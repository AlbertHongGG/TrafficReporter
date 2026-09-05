use tauri::AppHandle;
use tauri::Manager;
use crate::infrastructure::state::AppState;
use crate::domain::project::EditorWorkspaceState;

#[tauri::command]
#[specta::specta]
pub fn get_app_state(app_handle: AppHandle) -> Result<EditorWorkspaceState, String> {
    let state = app_handle.state::<AppState>();
    let workspace = state.workspace.lock().map_err(|_| "Failed to lock workspace state".to_string())?;
    Ok(workspace.clone())
}

#[tauri::command]
#[specta::specta]
pub fn workspace_add_files(app_handle: AppHandle, assets: Vec<crate::domain::project::EditorAsset>) -> Result<(), String> {
    crate::application::workspace_service::WorkspaceService::add_files(app_handle, assets)
}

#[tauri::command]
#[specta::specta]
pub fn workspace_remove_file(app_handle: AppHandle, file_id: String) -> Result<(), String> {
    crate::application::workspace_service::WorkspaceService::remove_file(app_handle, file_id)
}

#[tauri::command]
#[specta::specta]
pub fn workspace_set_active_file(app_handle: AppHandle, file_id: String) -> Result<(), String> {
    crate::application::workspace_service::WorkspaceService::set_active_file(app_handle, file_id)
}

#[tauri::command]
#[specta::specta]
pub fn workspace_move_clip(app_handle: AppHandle, file_id: String, clip_id: String, start_ms: f64) -> Result<(), String> {
    crate::application::workspace_service::WorkspaceService::move_clip(app_handle, file_id, clip_id, start_ms)
}

#[tauri::command]
#[specta::specta]
pub fn workspace_trim_clip_start(app_handle: AppHandle, file_id: String, clip_id: String, in_point_ms: f64, start_ms: f64) -> Result<(), String> {
    crate::application::workspace_service::WorkspaceService::trim_clip_start(app_handle, file_id, clip_id, in_point_ms, start_ms)
}

#[tauri::command]
#[specta::specta]
pub fn workspace_trim_clip_end(app_handle: AppHandle, file_id: String, clip_id: String, out_point_ms: f64) -> Result<(), String> {
    crate::application::workspace_service::WorkspaceService::trim_clip_end(app_handle, file_id, clip_id, out_point_ms)
}

#[tauri::command]
#[specta::specta]
pub fn workspace_split_clip(app_handle: AppHandle, file_id: String, clip_id: String, at_ms: f64) -> Result<(), String> {
    crate::application::workspace_service::WorkspaceService::split_clip(app_handle, file_id, clip_id, at_ms)
}

#[tauri::command]
#[specta::specta]
pub fn workspace_delete_clips(app_handle: AppHandle, file_id: String, clip_ids: Vec<String>) -> Result<(), String> {
    crate::application::workspace_service::WorkspaceService::delete_clips(app_handle, file_id, clip_ids)
}

#[tauri::command]
#[specta::specta]
pub fn workspace_set_clips_muted(app_handle: AppHandle, file_id: String, clip_ids: Vec<String>, muted: bool) -> Result<(), String> {
    crate::application::workspace_service::WorkspaceService::set_clips_muted(app_handle, file_id, clip_ids, muted)
}

#[tauri::command]
#[specta::specta]
pub fn workspace_set_render_profile(app_handle: AppHandle, file_id: String, render_profile: crate::contracts::RenderProfilePayload) -> Result<(), String> {
    crate::application::workspace_service::WorkspaceService::set_render_profile(app_handle, file_id, render_profile)
}
