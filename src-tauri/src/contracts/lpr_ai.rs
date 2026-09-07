use serde::{Deserialize, Serialize};

use super::lpr_common::{
    LprAnalysisProfileId, LprDecisionTrace, LprRuntimeStatusPayload, LprVehicleKind,
};
use super::lpr_media::{
    LprFrameSamplePayload, LprPlateCandidatePayload, LprTargetTrackPayload,
};
use super::lpr_workspace::{
    LprAnalysisProvenancePayload, LprReviewStatePayload, TimelineIntervalSelectionPayload,
};
use crate::contracts::{OutputCompressionModePayload, VideoMarkerRectPayload};

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
