use serde::{Deserialize, Serialize};
use serde_json::Value;

pub type LprAnalysisProfileId = String;
pub type LprRecognitionSource = String;
pub type LprDiagnostics = Value;

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
pub struct LprRuntimeStatusPayload {
    pub available: bool,
    pub python_executable: Option<String>,
    pub runtime_script: Option<String>,
    pub version: Option<String>,
    pub missing_packages: Vec<String>,
    pub installed_packages: Vec<String>,
    pub detail: String,
}
