use serde::{Deserialize, Serialize};

use super::lpr_common::{
    LprAnalysisProfileId, LprDecisionTrace, LprDiagnostics, LprJobStatus, LprRuntimeStatusPayload,
    LprVehicleKind,
};
use super::lpr_media::{
    LprFrameSamplePayload, LprPlateCandidatePayload, LprSequenceSummary, LprTargetTrackPayload,
    LprTrackedRegionPayload, LprTrackingSummary,
};
use crate::contracts::VideoMarkerRectPayload;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "kebab-case")]
pub enum LprWorkflowMode {
    Idle,
    Range,
    Target,
    Review,
}
impl_enum_as_str_and_display!(LprWorkflowMode {
    Idle => "idle",
    Range => "range",
    Target => "target",
    Review => "review",
});

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "kebab-case")]
pub enum LprAnalysisIntent {
    InteractiveShortRange,
    InteractiveRange,
    InteractiveDenseRange,
    AiEvidenceRange,
}
impl_enum_as_str_and_display!(LprAnalysisIntent {
    InteractiveShortRange => "interactive-short-range",
    InteractiveRange => "interactive-range",
    InteractiveDenseRange => "interactive-dense-range",
    AiEvidenceRange => "ai-evidence-range",
});

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "kebab-case")]
pub enum LprReviewStatus {
    Accepted,
    ReviewRequired,
    NoCandidate,
}
impl_enum_as_str_and_display!(LprReviewStatus {
    Accepted => "accepted",
    ReviewRequired => "review-required",
    NoCandidate => "no-candidate",
});

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprReviewStatePayload {
    pub status: LprReviewStatus,
    pub accepted_candidate_id: Option<String>,
    pub suggested_candidate_id: Option<String>,
    pub reasons: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprAnalysisProvenancePayload {
    pub request_id: Option<String>,
    pub command: String,
    pub analysis_profile_id: Option<LprAnalysisProfileId>,
    pub developer_diagnostics_enabled: bool,
    pub runtime_version: Option<String>,
    pub restoration_mode: Option<String>,
    pub recognizer_backend: Option<String>,
    pub temporal_evidence_mode: Option<String>,
    pub sequence_review_mode: Option<String>,
    pub emitted_at_ms: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct TimelineIntervalSelectionPayload {
    pub start_ms: f64,
    pub end_ms: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprAnalysisOptionsPayload {
    pub persist_artifacts: Option<bool>,
    pub artifact_dir: Option<String>,
    pub tracker_mode: Option<String>,
    pub fusion_mode: Option<String>,
    pub restoration_mode: Option<String>,
    pub recognizer_backend: Option<String>,
    pub temporal_evidence_mode: Option<String>,
    pub sequence_review_mode: Option<String>,
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
    pub min_sequence_persistence: Option<f64>,
    pub max_sequence_gap_count: Option<u32>,
    pub temporal_window_ms: Option<f64>,
    pub temporal_neighbor_count: Option<u32>,
    pub max_evidence_sample_count: Option<u32>,
    pub anchor_burst_count: Option<u32>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprFrameAnalysisRequestPayload {
    pub source_path: String,
    pub time_ms: f64,
    pub marker_rect: Option<VideoMarkerRectPayload>,
    pub target_vehicle_kind: LprVehicleKind,
    pub selected_target_box: Option<VideoMarkerRectPayload>,
    pub country_hints: Vec<String>,
    pub analysis_profile_id: Option<LprAnalysisProfileId>,
    pub enable_developer_diagnostics: Option<bool>,
    pub analysis_options: Option<LprAnalysisOptionsPayload>,
    pub request_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprFrameAnalysisResponsePayload {
    pub detections: Vec<LprTrackedRegionPayload>,
    pub sample: Option<LprFrameSamplePayload>,
    pub candidates: Vec<LprPlateCandidatePayload>,
    pub accepted_candidate_id: Option<String>,
    pub review: LprReviewStatePayload,
    pub provenance: LprAnalysisProvenancePayload,
    pub decision: Option<LprDecisionTrace>,
    pub runtime: LprRuntimeStatusPayload,
    pub job_status: Option<LprJobStatus>,
    #[specta(type = Option<specta_typescript::Any>)]
    pub diagnostics: Option<LprDiagnostics>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprIntervalAnalysisRequestPayload {
    pub source_path: String,
    pub interval: TimelineIntervalSelectionPayload,
    pub anchor_time_ms: f64,
    pub target_vehicle_kind: LprVehicleKind,
    pub selected_target_box: Option<VideoMarkerRectPayload>,
    pub selected_target_track_id: Option<String>,
    pub country_hints: Vec<String>,
    pub sample_every_ms: Option<f64>,
    pub max_samples: Option<u32>,
    pub analysis_intent: Option<LprAnalysisIntent>,
    pub latency_budget_ms: Option<f64>,
    pub analysis_profile_id: Option<LprAnalysisProfileId>,
    pub enable_developer_diagnostics: Option<bool>,
    pub analysis_options: Option<LprAnalysisOptionsPayload>,
    pub request_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprIntervalAnalysisResponsePayload {
    pub target_tracks: Vec<LprTargetTrackPayload>,
    pub analysis_track: Option<LprTargetTrackPayload>,
    pub samples: Vec<LprFrameSamplePayload>,
    pub candidates: Vec<LprPlateCandidatePayload>,
    pub accepted_candidate_id: Option<String>,
    pub review: LprReviewStatePayload,
    pub provenance: LprAnalysisProvenancePayload,
    pub decision: Option<LprDecisionTrace>,
    pub summary: String,
    pub runtime: LprRuntimeStatusPayload,
    pub job_status: Option<LprJobStatus>,
    pub tracking: Option<LprTrackingSummary>,
    pub sequence: Option<LprSequenceSummary>,
    #[specta(type = Option<specta_typescript::Any>)]
    pub diagnostics: Option<LprDiagnostics>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprAnalysisProfileDefinition {
    pub id: LprAnalysisProfileId,
    pub label: String,
    pub description: String,
    pub options: LprAnalysisOptionsPayload,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprAnalysisProfileCatalog {
    pub version: u32,
    pub default_profile_id: LprAnalysisProfileId,
    pub developer_diagnostics_options: Option<LprAnalysisOptionsPayload>,
    pub profiles: Vec<LprAnalysisProfileDefinition>,
}
