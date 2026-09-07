use std::sync::{
    atomic::{AtomicU64, Ordering},
    Mutex, OnceLock,
};

use serde::de::DeserializeOwned;
use serde::Serialize;

use crate::contracts::LprProgressPayload;
use crate::editor::{emit_app_log, emit_lpr_progress};

use super::process_lifecycle::{kill_process_tree, PersistentLprRuntime};
use super::protocol::{cancel_generation_changed, RuntimeWorkerInvokeError};

pub(crate) const LPR_RUNTIME_RETRY_LIMIT: usize = 1;

static RUNTIME_BROKER: OnceLock<RuntimeBroker> = OnceLock::new();

pub(crate) struct RuntimeBroker {
    worker: Mutex<Option<PersistentLprRuntime>>,
    worker_pid: Mutex<Option<u32>>,
    cancel_generation: AtomicU64,
}

impl RuntimeBroker {
    fn new() -> Self {
        Self {
            worker: Mutex::new(None),
            worker_pid: Mutex::new(None),
            cancel_generation: AtomicU64::new(0),
        }
    }

    fn cancel_generation(&self) -> u64 {
        self.cancel_generation.load(Ordering::SeqCst)
    }

    pub(crate) fn set_worker_pid(&self, pid: Option<u32>) {
        if let Ok(mut guard) = self.worker_pid.lock() {
            *guard = pid;
        }
    }

    fn active_worker_pid(&self) -> Result<Option<u32>, String> {
        self.worker_pid
            .lock()
            .map(|guard| *guard)
            .map_err(|_| "Failed to lock the local LPR runtime worker pid slot.".to_string())
    }

    fn invoke<TRequest, TResponse>(
        &self,
        app_handle: tauri::AppHandle,
        subcommand: &str,
        payload: &TRequest,
    ) -> Result<TResponse, String>
    where
        TRequest: Serialize,
        TResponse: DeserializeOwned,
    {
        self.invoke_with_progress::<TRequest, TResponse, LprProgressPayload, _>(
            app_handle,
            subcommand,
            payload,
            |app_handle, progress| {
                emit_lpr_progress(
                    app_handle,
                    progress.request_id.as_deref(),
                    progress.progress,
                    &progress.stage,
                    progress.detail,
                    progress.done,
                    progress.failed,
                    progress.reason_code.as_deref(),
                    progress.tracking_tier,
                    progress.coverage_ratio,
                );
            },
        )
    }

    fn invoke_with_progress<TRequest, TResponse, TProgress, F>(
        &self,
        app_handle: tauri::AppHandle,
        subcommand: &str,
        payload: &TRequest,
        mut on_progress: F,
    ) -> Result<TResponse, String>
    where
        TRequest: Serialize,
        TResponse: DeserializeOwned,
        TProgress: DeserializeOwned,
        F: FnMut(&tauri::AppHandle, TProgress),
    {
        let mut worker_guard = self
            .worker
            .lock()
            .map_err(|_| "Failed to lock the local LPR runtime worker slot.".to_string())?;
        let mut attempt = 0usize;
        let invoke_cancel_generation = self.cancel_generation();

        loop {
            let needs_restart = worker_guard
                .as_mut()
                .map(|worker| !worker.is_alive())
                .unwrap_or(true);
            if needs_restart {
                self.set_worker_pid(None);
                *worker_guard = Some(PersistentLprRuntime::start(app_handle.clone())?);
            }

            let worker = worker_guard
                .as_mut()
                .ok_or_else(|| "The local LPR runtime worker could not be initialized.".to_string())?;

            match worker.invoke(&app_handle, subcommand, payload, &mut on_progress) {
                Ok(response) => return Ok(response),
                Err(RuntimeWorkerInvokeError::Unrecoverable(error)) => return Err(error),
                Err(RuntimeWorkerInvokeError::Recoverable(error)) => {
                    self.set_worker_pid(None);
                    *worker_guard = None;
                    if cancel_generation_changed(invoke_cancel_generation, self.cancel_generation()) {
                        emit_app_log(
                            &app_handle,
                            "info",
                            "LprRuntimeWorker",
                            format!("Worker request cancelled without retry: {}", error),
                        );
                        return Err("The local LPR runtime request was cancelled.".to_string());
                    }
                    emit_app_log(
                        &app_handle,
                        "warn",
                        "LprRuntimeWorker",
                        format!("Worker request failed and will be restarted: {}", error),
                    );
                    if attempt >= LPR_RUNTIME_RETRY_LIMIT {
                        return Err(error);
                    }
                    attempt += 1;
                }
            }
        }
    }

    fn terminate(&self, app_handle: &tauri::AppHandle, reason: &str) -> Result<bool, String> {
        let Some(pid) = self.active_worker_pid()? else {
            emit_app_log(
                app_handle,
                "debug",
                "LprRuntimeWorker",
                format!("Cancellation skipped: no active worker. reason={}", reason),
            );
            return Ok(false);
        };

        emit_app_log(
            app_handle,
            "warn",
            "LprRuntimeWorker",
            format!("Terminating persistent Python runtime worker pid={} reason={}", pid, reason),
        );
        if let Ok(mut guard) = self.worker.try_lock() {
            if let Some(worker) = guard.as_mut() {
                worker.terminate()?;
            } else {
                // Fall back to OS-level termination when the worker slot is empty
                // but a pid is still recorded (e.g. after a timed-out read).
                kill_process_tree(pid)?;
            }
            *guard = None;
        } else {
            kill_process_tree(pid)?;
        }
        self.cancel_generation.fetch_add(1, Ordering::SeqCst);
        self.set_worker_pid(None);
        Ok(true)
    }
}

pub(crate) fn runtime_broker() -> &'static RuntimeBroker {
    RUNTIME_BROKER.get_or_init(RuntimeBroker::new)
}

pub(crate) fn invoke_lpr_runtime<TRequest, TResponse>(
    app_handle: tauri::AppHandle,
    subcommand: &str,
    payload: &TRequest,
) -> Result<TResponse, String>
where
    TRequest: Serialize,
    TResponse: DeserializeOwned,
{
    runtime_broker().invoke(app_handle, subcommand, payload)
}

pub(crate) fn invoke_lpr_runtime_with_progress<TRequest, TResponse, TProgress, F>(
    app_handle: tauri::AppHandle,
    subcommand: &str,
    payload: &TRequest,
    on_progress: F,
) -> Result<TResponse, String>
where
    TRequest: Serialize,
    TResponse: DeserializeOwned,
    TProgress: DeserializeOwned,
    F: FnMut(&tauri::AppHandle, TProgress),
{
    runtime_broker().invoke_with_progress(app_handle, subcommand, payload, on_progress)
}

pub(crate) fn terminate_lpr_runtime_process(
    app_handle: &tauri::AppHandle,
    reason: &str,
) -> Result<bool, String> {
    runtime_broker().terminate(app_handle, reason)
}
