use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug)]
pub struct VideoInfo {
    pub title: String,
    pub thumbnail: String,
    pub duration: u32,
}

#[derive(Clone, Serialize)]
pub struct DownloadProgressPayload {
    pub percent: f64,
    pub status: String,
    pub status_text: String,
    pub phase: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MediaProbePayload {
    pub duration_ms: u64,
    pub has_video: bool,
    pub has_audio: bool,
    pub fps: Option<u32>,
    pub width: Option<u32>,
    pub height: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TimelineTrackPayload {
    pub id: String,
    pub name: String,
    pub order: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TimelineClipPayload {
    pub id: String,
    pub asset_id: String,
    pub track_id: String,
    pub start_ms: u64,
    pub in_point_ms: u64,
    pub out_point_ms: u64,
    pub muted: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum OutputCompressionModePayload {
    Standard,
    Compact,
}

impl OutputCompressionModePayload {
    pub fn is_compact(self) -> bool {
        matches!(self, Self::Compact)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RenderProfilePayload {
    pub format: String,
    pub fps: u32,
    pub video_quality: Option<String>,
    pub audio_bitrate_kbps: Option<u32>,
    pub compression_mode: OutputCompressionModePayload,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct VideoMarkerRectPayload {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

mod lpr_generated;

pub use lpr_generated::*;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExportSource {
    pub id: String,
    pub name: String,
    pub path: String,
    pub has_video: bool,
    pub has_audio: bool,
    pub width: Option<u32>,
    pub height: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExportSnapshotPayload {
    pub file_id: String,
    pub file_name: String,
    pub workspace_name: String,
    pub suggested_name: String,
    pub timeline_duration_ms: u64,
    pub has_video: bool,
    pub has_audio: bool,
    pub dominant_width: Option<u32>,
    pub dominant_height: Option<u32>,
    pub sources: Vec<ExportSource>,
    pub tracks: Vec<TimelineTrackPayload>,
    pub clips: Vec<TimelineClipPayload>,
    pub render_profile: RenderProfilePayload,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TimelineExportRequest {
    pub output_path: String,
    pub profile: RenderProfilePayload,
    pub snapshot: ExportSnapshotPayload,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FrameExportRequest {
    pub output_path: String,
    pub source_path: String,
    pub time_ms: u64,
    pub marker_rect: Option<VideoMarkerRectPayload>,
    pub compression_mode: OutputCompressionModePayload,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExportProgressPayload {
    pub progress: f64,
    pub stage: String,
    pub detail: String,
    pub done: bool,
    pub failed: bool,
}
