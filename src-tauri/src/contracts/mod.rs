use serde::{Deserialize, Serialize};
use serde_json::Value;

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

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RenderProfilePayload {
    pub format: String,
    pub fps: u32,
    pub video_quality: Option<String>,
    pub audio_bitrate_kbps: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct VideoMarkerRectPayload {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TimelineIntervalSelectionPayload {
    pub start_ms: u64,
    pub end_ms: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprQualityMetricsPayload {
    pub sharpness: f64,
    pub contrast: f64,
    pub plate_area: f64,
    pub angle_score: f64,
    pub occlusion_score: f64,
    pub glare_score: f64,
    pub legibility_score: f64,
    pub overall_score: f64,
    pub legibility_level: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprTrackedRegionPayload {
    pub id: String,
    pub time_ms: u64,
    pub r#box: VideoMarkerRectPayload,
    pub confidence: f64,
    pub class_name: String,
    pub diagnostics: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprTargetTrackPayload {
    pub id: String,
    pub class_name: String,
    pub label: String,
    pub confidence: f64,
    pub frames: Vec<LprTrackedRegionPayload>,
    pub diagnostics: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprPlateCandidatePayload {
    pub id: String,
    pub text: String,
    pub confidence: f64,
    pub source: String,
    pub frame_time_ms: Option<u64>,
    pub country_code: Option<String>,
    pub r#box: Option<VideoMarkerRectPayload>,
    pub quality: Option<LprQualityMetricsPayload>,
    pub diagnostics: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprFrameSamplePayload {
    pub id: String,
    pub time_ms: u64,
    pub target_box: Option<VideoMarkerRectPayload>,
    pub plate_box: Option<VideoMarkerRectPayload>,
    pub quality: Option<LprQualityMetricsPayload>,
    pub candidates: Vec<LprPlateCandidatePayload>,
    pub image_path: Option<String>,
    pub diagnostics: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprAnalysisOptionsPayload {
    pub persist_artifacts: Option<bool>,
    pub artifact_dir: Option<String>,
    pub tracker_mode: Option<String>,
    pub fusion_mode: Option<String>,
    pub restoration_mode: Option<String>,
    pub enable_rectification: Option<bool>,
    pub enable_enhancement: Option<bool>,
    pub enable_recognizer_comparison: Option<bool>,
    pub debug_tag: Option<String>,
    pub ocr_model_names: Option<Vec<String>>,
    pub max_plate_candidates: Option<u32>,
    pub tracker_high_confidence: Option<f64>,
    pub tracker_low_confidence: Option<f64>,
    pub max_tracking_gap: Option<u32>,
    pub min_alignment_score: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprRuntimeStatusPayload {
    pub available: bool,
    pub python_executable: Option<String>,
    pub runtime_script: Option<String>,
    pub version: Option<String>,
    pub missing_packages: Vec<String>,
    pub installed_packages: Vec<String>,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprTargetScanRequestPayload {
    pub source_path: String,
    pub time_ms: u64,
    pub marker_rect: Option<VideoMarkerRectPayload>,
    pub target_vehicle_kind: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprTargetScanResponsePayload {
    pub detections: Vec<LprTrackedRegionPayload>,
    pub runtime: LprRuntimeStatusPayload,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprFrameAnalysisRequestPayload {
    pub source_path: String,
    pub time_ms: u64,
    pub marker_rect: Option<VideoMarkerRectPayload>,
    pub target_vehicle_kind: String,
    pub selected_target_box: Option<VideoMarkerRectPayload>,
    pub country_hints: Vec<String>,
    pub analysis_options: Option<LprAnalysisOptionsPayload>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprFrameAnalysisResponsePayload {
    pub detections: Vec<LprTrackedRegionPayload>,
    pub sample: Option<LprFrameSamplePayload>,
    pub candidates: Vec<LprPlateCandidatePayload>,
    pub runtime: LprRuntimeStatusPayload,
    pub diagnostics: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprIntervalAnalysisRequestPayload {
    pub source_path: String,
    pub interval: TimelineIntervalSelectionPayload,
    pub anchor_time_ms: u64,
    pub target_vehicle_kind: String,
    pub selected_target_box: Option<VideoMarkerRectPayload>,
    pub country_hints: Vec<String>,
    pub sample_every_ms: Option<u64>,
    pub max_samples: Option<u32>,
    pub analysis_options: Option<LprAnalysisOptionsPayload>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprIntervalAnalysisResponsePayload {
    pub target_tracks: Vec<LprTargetTrackPayload>,
    pub samples: Vec<LprFrameSamplePayload>,
    pub candidates: Vec<LprPlateCandidatePayload>,
    pub accepted_candidate_id: Option<String>,
    pub summary: String,
    pub runtime: LprRuntimeStatusPayload,
    pub diagnostics: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprEvidenceExportRequestPayload {
    pub output_path: String,
    pub source_path: String,
    pub time_ms: u64,
    pub marker_rect: Option<VideoMarkerRectPayload>,
    pub interval: Option<TimelineIntervalSelectionPayload>,
    pub target_track: Option<LprTargetTrackPayload>,
    pub accepted_candidate: Option<LprPlateCandidatePayload>,
    pub candidates: Vec<LprPlateCandidatePayload>,
    pub samples: Vec<LprFrameSamplePayload>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprEvidenceExportResponsePayload {
    pub json_path: String,
    pub image_path: String,
}

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
