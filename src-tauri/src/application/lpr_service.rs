
use tauri::{AppHandle, Manager, Emitter};
use crate::infrastructure::state::AppState;
use crate::infrastructure::python_client::{invoke_lpr_runtime, invoke_lpr_runtime_with_progress, terminate_lpr_runtime_process};
use crate::contracts::{
    LprRuntimeStatusPayload, LprTargetScanRequestPayload, LprTargetScanResponsePayload,
    LprFrameAnalysisRequestPayload, LprFrameAnalysisResponsePayload,
    LprIntervalAnalysisRequestPayload, LprIntervalAnalysisResponsePayload,
    AiEvidenceRequestPayload, AiEvidenceResponsePayload, AiEvidenceProgressPayload
};
use crate::editor::{
    emit_app_log, emit_lpr_request_log, emit_lpr_result_log, emit_lpr_progress,
    emit_ai_evidence_progress, emit_ai_evidence_progress_payload,
    finalize_ai_keyframe_artifacts, runtime_run_root, AI_EVIDENCE_WORKFLOW_STEP_COUNT,
    export_ai_evidence_clip
};
use std::time::{SystemTime, UNIX_EPOCH};

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

    pub fn analyze_ai_evidence(
        app_handle: AppHandle,
        request: AiEvidenceRequestPayload,
    ) -> Result<AiEvidenceResponsePayload, String> {
        let request_id = request.request_id.clone();
        emit_ai_evidence_progress(&app_handle, request_id.as_deref(), 0.05, "prepare", "Preparing AI evidence workflow.", false, false, Some("host-step"), None, None, Some(1), Some(AI_EVIDENCE_WORKFLOW_STEP_COUNT), Some(1), Some(1));
        
        emit_app_log(
            &app_handle,
            "info",
            "AiEvidenceRequest",
            format!("requestId={} description={} vehicleKind={} compressionMode={}", request.request_id.as_deref().unwrap_or("-"), request.description.as_str(), request.target_vehicle_kind.as_str(), if request.compression_mode.is_compact() { "compact" } else { "standard" }),
        );

        let mut response: AiEvidenceResponsePayload = invoke_lpr_runtime_with_progress(
            app_handle.clone(),
            "ai-evidence",
            &request,
            |app_handle, progress: AiEvidenceProgressPayload| {
                emit_ai_evidence_progress_payload(app_handle, progress);
            },
        )?;
        finalize_ai_keyframe_artifacts(&mut response, request.compression_mode)?;

        if let Some(interval) = response.interval.clone() {
            let request_folder = response.request_id.clone().or_else(|| request.request_id.clone()).unwrap_or_else(|| format!("ai-evidence-{}", SystemTime::now().duration_since(UNIX_EPOCH).map(|value| value.as_millis()).unwrap_or(0)));
            let clip_path = runtime_run_root(&request_folder)?.join("ai-evidence").join("clip.mp4");
            
            emit_ai_evidence_progress(&app_handle, response.request_id.as_deref(), 0.8, "export-clip", "Exporting resolved AI evidence clip.", false, false, Some("host-step"), None, None, Some(10), Some(AI_EVIDENCE_WORKFLOW_STEP_COUNT), Some(1), Some(1));
            export_ai_evidence_clip(&request.source_path, interval.start_ms, interval.end_ms, &clip_path, request.compression_mode, request.audio_bitrate_kbps)?;
            response.clip_path = Some(clip_path.to_string_lossy().to_string());
        }

        emit_ai_evidence_progress(&app_handle, payload_request_id(&response.request_id, &request_id), 1.0, "completed", "AI evidence workflow completed.", true, false, Some("host-step"), None, None, Some(11), Some(AI_EVIDENCE_WORKFLOW_STEP_COUNT), Some(1), Some(1));
        emit_app_log(&app_handle, "info", "AiEvidenceResult", format!("requestId={} plate={} clip={} keyframes={}", payload_request_id(&response.request_id, &request_id).unwrap_or("-"), response.plate_number.as_deref().unwrap_or("-"), response.clip_path.as_deref().unwrap_or("-"), response.keyframes.len()));
        
        Ok(response)
    }
}

fn payload_request_id<'a>(res: &'a Option<String>, req: &'a Option<String>) -> Option<&'a str> {
    res.as_deref().or(req.as_deref())
}
