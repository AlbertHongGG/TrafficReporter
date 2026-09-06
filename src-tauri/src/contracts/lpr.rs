use serde::{Deserialize, Serialize};
use serde_json::Value;
use super::{OutputCompressionModePayload, VideoMarkerRectPayload};

macro_rules! impl_enum_as_str_and_display {
    ($enum_type:ident { $($variant:ident => $str_val:literal),+ $(,)? }) => {
        impl $enum_type {
            pub fn as_str(&self) -> &'static str {
                match self {
                    $(Self::$variant => $str_val,)+
                }
            }

            pub fn from_str_opt(s: &str) -> Option<Self> {
                match s {
                    $($str_val => Some(Self::$variant),)+
                    _ => None,
                }
            }
        }
        impl std::fmt::Display for $enum_type {
            fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                write!(f, "{}", self.as_str())
            }
        }
    };
}

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
pub enum LprJobStatus {
    Idle,
    Queued,
    Running,
    Completed,
    Failed,
    Cancelled,
    Degraded,
}
impl_enum_as_str_and_display!(LprJobStatus {
    Idle => "idle",
    Queued => "queued",
    Running => "running",
    Completed => "completed",
    Failed => "failed",
    Cancelled => "cancelled",
    Degraded => "degraded",
});

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
pub enum LprVehicleKind {
    Any,
    Vehicle,
    Motorcycle,
    Car,
    Truck,
    Bus,
}
impl_enum_as_str_and_display!(LprVehicleKind {
    Any => "any",
    Vehicle => "vehicle",
    Motorcycle => "motorcycle",
    Car => "car",
    Truck => "truck",
    Bus => "bus",
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

pub type LprAnalysisProfileId = String;

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

pub type LprRecognitionSource = String;
pub type LprDiagnostics = Value;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "kebab-case")]
pub enum LprArtifactStage {
    Raw,
    Original,
    Rectified,
    Enhanced,
    Restored,
    TemporalRestored,
    Fused,
}
impl_enum_as_str_and_display!(LprArtifactStage {
    Raw => "raw",
    Original => "original",
    Rectified => "rectified",
    Enhanced => "enhanced",
    Restored => "restored",
    TemporalRestored => "temporal-restored",
    Fused => "fused",
});

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "kebab-case")]
pub enum LprEvidenceReason {
    Anchor,
    AnchorFrame,
    IntervalStart,
    IntervalEnd,
    ScheduledSample,
    TemporalBurst,
    MotionHotspot,
    HighConfidence,
    HighestConfidence,
    HighestResolution,
    Representative,
    TemporalSupport,
    SharpnessPeak,
}
impl_enum_as_str_and_display!(LprEvidenceReason {
    Anchor => "anchor",
    AnchorFrame => "anchor-frame",
    IntervalStart => "interval-start",
    IntervalEnd => "interval-end",
    ScheduledSample => "scheduled-sample",
    TemporalBurst => "temporal-burst",
    MotionHotspot => "motion-hotspot",
    HighConfidence => "high-confidence",
    HighestConfidence => "highest-confidence",
    HighestResolution => "highest-resolution",
    Representative => "representative",
    TemporalSupport => "temporal-support",
    SharpnessPeak => "sharpness-peak",
});

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "kebab-case")]
pub enum LprDecisionSource {
    SingleFrame,
    TemporalFusion,
    CrossFrameVote,
    UserSelected,
    FusedImage,
    FusedChar,
    TemporalRestored,
    SupportCarry,
    LegacyVote,
}
impl_enum_as_str_and_display!(LprDecisionSource {
    SingleFrame => "single-frame",
    TemporalFusion => "temporal-fusion",
    CrossFrameVote => "cross-frame-vote",
    UserSelected => "user-selected",
    FusedImage => "fused-image",
    FusedChar => "fused-char",
    TemporalRestored => "temporal-restored",
    SupportCarry => "support-carry",
    LegacyVote => "legacy-vote",
});

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprSampleSelection {
    pub selected: bool,
    pub priority: f64,
    pub reasons: Vec<LprEvidenceReason>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprTemporalSupport {
    pub strategy: String,
    pub reference_time_ms: f64,
    pub support_frame_count: u32,
    pub support_window_ms: f64,
    pub support_times: Vec<f64>,
    pub mean_alignment_score: f64,
    pub mean_quality_score: f64,
    pub source_stage: LprArtifactStage,
    pub selected_stage: LprArtifactStage,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprOcrInput {
    pub stage: LprArtifactStage,
    pub variant: String,
    pub source: LprDecisionSource,
    pub image_path: Option<String>,
    pub support_frame_count: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprDecisionTrace {
    pub source: LprDecisionSource,
    pub candidate_id: Option<String>,
    pub sample_id: Option<String>,
    pub frame_time_ms: Option<f64>,
    pub stage: Option<LprArtifactStage>,
    pub support_frame_count: u32,
    pub agreement_ratio: Option<f64>,
    pub margin: Option<f64>,
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
pub struct LprRuntimeStatusPayload {
    pub available: bool,
    pub python_executable: Option<String>,
    pub runtime_script: Option<String>,
    pub version: Option<String>,
    pub missing_packages: Vec<String>,
    pub installed_packages: Vec<String>,
    pub detail: String,
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
pub struct LprEvidenceExportRequestPayload {
    pub output_path: String,
    pub source_path: String,
    pub time_ms: f64,
    pub marker_rect: Option<VideoMarkerRectPayload>,
    pub compression_mode: OutputCompressionModePayload,
    pub interval: Option<TimelineIntervalSelectionPayload>,
    pub target_track: Option<LprTargetTrackPayload>,
    pub accepted_candidate: Option<LprPlateCandidatePayload>,
    pub candidates: Vec<LprPlateCandidatePayload>,
    pub samples: Vec<LprFrameSamplePayload>,
    pub review: Option<LprReviewStatePayload>,
    pub provenance: Option<LprAnalysisProvenancePayload>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct LprEvidenceExportResponsePayload {
    pub json_path: String,
    pub image_path: String,
    pub bundle_dir: String,
    pub exported_file_count: u32,
    pub decision_frame_count: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "kebab-case")]
pub enum AiEvidenceProviderKind {
    Mock,
    Gemini,
    Local,
}
impl_enum_as_str_and_display!(AiEvidenceProviderKind {
    Mock => "mock",
    Gemini => "gemini",
    Local => "local",
});

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "kebab-case")]
pub enum AiEvidenceProgressKind {
    HostStep,
    ToolCall,
}
impl_enum_as_str_and_display!(AiEvidenceProgressKind {
    HostStep => "host-step",
    ToolCall => "tool-call",
});

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct AiEvidenceProgressPayload {
    pub progress: f64,
    pub stage: String,
    pub detail: String,
    pub progress_kind: Option<AiEvidenceProgressKind>,
    pub tool_name: Option<String>,
    pub tool_label: Option<String>,
    pub step_index: Option<u32>,
    pub step_count: Option<u32>,
    pub stage_step_index: Option<u32>,
    pub stage_step_count: Option<u32>,
    pub done: bool,
    pub failed: bool,
    pub request_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct AiEvidencePixelBoxPayload {
    pub x: u32,
    pub y: u32,
    pub width: u32,
    pub height: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct AiEvidenceOverlayBoxPayload {
    pub normalized_box: Option<VideoMarkerRectPayload>,
    pub pixel_box: Option<AiEvidencePixelBoxPayload>,
    pub frame_width: u32,
    pub frame_height: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct AiEvidenceTimelineFrameRefPayload {
    pub frame_id: String,
    pub time_ms: f64,
    pub sequence_index: u32,
    pub label: String,
    pub image_path: Option<String>,
    pub frame_width: u32,
    pub frame_height: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct AiEvidenceToolCallPayload {
    pub stage: String,
    pub tool_name: String,
    pub input_summary: String,
    pub output_summary: String,
    pub started_at_ms: f64,
    pub completed_at_ms: f64,
    pub success: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct AiEvidenceTargetSelectionPayload {
    pub anchor_frame_id: String,
    pub selected_track_id: Option<String>,
    pub selected_candidate_id: Option<String>,
    pub confidence: f64,
    pub rationale: String,
    pub selected_box: Option<AiEvidenceOverlayBoxPayload>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct AiEvidenceKeyframePayload {
    pub frame: AiEvidenceTimelineFrameRefPayload,
    pub description: String,
    pub overlay: Option<AiEvidenceOverlayBoxPayload>,
    pub selected_for_target_resolution: Option<bool>,
    pub keyframe_source: Option<String>,
    pub description_source: Option<String>,
    pub box_source: Option<String>,
    pub is_valid_for_user_facing_output: Option<bool>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct AiEvidenceSharedProjectionPayload {
    pub interval: Option<TimelineIntervalSelectionPayload>,
    pub target_tracks: Vec<LprTargetTrackPayload>,
    pub analysis_track: Option<LprTargetTrackPayload>,
    pub selected_target_track_id: Option<String>,
    pub samples: Vec<LprFrameSamplePayload>,
    pub candidates: Vec<LprPlateCandidatePayload>,
    pub accepted_candidate_id: Option<String>,
    pub review: Option<LprReviewStatePayload>,
    pub provenance: Option<LprAnalysisProvenancePayload>,
    pub decision: Option<LprDecisionTrace>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct AiEvidenceResponsePayload {
    pub request_id: Option<String>,
    pub description: String,
    pub summary: String,
    pub provider: AiEvidenceProviderKind,
    pub interval: Option<TimelineIntervalSelectionPayload>,
    pub plate_number: Option<String>,
    pub plate_candidate: Option<LprPlateCandidatePayload>,
    pub primary_anchor: Option<AiEvidenceTimelineFrameRefPayload>,
    pub target_selection: Option<AiEvidenceTargetSelectionPayload>,
    pub keyframes: Vec<AiEvidenceKeyframePayload>,
    pub keyframe_count_reason: Option<String>,
    pub tool_calls: Vec<AiEvidenceToolCallPayload>,
    pub projection: AiEvidenceSharedProjectionPayload,
    pub clip_path: Option<String>,
    pub runtime: LprRuntimeStatusPayload,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct AiEvidenceRequestPayload {
    pub source_path: String,
    pub description: String,
    pub marker_rect: Option<VideoMarkerRectPayload>,
    pub compression_mode: OutputCompressionModePayload,
    pub audio_bitrate_kbps: Option<u32>,
    pub target_vehicle_kind: LprVehicleKind,
    pub country_hints: Vec<String>,
    pub analysis_profile_id: Option<LprAnalysisProfileId>,
    pub enable_developer_diagnostics: Option<bool>,
    pub coarse_sample_every_ms: Option<f64>,
    pub fine_sample_every_ms: Option<f64>,
    pub fine_window_padding_ms: Option<f64>,
    pub max_keyframes: Option<u32>,
    pub request_id: Option<String>,
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
