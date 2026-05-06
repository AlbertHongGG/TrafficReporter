use std::sync::Mutex;

use crate::contracts::ExportSnapshotPayload;

pub struct AppState {
    pub pending_export_snapshot: Mutex<Option<ExportSnapshotPayload>>,
}
