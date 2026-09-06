use std::fs;
use std::path::Path;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use base64::Engine;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::AppHandle;

use crate::ai::agents::{AgentFactory, AgentType};
use crate::ai::providers::{AIProvider, ProviderFactory};
use crate::contracts::{
    AiEvidenceKeyframePayload, AiEvidenceOverlayBoxPayload, AiEvidenceProgressKind,
    AiEvidenceProviderKind, AiEvidenceRequestPayload, AiEvidenceResponsePayload,
    AiEvidenceSharedProjectionPayload, AiEvidenceTargetSelectionPayload,
    AiEvidenceTimelineFrameRefPayload, AiEvidenceToolCallPayload,
    LprIntervalAnalysisResponsePayload, LprProgressPayload,
    LprTargetScanResponsePayload, TimelineIntervalSelectionPayload,
    VideoMarkerRectPayload,
};
use crate::editor::{
    emit_ai_evidence_progress, export_ai_evidence_clip, finalize_ai_keyframe_artifacts,
    runtime_run_root, AI_EVIDENCE_WORKFLOW_STEP_COUNT,
};
use crate::infrastructure::python_client::{invoke_lpr_runtime, invoke_lpr_runtime_with_progress};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoryboardFrameItem {
    pub frame_id: String,
    pub time_ms: i64,
    pub sequence_index: usize,
    pub label: String,
    pub image_path: String,
    pub frame_width: u32,
    pub frame_height: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoryboardFramesResponse {
    pub source_path: String,
    pub duration_ms: i64,
    pub output_dir: String,
    pub frames: Vec<StoryboardFrameItem>,
}

pub struct AiEvidenceWorkflowEngine {
    app_handle: AppHandle,
    provider: Arc<dyn AIProvider>,
    model: String,
}

impl AiEvidenceWorkflowEngine {
    pub fn new(app_handle: AppHandle, provider: Arc<dyn AIProvider>, model: String) -> Self {
        Self {
            app_handle,
            provider,
            model,
        }
    }

    pub fn resolve_default_provider() -> Result<(Arc<dyn AIProvider>, String), String> {
        let provider_name = std::env::var("TRAFFIC_AI_PROVIDER")
            .unwrap_or_else(|_| "ollama".to_string())
            .to_lowercase();
        let model = std::env::var("TRAFFIC_AI_MODEL")
            .unwrap_or_else(|_| match provider_name.as_str() {
                "geminiflow" => "gemini-2.5-flash".to_string(),
                "vertexai" => "gemini-2.5-flash".to_string(),
                _ => "qwen2.5-vl".to_string(),
            });
        let base_url = std::env::var("TRAFFIC_AI_BASE_URL").ok();
        let provider = ProviderFactory::create_provider(&provider_name, &model, base_url.as_deref())
            .map_err(|e| format!("Failed to create AI provider: {}", e))?;
        Ok((provider, model))
    }

    pub async fn run(
        &self,
        request: AiEvidenceRequestPayload,
    ) -> Result<AiEvidenceResponsePayload, String> {
        let request_id = request
            .request_id
            .clone()
            .unwrap_or_else(|| format!("ai-evidence-{}", now_ms()));

        let run_dir = runtime_run_root(&request_id)?.join("ai-evidence");
        let coarse_dir = run_dir.join("coarse");
        let fine_dir = run_dir.join("fine");
        let keyframes_dir = run_dir.join("keyframes");

        fs::create_dir_all(&run_dir).map_err(|e| e.to_string())?;
        fs::create_dir_all(&coarse_dir).map_err(|e| e.to_string())?;
        fs::create_dir_all(&fine_dir).map_err(|e| e.to_string())?;
        fs::create_dir_all(&keyframes_dir).map_err(|e| e.to_string())?;

        let mut tool_calls: Vec<AiEvidenceToolCallPayload> = Vec::new();

        // 1. Prepare
        emit_ai_evidence_progress(
            &self.app_handle,
            Some(&request_id),
            0.05,
            "prepare",
            "Preparing AI evidence workflow.",
            false,
            false,
            Some(AiEvidenceProgressKind::HostStep),
            None,
            None,
            Some(1),
            Some(AI_EVIDENCE_WORKFLOW_STEP_COUNT),
            Some(1),
            Some(1),
        );

        // 2. Coarse Storyboard Sampling
        let t_coarse_start = now_ms() as f64;
        emit_ai_evidence_progress(
            &self.app_handle,
            Some(&request_id),
            0.15,
            "coarse-storyboard",
            "Sampling coarse storyboard frames.",
            false,
            false,
            Some(AiEvidenceProgressKind::HostStep),
            None,
            None,
            Some(2),
            Some(AI_EVIDENCE_WORKFLOW_STEP_COUNT),
            Some(1),
            Some(2),
        );

        let coarse_sample_step = request.coarse_sample_every_ms.unwrap_or(2000.0) as i64;
        let coarse_sample_cmd = json!({
            "sourcePath": request.source_path,
            "sampleEveryMs": coarse_sample_step,
            "prefix": "coarse",
            "outputDir": coarse_dir.to_string_lossy(),
            "showHeader": true,
            "requestId": request_id,
        });

        let coarse_storyboard: StoryboardFramesResponse = invoke_lpr_runtime(
            self.app_handle.clone(),
            "sample-storyboard-frames",
            &coarse_sample_cmd,
        )?;

        if coarse_storyboard.frames.is_empty() {
            return Err("Coarse storyboard sampling produced no frames.".to_string());
        }

        // 3. AI Coarse Localization
        emit_ai_evidence_progress(
            &self.app_handle,
            Some(&request_id),
            0.25,
            "coarse-localization",
            "AI localizing vehicle appearance interval...",
            false,
            false,
            Some(AiEvidenceProgressKind::ToolCall),
            None,
            None,
            Some(3),
            Some(AI_EVIDENCE_WORKFLOW_STEP_COUNT),
            Some(2),
            Some(2),
        );

        let coarse_images = load_and_encode_images(&coarse_storyboard.frames)?;
        let coarse_agent = AgentFactory::create_agent(
            AgentType::CoarseLocalization,
            self.provider.clone(),
            self.model.clone(),
        );

        let coarse_frames_meta: Vec<Value> = coarse_storyboard.frames.iter().map(|f| json!({
            "frameId": f.frame_id,
            "timeMs": f.time_ms,
            "label": f.label,
        })).collect();

        let coarse_input = json!({
            "description": request.description,
            "frames": coarse_frames_meta,
            "images": coarse_images,
        });

        let coarse_output = coarse_agent
            .execute(coarse_input)
            .await
            .map_err(|e| format!("Coarse Localization Agent failed: {}", e))?;

        let coarse_start_id = coarse_output.get("startFrameId").and_then(Value::as_str).unwrap_or("");
        let coarse_end_id = coarse_output.get("endFrameId").and_then(Value::as_str).unwrap_or("");
        let coarse_summary = coarse_output.get("summary").and_then(Value::as_str).unwrap_or("").to_string();

        let coarse_start_ms = coarse_storyboard
            .frames
            .iter()
            .find(|f| f.frame_id == coarse_start_id)
            .map(|f| f.time_ms)
            .unwrap_or_else(|| coarse_storyboard.frames.first().map(|f| f.time_ms).unwrap_or(0));

        let coarse_end_ms = coarse_storyboard
            .frames
            .iter()
            .find(|f| f.frame_id == coarse_end_id)
            .map(|f| f.time_ms)
            .unwrap_or_else(|| coarse_storyboard.frames.last().map(|f| f.time_ms).unwrap_or(coarse_storyboard.duration_ms));

        tool_calls.push(AiEvidenceToolCallPayload {
            stage: "coarse-localization".to_string(),
            tool_name: "coarse_localization_agent".to_string(),
            input_summary: format!("description={}, frames={}", request.description, coarse_storyboard.frames.len()),
            output_summary: format!("interval={}ms-{}ms, summary={}", coarse_start_ms, coarse_end_ms, coarse_summary),
            started_at_ms: t_coarse_start,
            completed_at_ms: now_ms() as f64,
            success: true,
        });

        // 4. Fine Storyboard Sampling
        let t_fine_start = now_ms() as f64;
        emit_ai_evidence_progress(
            &self.app_handle,
            Some(&request_id),
            0.35,
            "fine-storyboard",
            "Sampling fine storyboard frames.",
            false,
            false,
            Some(AiEvidenceProgressKind::HostStep),
            None,
            None,
            Some(4),
            Some(AI_EVIDENCE_WORKFLOW_STEP_COUNT),
            Some(1),
            Some(2),
        );

        let padding_ms = request.fine_window_padding_ms.unwrap_or(2000.0) as i64;
        let fine_start = (coarse_start_ms - padding_ms).max(0);
        let fine_end = (coarse_end_ms + padding_ms).min(coarse_storyboard.duration_ms);
        let fine_step = request.fine_sample_every_ms.unwrap_or(300.0) as i64;

        let fine_sample_cmd = json!({
            "sourcePath": request.source_path,
            "startMs": fine_start,
            "endMs": fine_end,
            "sampleEveryMs": fine_step,
            "prefix": "fine",
            "outputDir": fine_dir.to_string_lossy(),
            "showHeader": true,
            "requestId": request_id,
        });

        let fine_storyboard: StoryboardFramesResponse = invoke_lpr_runtime(
            self.app_handle.clone(),
            "sample-storyboard-frames",
            &fine_sample_cmd,
        )?;

        if fine_storyboard.frames.is_empty() {
            return Err("Fine storyboard sampling produced no frames.".to_string());
        }

        // 5. AI Fine Localization & Keyframe Selection
        emit_ai_evidence_progress(
            &self.app_handle,
            Some(&request_id),
            0.45,
            "fine-localization",
            "AI selecting optimal keyframes and anchor...",
            false,
            false,
            Some(AiEvidenceProgressKind::ToolCall),
            None,
            None,
            Some(5),
            Some(AI_EVIDENCE_WORKFLOW_STEP_COUNT),
            Some(2),
            Some(2),
        );

        let fine_images = load_and_encode_images(&fine_storyboard.frames)?;
        let fine_agent = AgentFactory::create_agent(
            AgentType::FineLocalization,
            self.provider.clone(),
            self.model.clone(),
        );

        let fine_frames_meta: Vec<Value> = fine_storyboard.frames.iter().map(|f| json!({
            "frameId": f.frame_id,
            "timeMs": f.time_ms,
            "label": f.label,
        })).collect();

        let fine_input = json!({
            "description": request.description,
            "frames": fine_frames_meta,
            "images": fine_images,
            "maxKeyframes": request.max_keyframes.unwrap_or(8),
        });

        let fine_output = fine_agent
            .execute(fine_input)
            .await
            .map_err(|e| format!("Fine Localization Agent failed: {}", e))?;

        let anchor_id = fine_output.get("anchorFrameId").and_then(Value::as_str).unwrap_or("");
        let fine_summary = fine_output.get("summary").and_then(Value::as_str).unwrap_or("").to_string();

        let anchor_frame_item = fine_storyboard
            .frames
            .iter()
            .find(|f| f.frame_id == anchor_id)
            .or_else(|| fine_storyboard.frames.get(fine_storyboard.frames.len() / 2))
            .cloned()
            .ok_or_else(|| "Could not locate anchor frame.".to_string())?;

        let anchor_time_ms = anchor_frame_item.time_ms;

        tool_calls.push(AiEvidenceToolCallPayload {
            stage: "fine-localization".to_string(),
            tool_name: "fine_localization_agent".to_string(),
            input_summary: format!("frames={}, maxKeyframes={:?}", fine_storyboard.frames.len(), request.max_keyframes),
            output_summary: format!("anchorId={}, anchorTimeMs={}ms, summary={}", anchor_id, anchor_time_ms, fine_summary),
            started_at_ms: t_fine_start,
            completed_at_ms: now_ms() as f64,
            success: true,
        });

        // 6. Scan Targets on Anchor Frame
        let t_target_start = now_ms() as f64;
        emit_ai_evidence_progress(
            &self.app_handle,
            Some(&request_id),
            0.55,
            "scan-targets",
            "Detecting vehicle candidates on anchor frame...",
            false,
            false,
            Some(AiEvidenceProgressKind::HostStep),
            None,
            None,
            Some(6),
            Some(AI_EVIDENCE_WORKFLOW_STEP_COUNT),
            Some(1),
            Some(2),
        );

        let scan_cmd = json!({
            "sourcePath": request.source_path,
            "timeMs": anchor_time_ms,
            "targetVehicleKind": request.target_vehicle_kind.as_str(),
            "markerRect": request.marker_rect,
            "requestId": request_id,
        });

        let scan_res: LprTargetScanResponsePayload = invoke_lpr_runtime(
            self.app_handle.clone(),
            "scan-targets",
            &scan_cmd,
        )?;

        // 7. Target Resolution
        let (selected_box, selected_track_id): (Option<VideoMarkerRectPayload>, Option<String>) = if scan_res.detections.is_empty() {
            (request.marker_rect.clone(), None)
        } else if scan_res.detections.len() == 1 {
            let det = &scan_res.detections[0];
            (Some(det.r#box.clone()), Some(det.id.clone()))
        } else {
            emit_ai_evidence_progress(
                &self.app_handle,
                Some(&request_id),
                0.62,
                "target-resolution",
                "AI resolving target vehicle against description...",
                false,
                false,
                Some(AiEvidenceProgressKind::ToolCall),
                None,
                None,
                Some(7),
                Some(AI_EVIDENCE_WORKFLOW_STEP_COUNT),
                Some(2),
                Some(2),
            );

            let target_agent = AgentFactory::create_agent(
                AgentType::TargetResolution,
                self.provider.clone(),
                self.model.clone(),
            );

            let targets_meta: Vec<Value> = scan_res.detections.iter().map(|d| json!({
                "trackId": d.id,
                "className": d.class_name,
                "confidence": d.confidence,
                "box": d.r#box,
            })).collect();

            let target_input = json!({
                "description": request.description,
                "targets": targets_meta,
                "anchorTimeMs": anchor_time_ms,
            });

            let target_output: Option<Value> = target_agent.execute(target_input).await.ok();
            let selected_id = target_output.as_ref().and_then(|o| o.get("selectedTrackId")).and_then(Value::as_str);

            if let Some(id) = selected_id {
                if let Some(det) = scan_res.detections.iter().find(|d| d.id == id) {
                    (Some(det.r#box.clone()), Some(det.id.clone()))
                } else {
                    (Some(scan_res.detections[0].r#box.clone()), Some(scan_res.detections[0].id.clone()))
                }
            } else {
                (Some(scan_res.detections[0].r#box.clone()), Some(scan_res.detections[0].id.clone()))
            }
        };

        tool_calls.push(AiEvidenceToolCallPayload {
            stage: "target-resolution".to_string(),
            tool_name: "target_resolution_agent".to_string(),
            input_summary: format!("targets={}", scan_res.detections.len()),
            output_summary: format!("selectedTrackId={:?}, hasBox={}", selected_track_id, selected_box.is_some()),
            started_at_ms: t_target_start,
            completed_at_ms: now_ms() as f64,
            success: true,
        });

        // 8. Range Analysis (analyze-interval)
        emit_ai_evidence_progress(
            &self.app_handle,
            Some(&request_id),
            0.70,
            "analyze-interval",
            "Tracking target vehicle across interval and recognizing plate...",
            false,
            false,
            Some(AiEvidenceProgressKind::HostStep),
            None,
            None,
            Some(8),
            Some(AI_EVIDENCE_WORKFLOW_STEP_COUNT),
            Some(1),
            Some(1),
        );

        let final_start_ms = fine_start as f64;
        let final_end_ms = fine_end as f64;

        let interval_cmd = json!({
            "sourcePath": request.source_path,
            "interval": {
                "startMs": final_start_ms,
                "endMs": final_end_ms,
            },
            "anchorTimeMs": anchor_time_ms as f64,
            "targetVehicleKind": request.target_vehicle_kind.as_str(),
            "markerRect": request.marker_rect,
            "selectedTargetBox": selected_box,
            "selectedTargetTrackId": selected_track_id,
            "countryHints": request.country_hints,
            "analysisProfileId": request.analysis_profile_id,
            "enableDeveloperDiagnostics": request.enable_developer_diagnostics,
            "requestId": request_id,
        });

        let interval_res: LprIntervalAnalysisResponsePayload = invoke_lpr_runtime_with_progress(
            self.app_handle.clone(),
            "analyze-interval",
            &interval_cmd,
            |app_handle, progress: LprProgressPayload| {
                emit_ai_evidence_progress(
                    app_handle,
                    progress.request_id.as_deref(),
                    0.70 + (progress.progress * 0.15),
                    "range-analysis",
                    &progress.detail,
                    false,
                    false,
                    Some(AiEvidenceProgressKind::HostStep),
                    None,
                    None,
                    Some(8),
                    Some(AI_EVIDENCE_WORKFLOW_STEP_COUNT),
                    Some(1),
                    Some(1),
                );
            },
        )?;

        // 9. Export Evidence Clip
        emit_ai_evidence_progress(
            &self.app_handle,
            Some(&request_id),
            0.88,
            "export-clip",
            "Exporting resolved AI evidence clip.",
            false,
            false,
            Some(AiEvidenceProgressKind::HostStep),
            None,
            None,
            Some(10),
            Some(AI_EVIDENCE_WORKFLOW_STEP_COUNT),
            Some(1),
            Some(1),
        );

        let clip_path = run_dir.join("clip.mp4");
        export_ai_evidence_clip(
            &request.source_path,
            final_start_ms,
            final_end_ms,
            &clip_path,
            request.compression_mode,
            request.audio_bitrate_kbps,
        )?;

        // 10. Assemble Response Payload
        let primary_candidate = interval_res.candidates.first().cloned();
        let plate_number = primary_candidate.as_ref().map(|c| c.text.clone());

        let mut keyframes: Vec<AiEvidenceKeyframePayload> = Vec::new();
        if let Some(keyframes_val) = fine_output.get("keyframes") {
            if let Some(keyframes_arr) = keyframes_val.as_array() {
                for (idx, kf) in keyframes_arr.iter().enumerate() {
                    let frame_id = kf.get("frameId").and_then(Value::as_str).unwrap_or("");
                    let desc = kf.get("description").and_then(Value::as_str).unwrap_or("");
                    if let Some(frame_item) = fine_storyboard.frames.iter().find(|f| f.frame_id == frame_id) {
                        keyframes.push(AiEvidenceKeyframePayload {
                            frame: AiEvidenceTimelineFrameRefPayload {
                                frame_id: frame_item.frame_id.clone(),
                                time_ms: frame_item.time_ms as f64,
                                sequence_index: idx as u32,
                                label: frame_item.label.clone(),
                                image_path: Some(frame_item.image_path.clone()),
                                frame_width: frame_item.frame_width,
                                frame_height: frame_item.frame_height,
                            },
                            description: desc.to_string(),
                            overlay: None,
                            keyframe_source: Some("fine-selection".to_string()),
                            description_source: Some("llm".to_string()),
                            box_source: None,
                            is_valid_for_user_facing_output: Some(true),
                            selected_for_target_resolution: Some(frame_item.frame_id == anchor_frame_item.frame_id),
                        });
                    }
                }
            }
        }

        let provider_kind = match self.provider.name().to_lowercase().as_str() {
            "geminiflow" => AiEvidenceProviderKind::Gemini,
            "vertexai" => AiEvidenceProviderKind::Gemini,
            _ => AiEvidenceProviderKind::Local,
        };

        let target_selection_payload = selected_box.as_ref().map(|sb| AiEvidenceTargetSelectionPayload {
            anchor_frame_id: anchor_frame_item.frame_id.clone(),
            selected_track_id: selected_track_id.clone(),
            selected_candidate_id: interval_res.accepted_candidate_id.clone(),
            confidence: 0.9,
            rationale: "Target selected by Multi-Agent resolution".to_string(),
            selected_box: Some(AiEvidenceOverlayBoxPayload {
                normalized_box: Some(sb.clone()),
                pixel_box: None,
                frame_width: anchor_frame_item.frame_width,
                frame_height: anchor_frame_item.frame_height,
            }),
        });

        let mut response = AiEvidenceResponsePayload {
            request_id: Some(request_id.clone()),
            description: request.description,
            summary: format!("{} {}", coarse_summary, fine_summary).trim().to_string(),
            provider: provider_kind,
            interval: Some(TimelineIntervalSelectionPayload {
                start_ms: final_start_ms,
                end_ms: final_end_ms,
            }),
            plate_number,
            plate_candidate: primary_candidate,
            primary_anchor: Some(AiEvidenceTimelineFrameRefPayload {
                frame_id: anchor_frame_item.frame_id,
                time_ms: anchor_frame_item.time_ms as f64,
                sequence_index: 0,
                label: anchor_frame_item.label,
                image_path: Some(anchor_frame_item.image_path),
                frame_width: anchor_frame_item.frame_width,
                frame_height: anchor_frame_item.frame_height,
            }),
            target_selection: target_selection_payload,
            keyframes,
            keyframe_count_reason: None,
            tool_calls,
            projection: AiEvidenceSharedProjectionPayload {
                interval: Some(TimelineIntervalSelectionPayload {
                    start_ms: final_start_ms,
                    end_ms: final_end_ms,
                }),
                target_tracks: interval_res.target_tracks,
                analysis_track: interval_res.analysis_track,
                selected_target_track_id: interval_res.accepted_candidate_id.clone(),
                samples: interval_res.samples,
                candidates: interval_res.candidates,
                accepted_candidate_id: interval_res.accepted_candidate_id,
                review: Some(interval_res.review),
                provenance: Some(interval_res.provenance),
                decision: interval_res.decision,
            },
            clip_path: Some(clip_path.to_string_lossy().to_string()),
            runtime: interval_res.runtime,
        };

        finalize_ai_keyframe_artifacts(&mut response, request.compression_mode)?;

        emit_ai_evidence_progress(
            &self.app_handle,
            Some(&request_id),
            1.0,
            "completed",
            "AI evidence workflow completed.",
            true,
            false,
            Some(AiEvidenceProgressKind::HostStep),
            None,
            None,
            Some(11),
            Some(AI_EVIDENCE_WORKFLOW_STEP_COUNT),
            Some(1),
            Some(1),
        );

        Ok(response)
    }
}

fn load_and_encode_images(frames: &[StoryboardFrameItem]) -> Result<Vec<String>, String> {
    let mut images = Vec::with_capacity(frames.len());
    for f in frames {
        let path = Path::new(&f.image_path);
        let bytes = fs::read(path).map_err(|e| format!("Failed to read image at {:?}: {}", path, e))?;
        let base64_str = base64::engine::general_purpose::STANDARD.encode(&bytes);
        images.push(base64_str);
    }
    Ok(images)
}

fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|v| v.as_millis())
        .unwrap_or(0)
}
