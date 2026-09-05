use tauri::{AppHandle, Emitter, Manager};
use crate::infrastructure::state::AppState;
use crate::contracts::{RenderProfilePayload, TimelineClipPayload, TimelineTrackPayload};
use crate::domain::project::{EditorAsset, EditorFileState, EditorWorkspaceState};

pub struct WorkspaceService;

impl WorkspaceService {
    fn get_state(app_handle: &AppHandle) -> std::sync::Arc<std::sync::Mutex<EditorWorkspaceState>> {
        app_handle.state::<AppState>().workspace.clone()
    }

    fn broadcast_state(app_handle: &AppHandle, state: &EditorWorkspaceState) {
        if let Err(e) = app_handle.emit("editor/state-updated", state) {
            eprintln!("Failed to broadcast state: {}", e);
        }
    }

    pub fn add_files(app_handle: AppHandle, assets: Vec<EditorAsset>) -> Result<(), String> {
        let state_arc = Self::get_state(&app_handle);
        let mut state = state_arc.lock().unwrap();

        let existing_paths: std::collections::HashSet<_> = state.files.iter().map(|f| f.asset.path.clone()).collect();
        let mut next_files = Vec::new();
        
        for mut asset in assets {
            if !existing_paths.contains(&asset.path) {
                if asset.file_size == 0.0 || asset.created_at.is_empty() || asset.modified_at.is_empty() {
                    if let Ok(metadata) = std::fs::metadata(&asset.path) {
                        if asset.file_size == 0.0 {
                            asset.file_size = metadata.len() as f64;
                        }
                        let now = std::time::SystemTime::now();
                        if asset.created_at.is_empty() {
                            let created = metadata.created().unwrap_or(now);
                            asset.created_at = chrono::DateTime::<chrono::Utc>::from(created).to_rfc3339();
                        }
                        if asset.modified_at.is_empty() {
                            let modified = metadata.modified().unwrap_or(now);
                            asset.modified_at = chrono::DateTime::<chrono::Utc>::from(modified).to_rfc3339();
                        }
                    }
                }
                if asset.status.is_empty() {
                    asset.status = "ready".to_string();
                }

                let track = TimelineTrackPayload {
                    id: format!("track-{}", uuid::Uuid::new_v4()),
                    name: "Track 1".to_string(),
                    order: 1,
                };
                let clip = TimelineClipPayload {
                    id: format!("clip-{}", uuid::Uuid::new_v4()),
                    asset_id: asset.id.clone(),
                    track_id: track.id.clone(),
                    start_ms: 0.0,
                    in_point_ms: 0.0,
                    out_point_ms: asset.duration_ms.max(120.0),
                    muted: false,
                };
                let fps = asset.fps.unwrap_or(60);
                
                let file_state = EditorFileState {
                    id: format!("file-{}", uuid::Uuid::new_v4()),
                    asset,
                    track,
                    clips: vec![clip],
                    render_profile: RenderProfilePayload {
                        format: "mp4".to_string(),
                        fps,
                        video_quality: Some("source".to_string()),
                        audio_bitrate_kbps: Some(320),
                        compression_mode: crate::contracts::OutputCompressionModePayload::Standard,
                    },
                };
                next_files.push(file_state);
            }
        }

        if next_files.is_empty() {
            return Ok(());
        }

        if let Some(last) = next_files.last() {
            state.active_file_id = Some(last.id.clone());
        }
        state.files.extend(next_files);

        Self::broadcast_state(&app_handle, &state);
        Ok(())
    }

    pub fn remove_file(app_handle: AppHandle, file_id: String) -> Result<(), String> {
        let state_arc = Self::get_state(&app_handle);
        let mut state = state_arc.lock().unwrap();

        let removing_index = state.files.iter().position(|f| f.id == file_id);
        if let Some(index) = removing_index {
            state.files.retain(|f| f.id != file_id);
            
            if state.files.is_empty() {
                state.active_file_id = None;
            } else if state.active_file_id == Some(file_id) {
                let fallback_index = std::cmp::min(index, state.files.len() - 1);
                state.active_file_id = Some(state.files[fallback_index].id.clone());
            }

            Self::broadcast_state(&app_handle, &state);
        }
        Ok(())
    }

    pub fn set_active_file(app_handle: AppHandle, file_id: String) -> Result<(), String> {
        let state_arc = Self::get_state(&app_handle);
        let mut state = state_arc.lock().unwrap();

        if state.files.iter().any(|f| f.id == file_id) && state.active_file_id != Some(file_id.clone()) {
            state.active_file_id = Some(file_id);
            Self::broadcast_state(&app_handle, &state);
        }
        Ok(())
    }

