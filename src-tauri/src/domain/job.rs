use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum JobStatus {
    Pending,
    Running,
    Completed,
    Error,
    Cancelled,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Job {
    pub id: String,
    pub status: JobStatus,
    pub progress: f64,
    pub detail: String,
    pub error_message: Option<String>,
}

#[allow(dead_code)]
impl Job {
    pub fn new(id: String) -> Self {
        Self {
            id,
            status: JobStatus::Pending,
            progress: 0.0,
            detail: "".to_string(),
            error_message: None,
        }
    }
}
