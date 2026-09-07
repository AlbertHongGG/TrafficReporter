use serde_json::{json, Value};

use crate::ai::agents::{AgentFactory, AgentType};
use crate::contracts::{
    AiEvidenceProgressKind, AiEvidenceRequestPayload, AiEvidenceToolCallPayload,
    LprTargetScanResponsePayload, VideoMarkerRectPayload,
};
use crate::editor::{emit_ai_evidence_progress, AI_EVIDENCE_WORKFLOW_STEP_COUNT};
use crate::infrastructure::python_client::invoke_lpr_runtime;

use super::types::now_ms;
use super::AiEvidenceWorkflowEngine;

impl AiEvidenceWorkflowEngine {
    pub(crate) async fn scan_anchor_targets(
        &self,
        request: &AiEvidenceRequestPayload,
        request_id: &str,
        anchor_time_ms: i64,
    ) -> Result<LprTargetScanResponsePayload, String> {
        emit_ai_evidence_progress(
            &self.app_handle,
            Some(request_id),
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

        Ok(scan_res)
    }

    pub(crate) async fn resolve_target_selection(
        &self,
        request: &AiEvidenceRequestPayload,
        request_id: &str,
        scan_res: &LprTargetScanResponsePayload,
        anchor_time_ms: i64,
        t_target_start: f64,
        tool_calls: &mut Vec<AiEvidenceToolCallPayload>,
    ) -> Result<(Option<VideoMarkerRectPayload>, Option<String>), String> {
        let (selected_box, selected_track_id): (Option<VideoMarkerRectPayload>, Option<String>) = if scan_res.detections.is_empty() {
            (request.marker_rect.clone(), None)
        } else if scan_res.detections.len() == 1 {
            let det = &scan_res.detections[0];
            (Some(det.r#box.clone()), Some(det.id.clone()))
        } else {
            emit_ai_evidence_progress(
                &self.app_handle,
                Some(request_id),
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

        Ok((selected_box, selected_track_id))
    }
}
