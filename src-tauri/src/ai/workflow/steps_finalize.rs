use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::contracts::{
    AiEvidenceKeyframePayload, AiEvidenceOverlayBoxPayload, AiEvidenceProgressKind,
    AiEvidenceProviderKind, AiEvidenceRequestPayload, AiEvidenceResponsePayload,
    AiEvidenceSharedProjectionPayload, AiEvidenceTargetSelectionPayload,
    AiEvidenceTimelineFrameRefPayload, AiEvidenceToolCallPayload,
    LprIntervalAnalysisResponsePayload, LprProgressPayload,
    TimelineIntervalSelectionPayload, VideoMarkerRectPayload,
};
use crate::editor::{
    emit_ai_evidence_progress, export_ai_evidence_clip, finalize_ai_keyframe_artifacts,
    AI_EVIDENCE_WORKFLOW_STEP_COUNT,
};
use crate::infrastructure::python_client::invoke_lpr_runtime_with_progress;

use super::types::{StoryboardFrameItem, StoryboardFramesResponse};
use super::AiEvidenceWorkflowEngine;

impl AiEvidenceWorkflowEngine {
    pub(crate) async fn analyze_target_interval(
        &self,
        request: &AiEvidenceRequestPayload,
        request_id: &str,
        fine_start: i64,
        fine_end: i64,
        anchor_time_ms: i64,
        selected_box: &Option<VideoMarkerRectPayload>,
        selected_track_id: &Option<String>,
    ) -> Result<(LprIntervalAnalysisResponsePayload, f64, f64), String> {
        emit_ai_evidence_progress(
            &self.app_handle,
            Some(request_id),
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

        Ok((interval_res, final_start_ms, final_end_ms))
    }

    pub(crate) fn export_evidence_clip(
        &self,
        request: &AiEvidenceRequestPayload,
        request_id: &str,
        run_dir: &Path,
        final_start_ms: f64,
        final_end_ms: f64,
    ) -> Result<PathBuf, String> {
        emit_ai_evidence_progress(
            &self.app_handle,
            Some(request_id),
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

        Ok(clip_path)
    }

    pub(crate) fn assemble_evidence_response(
        &self,
        request: AiEvidenceRequestPayload,
        request_id: String,
        coarse_summary: String,
        fine_summary: String,
        fine_output: &Value,
        fine_storyboard: &StoryboardFramesResponse,
        anchor_frame_item: StoryboardFrameItem,
        selected_box: Option<VideoMarkerRectPayload>,
        selected_track_id: Option<String>,
        interval_res: LprIntervalAnalysisResponsePayload,
        clip_path: PathBuf,
        final_start_ms: f64,
        final_end_ms: f64,
        tool_calls: Vec<AiEvidenceToolCallPayload>,
    ) -> Result<AiEvidenceResponsePayload, String> {
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

        Ok(response)
    }
}
