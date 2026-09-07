use tauri::AppHandle;

use crate::contracts::TimelineExportRequest;

/// Application-layer entry point for timeline export.
///
/// Keeps `commands` thin: commands only extract parameters and delegate here,
/// and all ffmpeg graph/codec/process logic stays behind this service boundary
/// inside `crate::export`.
pub async fn process_timeline_export(app: AppHandle, request: TimelineExportRequest) -> Result<(), String> {
    crate::export::process_timeline_export(app, request).await
}
