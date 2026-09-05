use serde::{Deserialize, Serialize};

use crate::contracts::{RenderProfilePayload, TimelineClipPayload, TimelineTrackPayload};
use super::lpr::EditorAnalysisState;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EditorAsset {
    pub id: String,
    pub name: String,
    pub path: String,
    pub file_size: u64,
    pub created_at: String,
    pub modified_at: String,
    pub status: String, // "ready" | "missing"
    pub url: Option<String>,
    pub thumbnail_url: Option<String>,
    pub has_video: bool,
    pub has_audio: bool,
    pub duration_ms: u64,
    pub fps: Option<u32>,
    pub audio_bitrate_kbps: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EditorFileState {
    pub id: String,
    pub asset: EditorAsset,
    pub track: TimelineTrackPayload,
    pub clips: Vec<TimelineClipPayload>,
    pub render_profile: RenderProfilePayload,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct EditorWorkspaceState {
    pub workspace_name: String,
    pub active_file_id: Option<String>,
    pub files: Vec<EditorFileState>,
    pub analysis: EditorAnalysisState,
}
