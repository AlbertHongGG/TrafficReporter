use std::collections::BTreeMap;
use serde::{Deserialize, Serialize};

use crate::contracts::LprRuntimeStatusPayload;

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct EditorAnalysisState {
    pub lpr_runtime_status: Option<LprRuntimeStatusPayload>,
    pub lpr_sessions_by_file_id: BTreeMap<String, serde_json::Value>,
    pub ai_evidence_sessions_by_file_id: BTreeMap<String, serde_json::Value>,
}
