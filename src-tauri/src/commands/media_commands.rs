use tauri::AppHandle;
use crate::contracts::{
    FrameExportRequest, LprEvidenceExportRequestPayload, LprEvidenceExportResponsePayload,
    MediaProbePayload, TimelineExportRequest,
};

#[tauri::command]
#[specta::specta]
pub async fn probe_media_source(path: String) -> Result<MediaProbePayload, String> {
    crate::media::probe_media_source(path).await
}

#[tauri::command]
#[specta::specta]
pub fn save_generated_media_asset(source_path: String, output_path: String) -> Result<(), String> {
    crate::media::save_generated_media_asset(source_path, output_path)
}

#[tauri::command]
#[specta::specta]
pub fn export_frame_image(request: FrameExportRequest) -> Result<(), String> {
    crate::media::export_frame_image(request)
}

#[tauri::command]
#[specta::specta]
pub async fn export_lpr_evidence(
    app_handle: AppHandle,
    request: LprEvidenceExportRequestPayload,
) -> Result<LprEvidenceExportResponsePayload, String> {
    crate::media::export_lpr_evidence(app_handle, request).await
}

#[tauri::command]
#[specta::specta]
pub async fn process_timeline_export(
    app: AppHandle,
    request: TimelineExportRequest,
) -> Result<(), String> {
    crate::application::export_service::process_timeline_export(app, request).await
}
