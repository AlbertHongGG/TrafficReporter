use serde::{Deserialize, Serialize};

use super::lpr_media::{
    LprFrameSamplePayload, LprPlateCandidatePayload, LprTargetTrackPayload,
};
use super::lpr_workspace::{
    LprAnalysisProvenancePayload, LprReviewStatePayload, TimelineIntervalSelectionPayload,
};
use crate::contracts::{OutputCompressionModePayload, VideoMarkerRectPayload};

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
