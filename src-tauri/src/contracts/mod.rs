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

    pub fn video_preset(self) -> &'static str {
        if self.is_compact() {
            "veryslow"
        } else {
            "medium"
        }
    }

    pub fn video_crf(self) -> &'static str {
        if self.is_compact() {
            "30"
        } else {
            "18"
        }
    }

    pub fn video_gop_size(self, fps: u32) -> u32 {
        let safe_fps = fps.max(1);
        if self.is_compact() {
            safe_fps.saturating_mul(4)
        } else {
            safe_fps.saturating_mul(2)
        }
    }

    pub fn video_min_keyframe_interval(self, fps: u32) -> u32 {
        let safe_fps = fps.max(1);
        if self.is_compact() {
            safe_fps
        } else {
            safe_fps / 2
        }
        .max(1)
    }

    pub fn video_b_frames(self) -> u32 {
        if self.is_compact() {
            3
        } else {
            2
        }
    }

    pub fn video_maxrate_kbps(self, width: u32, height: u32, fps: u32) -> Option<u32> {
        if !self.is_compact() {
            return None;
        }

        let longer_side = width.max(height);
        let base_kbps: u32 = match longer_side {
            0..=640 => 1200,
            641..=960 => 2200,
            961..=1280 => 3500,
            1281..=1920 => 6000,
            1921..=2560 => 9000,
            _ => 14000,
        };

        let adjusted_kbps = if fps > 30 {
            (base_kbps.saturating_mul(135).saturating_add(99)) / 100
        } else {
            base_kbps
        };

        Some(adjusted_kbps)
    }

    pub fn video_bufsize_kbps(self, width: u32, height: u32, fps: u32) -> Option<u32> {
        self.video_maxrate_kbps(width, height, fps)
            .map(|maxrate| maxrate.saturating_mul(2))
    }

    pub fn still_image_quantization_max_colors(self) -> Option<u32> {
        if self.is_compact() {
            Some(192)
        } else {
            None
        }
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
