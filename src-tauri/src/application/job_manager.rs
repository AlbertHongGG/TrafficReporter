use std::sync::{Arc, Mutex};
use std::sync::atomic::{AtomicBool, Ordering};
use crate::domain::job::{Job, JobStatus};

pub struct JobManager {
    current_job: Mutex<Option<Job>>,
    cancel_token: Arc<AtomicBool>,
}

#[allow(dead_code)]
impl JobManager {
    pub fn new() -> Self {
        Self {
            current_job: Mutex::new(None),
            cancel_token: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn is_running(&self) -> bool {
        if let Some(job) = self.current_job.lock().unwrap().as_ref() {
            job.status == JobStatus::Pending || job.status == JobStatus::Running
        } else {
            false
        }
    }

    pub fn start_new_job(&self, id: String) -> Result<String, String> {
        let mut job_lock = self.current_job.lock().map_err(|e| e.to_string())?;
        self.cancel_token.store(false, Ordering::SeqCst);
        let new_job = Job::new(id.clone());
        *job_lock = Some(new_job);
        Ok(id)
    }

    pub fn update_progress(&self, progress: f64, detail: &str) {
        if let Some(job) = self.current_job.lock().unwrap().as_mut() {
            if job.status == JobStatus::Cancelled {
                return;
            }
            job.status = JobStatus::Running;
            job.progress = progress;
            job.detail = detail.to_string();
        }
    }

    pub fn complete_job(&self) {
        if let Some(job) = self.current_job.lock().unwrap().as_mut() {
            if job.status == JobStatus::Cancelled {
                return;
            }
            job.status = JobStatus::Completed;
            job.progress = 100.0;
        }
    }

    pub fn fail_job(&self, error_message: String) {
        if let Some(job) = self.current_job.lock().unwrap().as_mut() {
            if job.status == JobStatus::Cancelled {
                return;
            }
            job.status = JobStatus::Error;
            job.error_message = Some(error_message);
        }
    }

    pub fn cancel_job(&self) {
        self.cancel_token.store(true, Ordering::SeqCst);
        if let Some(job) = self.current_job.lock().unwrap().as_mut() {
            job.status = JobStatus::Cancelled;
        }
    }

    pub fn is_cancelled(&self) -> bool {
        self.cancel_token.load(Ordering::SeqCst)
    }
}

impl Default for JobManager {
    fn default() -> Self {
        Self::new()
    }
}
