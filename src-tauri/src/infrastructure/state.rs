use std::sync::{Arc, Mutex};
use crate::domain::project::EditorWorkspaceState;
use crate::application::job_manager::JobManager;

pub struct AppState {
    pub workspace: Arc<Mutex<EditorWorkspaceState>>,
    pub job_manager: Arc<JobManager>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            workspace: Arc::new(Mutex::new(EditorWorkspaceState::default())),
            job_manager: Arc::new(JobManager::new()),
        }
    }
}

impl Default for AppState {
    fn default() -> Self {
        Self::new()
    }
}
