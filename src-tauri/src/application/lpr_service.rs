
use tauri::{AppHandle, Manager, Emitter};
use crate::infrastructure::state::AppState;
use crate::infrastructure::python_client::{invoke_lpr_runtime, terminate_lpr_runtime_process};
use crate::contracts::{
    LprRuntimeStatusPayload, LprTargetScanRequestPayload, LprTargetScanResponsePayload,
    LprFrameAnalysisRequestPayload, LprFrameAnalysisResponsePayload,
    LprIntervalAnalysisRequestPayload, LprIntervalAnalysisResponsePayload,
    AiEvidenceRequestPayload, AiEvidenceResponsePayload,
};
use crate::editor::{
    emit_app_log, emit_lpr_request_log, emit_lpr_result_log, emit_lpr_progress,
};

pub struct LprService;

impl LprService {
    pub fn broadcast_state(app_handle: &AppHandle) {
        let state = app_handle.state::<AppState>();
        if let Ok(workspace) = state.workspace.lock() {
            let _ = app_handle.emit("editor/state-updated", &*workspace);
        };
    }

    pub fn get_runtime_status(app_handle: AppHandle) -> Result<LprRuntimeStatusPayload, String> {
        let status: LprRuntimeStatusPayload = invoke_lpr_runtime(app_handle.clone(), "status", &serde_json::json!({}))?;
        
        let state = app_handle.state::<AppState>();
        if let Ok(mut workspace) = state.workspace.lock() {
            workspace.analysis.lpr_runtime_status = Some(status.clone());
        };
        Self::broadcast_state(&app_handle);
        
        Ok(status)
    }

    pub fn cancel_job(app_handle: AppHandle) -> Result<bool, String> {
        let state = app_handle.state::<AppState>();
        state.job_manager.cancel_job();
        let result = terminate_lpr_runtime_process(&app_handle, "ui-request");
        Self::broadcast_state(&app_handle);
        result
    }

    pub fn scan_targets(
        app_handle: AppHandle,
        request: LprTargetScanRequestPayload,
    ) -> Result<LprTargetScanResponsePayload, String> {
        emit_lpr_request_log(&app_handle, "scan-targets", request.request_id.as_deref(), None, false);
        let response: LprTargetScanResponsePayload = invoke_lpr_runtime(app_handle.clone(), "scan-targets", &request)?;
        emit_app_log(
            &app_handle,
            "info",
            "LprRuntimeResult",
            format!("command=scan-targets requestId={} detections={}", request.request_id.as_deref().unwrap_or("-"), response.detections.len()),
        );
        Ok(response)
    }

    pub fn analyze_frame(
        app_handle: AppHandle,
        request: LprFrameAnalysisRequestPayload,
    ) -> Result<LprFrameAnalysisResponsePayload, String> {
        emit_lpr_request_log(&app_handle, "analyze-frame", request.request_id.as_deref(), request.analysis_profile_id.as_deref(), request.enable_developer_diagnostics.unwrap_or(false));
        let response: LprFrameAnalysisResponsePayload = invoke_lpr_runtime(app_handle.clone(), "analyze-frame", &request)
            .inspect_err(|error| {
                emit_lpr_progress(&app_handle, request.request_id.as_deref(), 1.0, "Frame", error.clone(), true, true, Some("runtime-error"), None, None);
            })?;
        emit_lpr_result_log(&app_handle, &response.provenance, &response.review, response.candidates.len());
        Ok(response)
    }

    pub fn analyze_interval(
        app_handle: AppHandle,
        request: LprIntervalAnalysisRequestPayload,
    ) -> Result<LprIntervalAnalysisResponsePayload, String> {
        emit_lpr_request_log(&app_handle, "analyze-interval", request.request_id.as_deref(), request.analysis_profile_id.as_deref(), request.enable_developer_diagnostics.unwrap_or(false));
        let response: LprIntervalAnalysisResponsePayload = invoke_lpr_runtime(app_handle.clone(), "analyze-interval", &request)
            .inspect_err(|error| {
                emit_lpr_progress(&app_handle, request.request_id.as_deref(), 1.0, "Interval", error.clone(), true, true, Some("runtime-error"), None, None);
            })?;
        emit_lpr_result_log(&app_handle, &response.provenance, &response.review, response.candidates.len());
        Ok(response)
    }

    pub async fn analyze_ai_evidence(
        app_handle: AppHandle,
        request: AiEvidenceRequestPayload,
    ) -> Result<AiEvidenceResponsePayload, String> {
        emit_app_log(
            &app_handle,
            "info",
            "AiEvidenceRequest",
            format!(
                "requestId={} description={} vehicleKind={} compressionMode={}",
                request.request_id.as_deref().unwrap_or("-"),
                request.description.as_str(),
                request.target_vehicle_kind.as_str(),
                if request.compression_mode.is_compact() { "compact" } else { "standard" }
            ),
        );

        let (provider, model) = crate::ai::workflow::AiEvidenceWorkflowEngine::resolve_default_provider()?;
        let engine = crate::ai::workflow::AiEvidenceWorkflowEngine::new(app_handle.clone(), provider, model);
        let response = engine.run(request).await?;

        emit_app_log(
            &app_handle,
            "info",
            "AiEvidenceResult",
            format!(
                "requestId={} plate={} clip={} keyframes={}",
                response.request_id.as_deref().unwrap_or("-"),
                response.plate_number.as_deref().unwrap_or("-"),
                response.clip_path.as_deref().unwrap_or("-"),
                response.keyframes.len()
            ),
        );

        Ok(response)
    }
}
