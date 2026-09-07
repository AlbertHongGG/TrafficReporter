use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, ChildStdout, Stdio};
use std::time::Duration;

use serde::de::DeserializeOwned;
use serde::Serialize;

use crate::editor::emit_app_log;
use crate::platform::process::{find_lpr_runtime_root, find_python_runtime, hidden_command};

use super::protocol::{
    deserialize_progress_payload, format_worker_error, parse_worker_response_line,
    request_timeout_for_subcommand, RuntimeWorkerEnvelope, RuntimeWorkerInvokeError,
    RuntimeWorkerRequest, LPR_RUNTIME_PROTOCOL_VERSION,
};
use super::status::runtime_broker;

pub(crate) struct PersistentLprRuntime {
    child: Child,
    stdin: ChildStdin,
    stdout: Option<BufReader<ChildStdout>>,
    next_request_id: u64,
}

impl PersistentLprRuntime {
    pub(crate) fn start(app_handle: tauri::AppHandle) -> Result<Self, String> {
        let python = find_python_runtime()?;
        let runtime_root = find_lpr_runtime_root()?;
        emit_app_log(&app_handle, "info", "LprRuntimeWorker", "Starting persistent Python runtime worker.");
        let mut command = hidden_command(&python.program);
        for arg in &python.args {
            command.arg(arg);
        }

        let mut child = command
            .current_dir(&runtime_root)
            .arg("-m")
            .arg("traffic_lpr_runtime")
            .arg("serve")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| format!("Failed to start the local LPR runtime worker: {}", error))?;
        let child_pid = child.id();

