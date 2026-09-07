use std::path::Path;

use serde_json::{json, Value};

use crate::ai::agents::{AgentFactory, AgentType};
use crate::contracts::{
    AiEvidenceProgressKind, AiEvidenceRequestPayload, AiEvidenceToolCallPayload,
};
use crate::editor::{emit_ai_evidence_progress, AI_EVIDENCE_WORKFLOW_STEP_COUNT};
use crate::infrastructure::python_client::invoke_lpr_runtime;

use super::types::{load_and_encode_images, now_ms, StoryboardFrameItem, StoryboardFramesResponse};
use super::AiEvidenceWorkflowEngine;

impl AiEvidenceWorkflowEngine {
    pub(crate) async fn sample_fine_storyboard(
        &self,
        request: &AiEvidenceRequestPayload,
        request_id: &str,
        coarse_storyboard: &StoryboardFramesResponse,
        coarse_start_ms: i64,
        coarse_end_ms: i64,
        fine_dir: &Path,
    ) -> Result<(StoryboardFramesResponse, i64, i64), String> {
        emit_ai_evidence_progress(
            &self.app_handle,
            Some(request_id),
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

        Ok((fine_storyboard, fine_start, fine_end))
    }

    pub(crate) async fn localize_fine_keyframes(
        &self,
        request: &AiEvidenceRequestPayload,
        request_id: &str,
        fine_storyboard: &StoryboardFramesResponse,
        t_fine_start: f64,
        tool_calls: &mut Vec<AiEvidenceToolCallPayload>,
    ) -> Result<(StoryboardFrameItem, i64, String, Value), String> {
        emit_ai_evidence_progress(
            &self.app_handle,
            Some(request_id),
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

        Ok((anchor_frame_item, anchor_time_ms, fine_summary, fine_output))
    }
}