    fn sort_clips(clips: &mut Vec<TimelineClipPayload>) {
        clips.sort_by(|a, b| {
            a.start_ms
                .partial_cmp(&b.start_ms)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| a.id.cmp(&b.id))
        });
    }

    pub fn move_clip(app_handle: AppHandle, file_id: String, clip_id: String, start_ms: f64) -> Result<(), String> {
        let state_arc = Self::get_state(&app_handle);
        let mut state = state_arc.lock().unwrap();

        if let Some(file) = state.files.iter_mut().find(|f| f.id == file_id) {
            if let Some(clip) = file.clips.iter_mut().find(|c| c.id == clip_id) {
                clip.start_ms = start_ms;
            }
            Self::sort_clips(&mut file.clips);
            Self::broadcast_state(&app_handle, &state);
        }
        Ok(())
    }
    
    pub fn trim_clip_start(app_handle: AppHandle, file_id: String, clip_id: String, in_point_ms: f64, start_ms: f64) -> Result<(), String> {
        let state_arc = Self::get_state(&app_handle);
        let mut state = state_arc.lock().unwrap();

        if let Some(file) = state.files.iter_mut().find(|f| f.id == file_id) {
            if let Some(clip) = file.clips.iter_mut().find(|c| c.id == clip_id) {
                clip.in_point_ms = in_point_ms;
                clip.start_ms = start_ms;
            }
            Self::broadcast_state(&app_handle, &state);
        }
        Ok(())
    }

    pub fn trim_clip_end(app_handle: AppHandle, file_id: String, clip_id: String, out_point_ms: f64) -> Result<(), String> {
        let state_arc = Self::get_state(&app_handle);
        let mut state = state_arc.lock().unwrap();

        if let Some(file) = state.files.iter_mut().find(|f| f.id == file_id) {
            if let Some(clip) = file.clips.iter_mut().find(|c| c.id == clip_id) {
                clip.out_point_ms = out_point_ms;
            }
            Self::broadcast_state(&app_handle, &state);
        }
        Ok(())
    }

    pub fn split_clip(app_handle: AppHandle, file_id: String, clip_id: String, at_ms: f64) -> Result<(), String> {
        let state_arc = Self::get_state(&app_handle);
        let mut state = state_arc.lock().unwrap();

        if let Some(file) = state.files.iter_mut().find(|f| f.id == file_id) {
            let mut new_clip = None;
            if let Some(clip) = file.clips.iter_mut().find(|c| c.id == clip_id) {
                let local_offset_ms = at_ms - clip.start_ms;
                if local_offset_ms > 120.0 && (clip.out_point_ms - clip.in_point_ms) - local_offset_ms > 120.0 {
                    let split_in_point_ms = clip.in_point_ms + local_offset_ms;
                    
                    let right_clip = TimelineClipPayload {
                        id: format!("clip-{}", uuid::Uuid::new_v4()),
                        asset_id: clip.asset_id.clone(),
                        track_id: clip.track_id.clone(),
                        start_ms: at_ms,
                        in_point_ms: split_in_point_ms,
                        out_point_ms: clip.out_point_ms,
                        muted: clip.muted,
                    };
                    
                    clip.out_point_ms = split_in_point_ms;
                    new_clip = Some(right_clip);
                }
            }
            
            if let Some(right_clip) = new_clip {
                file.clips.push(right_clip);
                Self::sort_clips(&mut file.clips);
            }
            Self::broadcast_state(&app_handle, &state);
        }
        Ok(())
    }

    pub fn delete_clips(app_handle: AppHandle, file_id: String, clip_ids: Vec<String>) -> Result<(), String> {
        let state_arc = Self::get_state(&app_handle);
        let mut state = state_arc.lock().unwrap();

        if let Some(file) = state.files.iter_mut().find(|f| f.id == file_id) {
            file.clips.retain(|c| !clip_ids.contains(&c.id));
            Self::broadcast_state(&app_handle, &state);
        }
        Ok(())
    }

    pub fn set_clips_muted(app_handle: AppHandle, file_id: String, clip_ids: Vec<String>, muted: bool) -> Result<(), String> {
        let state_arc = Self::get_state(&app_handle);
        let mut state = state_arc.lock().unwrap();

        if let Some(file) = state.files.iter_mut().find(|f| f.id == file_id) {
            for clip in file.clips.iter_mut().filter(|c| clip_ids.contains(&c.id)) {
                clip.muted = muted;
            }
            Self::broadcast_state(&app_handle, &state);
        }
        Ok(())
    }

    pub fn set_render_profile(app_handle: AppHandle, file_id: String, render_profile: RenderProfilePayload) -> Result<(), String> {
        let state_arc = Self::get_state(&app_handle);
        let mut state = state_arc.lock().unwrap();

        if let Some(file) = state.files.iter_mut().find(|f| f.id == file_id) {
            file.render_profile = render_profile;
            Self::broadcast_state(&app_handle, &state);
        }
        Ok(())
    }
}