        if let Some(stderr) = child.stderr.take() {
            let stderr_app_handle = app_handle.clone();
            std::thread::spawn(move || {
                let mut reader = BufReader::new(stderr);
                let mut line = String::new();
                loop {
                    line.clear();
                    match reader.read_line(&mut line) {
                        Ok(0) => break,
                        Ok(_) => {
                            let message = line.trim();
                            if !message.is_empty() {
                                emit_app_log(&stderr_app_handle, "warn", "LprRuntimeWorker", message.to_string());
                            }
                        }
                        Err(error) => {
                            emit_app_log(
                                &stderr_app_handle,
                                "warn",
                                "LprRuntimeWorker",
                                format!("Failed to read LPR runtime worker stderr: {}", error),
                            );
                            break;
                        }
                    }
                }
            });
        }

        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| "Failed to open stdin for the local LPR runtime worker.".to_string())?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "Failed to open stdout for the local LPR runtime worker.".to_string())?;

        runtime_broker().set_worker_pid(Some(child_pid));

        Ok(Self {
            child,
            stdin,
            stdout: Some(BufReader::new(stdout)),
            next_request_id: 1,
        })
    }

    pub(crate) fn terminate(&mut self) -> Result<(), String> {
        if !matches!(self.child.try_wait(), Ok(None)) {
            return Ok(());
        }

        let child_pid = self.child.id();
        kill_process_tree(child_pid)?;
        let _ = self.child.wait();
        Ok(())
    }

    pub(crate) fn is_alive(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(None))
    }

    pub(crate) fn invoke<TRequest, TResponse, TProgress, F>(
        &mut self,
        app_handle: &tauri::AppHandle,
        subcommand: &str,
        payload: &TRequest,
        on_progress: &mut F,
    ) -> Result<TResponse, RuntimeWorkerInvokeError>
    where
        TRequest: Serialize,
        TResponse: DeserializeOwned,
        TProgress: DeserializeOwned,
        F: FnMut(&tauri::AppHandle, TProgress),
    {
        let request = RuntimeWorkerRequest {
            protocol_version: LPR_RUNTIME_PROTOCOL_VERSION,
            request_id: self.next_request_id,
            subcommand,
            payload,
        };
        self.next_request_id += 1;

        let serialized_request = serde_json::to_vec(&request).map_err(|error| {
            RuntimeWorkerInvokeError::Unrecoverable(format!(
                "Failed to serialize LPR runtime worker request: {}",
                error
            ))
        })?;

        self.stdin.write_all(&serialized_request).map_err(|error| {
            RuntimeWorkerInvokeError::Recoverable(format!(
                "Failed to write to the local LPR runtime worker: {}",
                error
            ))
        })?;
        self.stdin.write_all(b"\n").map_err(|error| {
            RuntimeWorkerInvokeError::Recoverable(format!(
                "Failed to finalize the LPR runtime worker request: {}",
                error
            ))
        })?;
        self.stdin.flush().map_err(|error| {
            RuntimeWorkerInvokeError::Recoverable(format!(
                "Failed to flush the LPR runtime worker request: {}",
                error
            ))
        })?;

        loop {
            let response_line = self.read_response_line(subcommand)?;
            match parse_worker_response_line(&response_line, request.request_id, request.protocol_version)? {
                RuntimeWorkerEnvelope::Progress(progress) => {
                    on_progress(app_handle, deserialize_progress_payload(progress)?);
                    continue;
                }
                RuntimeWorkerEnvelope::Success(result) => return Ok(result),
                RuntimeWorkerEnvelope::Error(response) => {
                    return Err(RuntimeWorkerInvokeError::Unrecoverable(format_worker_error(response)));
                }
            }
        }
    }

    fn read_response_line(&mut self, subcommand: &str) -> Result<String, RuntimeWorkerInvokeError> {
        let stdout = self.stdout.take().ok_or_else(|| {
            RuntimeWorkerInvokeError::Recoverable(
                "The local LPR runtime worker response stream is not available.".to_string(),
            )
        })?;
        let request_timeout = request_timeout_for_subcommand(subcommand);

        let (sender, receiver) = std::sync::mpsc::sync_channel(1);
        std::thread::spawn(move || {
            let mut stdout = stdout;
            let mut response_line = String::new();
            let result = stdout.read_line(&mut response_line).map(|bytes_read| (bytes_read, response_line));
            let _ = sender.send((stdout, result));
        });

        match receiver.recv_timeout(request_timeout) {
            Ok((stdout, result)) => {
                self.stdout = Some(stdout);
                let (bytes_read, response_line) = result.map_err(|error| {
                    RuntimeWorkerInvokeError::Recoverable(format!(
                        "Failed to read the LPR runtime worker response: {}",
                        error
                    ))
                })?;
                if bytes_read == 0 {
                    return Err(RuntimeWorkerInvokeError::Recoverable(
                        "The local LPR runtime worker exited unexpectedly.".to_string(),
                    ));
                }
                Ok(response_line)
            }
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                let child_pid = self.child.id();
                let _ = kill_process_tree(child_pid);
                let _ = self.child.wait();
                if let Ok((stdout, _)) = receiver.recv_timeout(Duration::from_secs(2)) {
                    self.stdout = Some(stdout);
                }
                Err(RuntimeWorkerInvokeError::Recoverable(format!(
                    "Timed out waiting for the local LPR runtime worker response after {} ms.",
                    request_timeout.as_millis()
                )))
            }
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => Err(RuntimeWorkerInvokeError::Recoverable(
                "The local LPR runtime worker response reader disconnected unexpectedly.".to_string(),
            )),
        }
    }
}

impl Drop for PersistentLprRuntime {
    fn drop(&mut self) {
        if !matches!(self.child.try_wait(), Ok(None)) {
            return;
        }

        let child_pid = self.child.id();
        let _ = kill_process_tree(child_pid);
        let _ = self.child.wait();
    }
}

#[cfg(target_os = "windows")]
pub(crate) fn kill_process_tree(pid: u32) -> Result<(), String> {
    let output = hidden_command("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .output()
        .map_err(|error| format!("Failed to execute taskkill for pid {}: {}", pid, error))?;

    if output.status.success() {
        return Ok(());
    }

    let detail = String::from_utf8_lossy(&output.stderr).trim().to_string();
    Err(if detail.is_empty() {
        format!("taskkill failed for pid {}.", pid)
    } else {
        detail
    })
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn kill_process_tree(pid: u32) -> Result<(), String> {
    let output = hidden_command("kill")
        .args(["-TERM", &pid.to_string()])
        .output()
        .map_err(|error| format!("Failed to execute kill for pid {}: {}", pid, error))?;

    if output.status.success() {
        return Ok(());
    }

    let detail = String::from_utf8_lossy(&output.stderr).trim().to_string();
    Err(if detail.is_empty() {
        format!("kill failed for pid {}.", pid)
    } else {
        detail
    })
}
