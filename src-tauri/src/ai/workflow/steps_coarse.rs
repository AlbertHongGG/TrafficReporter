use std::path::Path;

use serde_json::{json, Value};

use crate::ai::agents::{AgentFactory, AgentType};
use crate::contracts::{
    AiEvidenceProgressKind, AiEvidenceRequestPayload, AiEvidenceToolCallPayload,
};
use crate::editor::{emit_ai_evidence_progress, AI_EVIDENCE_WORKFLOW_STEP_COUNT};
use crate::infrastructure::python_client::invoke_lpr_runtime;

use super::types::{load_and_encode_images, now_ms, StoryboardFramesResponse};
use super::AiEvidenceWorkflowEngine;

impl AiEvidenceWorkflowEngine {
    pub(crate) async fn sample_coarse_storyboard(
        &self,
        request: &AiEvidenceRequestPayload,
        request_id: &str,
        coarse_dir: &Path,
    ) -> Result<StoryboardFramesResponse, String> {
        emit_ai_evidence_progress(
            &self.app_handle,
            Some(request_id),
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

        Ok(coarse_storyboard)
    }

    pub(crate) async fn localize_coarse_interval(
        &self,
        request: &AiEvidenceRequestPayload,
        request_id: &str,
        coarse_storyboard: &StoryboardFramesResponse,
        t_coarse_start: f64,
        tool_calls: &mut Vec<AiEvidenceToolCallPayload>,
    ) -> Result<(i64, i64, String), String> {
        emit_ai_evidence_progress(
            &self.app_handle,
            Some(request_id),
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

        Ok((coarse_start_ms, coarse_end_ms, coarse_summary))
    }
}
