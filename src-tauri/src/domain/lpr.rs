use std::collections::BTreeMap;
use serde::{Deserialize, Serialize};

use crate::contracts::LprRuntimeStatusPayload;

#[derive(Debug, Clone, Serialize, Deserialize, Default, specta::Type)]
#[serde(rename_all = "camelCase")]
pub struct EditorAnalysisState {
    pub lpr_runtime_status: Option<LprRuntimeStatusPayload>,
    #[specta(type = std::collections::BTreeMap<String, specta_typescript::Any>)]
    pub lpr_sessions_by_file_id: BTreeMap<String, serde_json::Value>,
    #[specta(type = std::collections::BTreeMap<String, specta_typescript::Any>)]
    pub ai_evidence_sessions_by_file_id: BTreeMap<String, serde_json::Value>,
}
