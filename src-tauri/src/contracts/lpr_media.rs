use serde::{Deserialize, Serialize};

use super::lpr_common::{
    LprDiagnostics, LprOcrInput, LprRecognitionSource, LprRuntimeStatusPayload,
    LprSampleSelection, LprTemporalSupport, LprVehicleKind,
};
use crate::contracts::VideoMarkerRectPayload;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "kebab-case")]
pub enum LprTrackingTier {
    Full,
    Partial,
    DetectionFallback,
    AnchorOnly,
    AnchorInvalid,
}
impl_enum_as_str_and_display!(LprTrackingTier {
    Full => "full",
    Partial => "partial",
    DetectionFallback => "detection-fallback",
    AnchorOnly => "anchor-only",
    AnchorInvalid => "anchor-invalid",
});

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "kebab-case")]
pub enum LprAnchorStatus {
    Valid,
    MissingSelection,
    OutsideInterval,
    NotDetected,
    Mismatched,
    Degraded,
}
impl_enum_as_str_and_display!(LprAnchorStatus {
    Valid => "valid",
    MissingSelection => "missing-selection",
    OutsideInterval => "outside-interval",
    NotDetected => "not-detected",
    Mismatched => "mismatched",
    Degraded => "degraded",
});

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "kebab-case")]
pub enum LprLegibilityLevel {
    Perfect,
    Good,
    Poor,
    Illegible,
    Unknown,
}
impl_enum_as_str_and_display!(LprLegibilityLevel {
    Perfect => "perfect",
    Good => "good",
    Poor => "poor",
    Illegible => "illegible",
    Unknown => "unknown",
});

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
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

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprTrackedRegionPayload {
    pub id: String,
    pub time_ms: f64,
    pub r#box: VideoMarkerRectPayload,
    pub confidence: f64,
    pub class_name: String,
    #[specta(type = Option<specta_typescript::Any>)]
    pub diagnostics: Option<LprDiagnostics>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprTargetTrackPayload {
    pub id: String,
    pub class_name: String,
    pub label: String,
    pub confidence: f64,
    pub frames: Vec<LprTrackedRegionPayload>,
    #[specta(type = Option<specta_typescript::Any>)]
    pub diagnostics: Option<LprDiagnostics>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprPlateCandidatePayload {
    pub id: String,
    pub text: String,
    pub confidence: f64,
    pub source: LprRecognitionSource,
    pub frame_time_ms: Option<f64>,
    pub country_code: Option<String>,
    pub r#box: Option<VideoMarkerRectPayload>,
    pub quality: Option<LprQualityMetricsPayload>,
    #[specta(type = Option<specta_typescript::Any>)]
    pub diagnostics: Option<LprDiagnostics>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprFrameSamplePayload {
    pub id: String,
    pub time_ms: f64,
    pub target_box: Option<VideoMarkerRectPayload>,
    pub plate_box: Option<VideoMarkerRectPayload>,
    pub quality: Option<LprQualityMetricsPayload>,
    pub candidates: Vec<LprPlateCandidatePayload>,
    pub image_path: Option<String>,
    pub selection: Option<LprSampleSelection>,
    pub ocr_input: Option<LprOcrInput>,
    pub temporal_support: Option<LprTemporalSupport>,
    #[specta(type = Option<specta_typescript::Any>)]
    pub diagnostics: Option<LprDiagnostics>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprProgressPayload {
    pub progress: f64,
    pub stage: String,
    pub detail: String,
    pub done: bool,
    pub failed: bool,
    pub request_id: Option<String>,
    pub reason_code: Option<String>,
    pub tracking_tier: Option<LprTrackingTier>,
    pub coverage_ratio: Option<f64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprTrackingSummary {
    pub tracking_tier: LprTrackingTier,
    pub anchor_status: LprAnchorStatus,
    pub coverage_ratio: f64,
    pub tracked_frame_count: u32,
    pub requested_frame_count: u32,
    pub degraded_reason: Option<String>,
    pub terminated_early: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "kebab-case")]
pub enum LprSequenceTier {
    Stable,
    Drifting,
    Gapped,
    Fragmented,
}
impl_enum_as_str_and_display!(LprSequenceTier {
    Stable => "stable",
    Drifting => "drifting",
    Gapped => "gapped",
    Fragmented => "fragmented",
});

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprSequenceSummary {
    pub sequence_tier: LprSequenceTier,
    pub dominant_text: Option<String>,
    pub persistence_ratio: f64,
    pub support_frame_count: u32,
    pub sample_count: u32,
    pub support_frame_gap_count: u32,
    pub prediction_switch_count: u32,
    pub character_consistency: Vec<f64>,
    pub character_consistency_mean: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprTargetScanRequestPayload {
    pub source_path: String,
    pub time_ms: f64,
    pub marker_rect: Option<VideoMarkerRectPayload>,
    pub target_vehicle_kind: LprVehicleKind,
    pub request_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprTargetScanResponsePayload {
    pub detections: Vec<LprTrackedRegionPayload>,
    pub runtime: LprRuntimeStatusPayload,
}
