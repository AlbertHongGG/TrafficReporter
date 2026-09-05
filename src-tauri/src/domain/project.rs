use serde::{Deserialize, Serialize};

use crate::contracts::{RenderProfilePayload, TimelineClipPayload, TimelineTrackPayload};
use super::lpr::EditorAnalysisState;

fn default_asset_status() -> String {
    "ready".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct EditorAsset {
    pub id: String,
    pub name: String,
    pub path: String,
    #[serde(default)]
    pub file_size: f64,
    #[serde(default)]
    pub created_at: String,
    #[serde(default)]
    pub modified_at: String,
    #[serde(default = "default_asset_status")]
    pub status: String, // "ready" | "missing"
    pub url: Option<String>,
    pub thumbnail_url: Option<String>,
    pub has_video: bool,
    pub has_audio: bool,
    pub duration_ms: f64,
    pub fps: Option<u32>,
    pub audio_bitrate_kbps: Option<u32>,
    pub width: Option<u32>,
    pub height: Option<u32>,
    pub kind: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct EditorFileState {
    pub id: String,
    pub asset: EditorAsset,
    pub track: TimelineTrackPayload,
    pub clips: Vec<TimelineClipPayload>,
    pub render_profile: RenderProfilePayload,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct EditorWorkspaceState {
    pub workspace_name: String,
    pub active_file_id: Option<String>,
    pub files: Vec<EditorFileState>,
    pub analysis: EditorAnalysisState,
}
