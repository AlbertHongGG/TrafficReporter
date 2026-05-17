// This file is auto-generated from schemas/lpr/lpr-contracts.json.
// Do not edit manually.
use serde::{Deserialize, Serialize};
use serde_json::Value;
use super::{VideoMarkerRectPayload};

pub type LprVehicleKind = String;

pub type LprLegibilityLevel = String;

pub type LprAnalysisProfileId = String;

pub type LprRecognitionSource = String;

pub type LprDiagnostics = Value;

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
    pub enable_reliability_gates: Option<bool>,
    pub min_accepted_confidence: Option<f64>,
    pub min_candidate_margin: Option<f64>,
    pub min_interval_support_frames: Option<u32>,
}

pub type LprReviewStatus = String;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprReviewStatePayload {
    pub status: LprReviewStatus,
    pub accepted_candidate_id: Option<String>,
    pub suggested_candidate_id: Option<String>,
    pub reasons: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprAnalysisProvenancePayload {
    pub request_id: Option<String>,
    pub command: String,
    pub analysis_profile_id: Option<LprAnalysisProfileId>,
    pub developer_diagnostics_enabled: bool,
    pub runtime_version: Option<String>,
    pub emitted_at_ms: u64,
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
    pub legibility_level: LprLegibilityLevel,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprTrackedRegionPayload {
    pub id: String,
    pub time_ms: u64,
    pub r#box: VideoMarkerRectPayload,
    pub confidence: f64,
    pub class_name: String,
    pub diagnostics: Option<LprDiagnostics>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprTargetTrackPayload {
    pub id: String,
    pub class_name: String,
    pub label: String,
    pub confidence: f64,
    pub frames: Vec<LprTrackedRegionPayload>,
    pub diagnostics: Option<LprDiagnostics>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprPlateCandidatePayload {
    pub id: String,
    pub text: String,
    pub confidence: f64,
    pub source: LprRecognitionSource,
    pub frame_time_ms: Option<u64>,
    pub country_code: Option<String>,
    pub r#box: Option<VideoMarkerRectPayload>,
    pub quality: Option<LprQualityMetricsPayload>,
    pub diagnostics: Option<LprDiagnostics>,
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
    pub diagnostics: Option<LprDiagnostics>,
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
    pub target_vehicle_kind: LprVehicleKind,
    pub request_id: Option<String>,
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
    pub target_vehicle_kind: LprVehicleKind,
    pub selected_target_box: Option<VideoMarkerRectPayload>,
    pub country_hints: Vec<String>,
    pub analysis_profile_id: Option<LprAnalysisProfileId>,
    pub enable_developer_diagnostics: Option<bool>,
    pub analysis_options: Option<LprAnalysisOptionsPayload>,
    pub request_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprFrameAnalysisResponsePayload {
    pub detections: Vec<LprTrackedRegionPayload>,
    pub sample: Option<LprFrameSamplePayload>,
    pub candidates: Vec<LprPlateCandidatePayload>,
    pub accepted_candidate_id: Option<String>,
    pub review: LprReviewStatePayload,
    pub provenance: LprAnalysisProvenancePayload,
    pub runtime: LprRuntimeStatusPayload,
    pub diagnostics: Option<LprDiagnostics>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprIntervalAnalysisRequestPayload {
    pub source_path: String,
    pub interval: TimelineIntervalSelectionPayload,
    pub anchor_time_ms: u64,
    pub target_vehicle_kind: LprVehicleKind,
    pub selected_target_box: Option<VideoMarkerRectPayload>,
    pub country_hints: Vec<String>,
    pub sample_every_ms: Option<u64>,
    pub max_samples: Option<u32>,
    pub analysis_profile_id: Option<LprAnalysisProfileId>,
    pub enable_developer_diagnostics: Option<bool>,
    pub analysis_options: Option<LprAnalysisOptionsPayload>,
    pub request_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprIntervalAnalysisResponsePayload {
    pub target_tracks: Vec<LprTargetTrackPayload>,
    pub samples: Vec<LprFrameSamplePayload>,
    pub candidates: Vec<LprPlateCandidatePayload>,
    pub accepted_candidate_id: Option<String>,
    pub review: LprReviewStatePayload,
    pub provenance: LprAnalysisProvenancePayload,
    pub summary: String,
    pub runtime: LprRuntimeStatusPayload,
    pub diagnostics: Option<LprDiagnostics>,
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
    pub review: Option<LprReviewStatePayload>,
    pub provenance: Option<LprAnalysisProvenancePayload>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LprEvidenceExportResponsePayload {
    pub json_path: String,
    pub image_path: String,
    pub bundle_dir: String,
    pub exported_file_count: usize,
    pub decision_frame_count: usize,
}
