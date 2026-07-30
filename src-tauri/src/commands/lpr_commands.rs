use tauri::AppHandle;
use crate::application::lpr_service::LprService;
use crate::contracts::LprRuntimeStatusPayload;

#[tauri::command]
pub async fn get_lpr_runtime_status(
    app_handle: AppHandle,
) -> Result<LprRuntimeStatusPayload, String> {
    tauri::async_runtime::spawn_blocking(move || LprService::get_runtime_status(app_handle))
        .await
        .map_err(|error| format!("Failed to join runtime status task: {}", error))?
}

#[tauri::command]
pub fn cancel_lpr_runtime_job(
    app_handle: AppHandle,
) -> Result<bool, String> {
    LprService::cancel_job(app_handle)
}

#[tauri::command]
pub async fn scan_lpr_targets(
    app_handle: AppHandle,
    request: crate::contracts::LprTargetScanRequestPayload,
) -> Result<crate::contracts::LprTargetScanResponsePayload, String> {
    tauri::async_runtime::spawn_blocking(move || LprService::scan_targets(app_handle, request))
        .await
        .map_err(|error| format!("Failed to join target scan task: {}", error))
        .and_then(|res| res)
}

#[tauri::command]
pub async fn analyze_lpr_frame(
    app_handle: AppHandle,
    request: crate::contracts::LprFrameAnalysisRequestPayload,
) -> Result<crate::contracts::LprFrameAnalysisResponsePayload, String> {
    tauri::async_runtime::spawn_blocking(move || LprService::analyze_frame(app_handle, request))
        .await
        .map_err(|error| format!("Failed to join frame analysis task: {}", error))
        .and_then(|res| res)
}

#[tauri::command]
pub async fn analyze_lpr_interval(
    app_handle: AppHandle,
    request: crate::contracts::LprIntervalAnalysisRequestPayload,
) -> Result<crate::contracts::LprIntervalAnalysisResponsePayload, String> {
    tauri::async_runtime::spawn_blocking(move || LprService::analyze_interval(app_handle, request))
        .await
        .map_err(|error| format!("Failed to join interval analysis task: {}", error))
        .and_then(|res| res)
}

#[tauri::command]
pub async fn analyze_ai_evidence(
    app_handle: AppHandle,
    request: crate::contracts::AiEvidenceRequestPayload,
) -> Result<crate::contracts::AiEvidenceResponsePayload, String> {
    tauri::async_runtime::spawn_blocking(move || LprService::analyze_ai_evidence(app_handle, request))
        .await
        .map_err(|error| format!("Failed to join ai evidence task: {}", error))
        .and_then(|res| res)
}
