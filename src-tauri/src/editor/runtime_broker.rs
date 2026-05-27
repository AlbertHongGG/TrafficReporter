use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, ChildStdout, Stdio};
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};

use crate::contracts::{LprProgressPayload, LprRuntimeStatusPayload};
use crate::platform::process::{find_lpr_runtime_root, find_python_runtime, hidden_command};

const LPR_RUNTIME_RETRY_LIMIT: usize = 1;
const LPR_RUNTIME_PROTOCOL_VERSION: u8 = 1;
const LPR_RUNTIME_REQUEST_TIMEOUT: Duration = Duration::from_secs(300);

static RUNTIME_BROKER: OnceLock<RuntimeBroker> = OnceLock::new();

struct RuntimeBroker {
    worker: Mutex<Option<PersistentLprRuntime>>,
    worker_pid: Mutex<Option<u32>>,
}

struct PersistentLprRuntime {
    child: Child,
    stdin: ChildStdin,
    stdout: Option<BufReader<ChildStdout>>,
    next_request_id: u64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeWorkerRequest<'a, TRequest: Serialize> {
    protocol_version: u8,
    request_id: u64,
    subcommand: &'a str,
    payload: &'a TRequest,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeWorkerResponse<TResponse> {
    protocol_version: u8,
    request_id: u64,
    kind: Option<String>,
    ok: Option<bool>,
    progress: Option<LprProgressPayload>,
    result: Option<TResponse>,
    error: Option<String>,
    runtime: Option<LprRuntimeStatusPayload>,
    traceback: Option<String>,
}

#[derive(Debug)]
enum RuntimeWorkerInvokeError {
    Recoverable(String),
    Unrecoverable(String),
}

enum RuntimeWorkerEnvelope<TResponse> {
    Progress(LprProgressPayload),
    Success(TResponse),
    Error(RuntimeWorkerResponse<TResponse>),
}

fn parse_worker_response_line<TResponse>(
    response_line: &str,
    request_id: u64,
    protocol_version: u8,
) -> Result<RuntimeWorkerEnvelope<TResponse>, RuntimeWorkerInvokeError>
where
    TResponse: DeserializeOwned,
{
    let response: RuntimeWorkerResponse<TResponse> = serde_json::from_str(response_line.trim_end()).map_err(|error| {
        RuntimeWorkerInvokeError::Recoverable(format!(
            "Failed to parse the LPR runtime worker response: {}\n{}",
            error,
            response_line.trim()
        ))
    })?;

    if response.request_id != request_id {
        return Err(RuntimeWorkerInvokeError::Recoverable(format!(
            "Mismatched LPR runtime worker response: expected request {}, received {}.",
            request_id,
            response.request_id,
        )));
    }

    if response.protocol_version != protocol_version {
        return Err(RuntimeWorkerInvokeError::Recoverable(format!(
            "Mismatched LPR runtime worker protocol: expected version {}, received {}.",
            protocol_version,
            response.protocol_version,
        )));
    }

    if response.kind.as_deref() == Some("progress") {
        let progress = response.progress.ok_or_else(|| {
            RuntimeWorkerInvokeError::Recoverable(
                "The local LPR runtime worker emitted a progress envelope without a progress payload.".to_string(),
            )
        })?;
        return Ok(RuntimeWorkerEnvelope::Progress(progress));
    }

    if response.ok == Some(true) {
        let result = response.result.ok_or_else(|| {
            RuntimeWorkerInvokeError::Unrecoverable(
                "The local LPR runtime worker returned success without a payload.".to_string(),
            )
        })?;
        return Ok(RuntimeWorkerEnvelope::Success(result));
    }

    Ok(RuntimeWorkerEnvelope::Error(response))
}

impl RuntimeBroker {
    fn new() -> Self {
        Self {
            worker: Mutex::new(None),
            worker_pid: Mutex::new(None),
        }
    }

    fn set_worker_pid(&self, pid: Option<u32>) {
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
        let mut worker_guard = self
            .worker
            .lock()
            .map_err(|_| "Failed to lock the local LPR runtime worker slot.".to_string())?;
        let mut attempt = 0usize;

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

            match worker.invoke(&app_handle, subcommand, payload) {
                Ok(response) => return Ok(response),
                Err(RuntimeWorkerInvokeError::Unrecoverable(error)) => return Err(error),
                Err(RuntimeWorkerInvokeError::Recoverable(error)) => {
                    super::emit_app_log(
                        &app_handle,
                        "warn",
                        "LprRuntimeWorker",
                        format!("Worker request failed and will be restarted: {}", error),
                    );
                    self.set_worker_pid(None);
                    *worker_guard = None;
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
            super::emit_app_log(
                app_handle,
                "debug",
                "LprRuntimeWorker",
                format!("Cancellation skipped: no active worker. reason={}", reason),
            );
            return Ok(false);
        };

        super::emit_app_log(
            app_handle,
            "warn",
            "LprRuntimeWorker",
            format!("Terminating persistent Python runtime worker pid={} reason={}", pid, reason),
        );
        kill_process_tree(pid)?;
        self.set_worker_pid(None);
        if let Ok(mut guard) = self.worker.lock() {
            *guard = None;
        }
        Ok(true)
    }
}

impl PersistentLprRuntime {
    fn start(app_handle: tauri::AppHandle) -> Result<Self, String> {
        let python = find_python_runtime()?;
        let runtime_root = find_lpr_runtime_root()?;
        super::emit_app_log(&app_handle, "info", "LprRuntimeWorker", "Starting persistent Python runtime worker.");
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
                                super::emit_app_log(&stderr_app_handle, "warn", "LprRuntimeWorker", message.to_string());
                            }
                        }
                        Err(error) => {
                            super::emit_app_log(
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

    fn is_alive(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(None))
    }

    fn invoke<TRequest, TResponse>(
        &mut self,
        app_handle: &tauri::AppHandle,
        subcommand: &str,
        payload: &TRequest,
    ) -> Result<TResponse, RuntimeWorkerInvokeError>
    where
        TRequest: Serialize,
        TResponse: DeserializeOwned,
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
            let response_line = self.read_response_line()?;
            match parse_worker_response_line(&response_line, request.request_id, request.protocol_version)? {
                RuntimeWorkerEnvelope::Progress(progress) => {
                    super::emit_lpr_progress(
                        app_handle,
                        progress.request_id.as_deref(),
                        progress.progress,
                        &progress.stage,
                        progress.detail,
                        progress.done,
                        progress.failed,
                        progress.reason_code.as_deref(),
                        progress.tracking_tier.as_deref(),
                        progress.coverage_ratio,
                    );
                    continue;
                }
                RuntimeWorkerEnvelope::Success(result) => return Ok(result),
                RuntimeWorkerEnvelope::Error(response) => {
                    return Err(RuntimeWorkerInvokeError::Unrecoverable(format_worker_error(response)));
                }
            }
        }
    }

    fn read_response_line(&mut self) -> Result<String, RuntimeWorkerInvokeError> {
        let stdout = self.stdout.take().ok_or_else(|| {
            RuntimeWorkerInvokeError::Recoverable(
                "The local LPR runtime worker response stream is not available.".to_string(),
            )
        })?;

        let (sender, receiver) = std::sync::mpsc::sync_channel(1);
        std::thread::spawn(move || {
            let mut stdout = stdout;
            let mut response_line = String::new();
            let result = stdout.read_line(&mut response_line).map(|bytes_read| (bytes_read, response_line));
            let _ = sender.send((stdout, result));
        });

        match receiver.recv_timeout(LPR_RUNTIME_REQUEST_TIMEOUT) {
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
                    LPR_RUNTIME_REQUEST_TIMEOUT.as_millis()
                )))
            }
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => Err(RuntimeWorkerInvokeError::Recoverable(
                "The local LPR runtime worker response reader disconnected unexpectedly.".to_string(),
            )),
        }
    }
}

#[cfg(target_os = "windows")]
fn kill_process_tree(pid: u32) -> Result<(), String> {
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
fn kill_process_tree(pid: u32) -> Result<(), String> {
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

fn format_worker_error<TResponse>(response: RuntimeWorkerResponse<TResponse>) -> String {
    let mut detail = response
        .error
        .unwrap_or_else(|| "The local LPR runtime worker reported an error.".to_string());

    if let Some(runtime) = response.runtime {
        let runtime_detail = runtime.detail.trim();
        if !runtime_detail.is_empty() && runtime_detail != detail {
            detail = format!("{}\n{}", detail, runtime_detail);
        }
    }

    if let Some(traceback) = response.traceback {
        let traceback = traceback.trim();
        if !traceback.is_empty() {
            detail = format!("{}\n{}", detail, traceback);
        }
    }

    detail
}

fn runtime_broker() -> &'static RuntimeBroker {
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

pub(crate) fn terminate_lpr_runtime_process(
    app_handle: &tauri::AppHandle,
    reason: &str,
) -> Result<bool, String> {
    runtime_broker().terminate(app_handle, reason)
}

#[cfg(test)]
mod tests {
    use serde_json::Value;

    use super::{parse_worker_response_line, RuntimeWorkerEnvelope, RuntimeWorkerInvokeError};

    #[test]
    fn parse_worker_response_line_accepts_progress_envelopes() {
        let envelope = parse_worker_response_line::<Value>(
            r#"{"protocolVersion":1,"requestId":7,"kind":"progress","progress":{"requestId":"req-7","progress":0.4,"stage":"Interval","detail":"Analyzing tracked sample 2/5.","done":false,"failed":false,"reasonCode":null,"trackingTier":"partial","coverageRatio":0.4}}"#,
            7,
            1,
        )
        .expect("progress envelope should parse");

        match envelope {
            RuntimeWorkerEnvelope::Progress(progress) => {
                assert_eq!(progress.request_id.as_deref(), Some("req-7"));
                assert_eq!(progress.stage, "Interval");
                assert_eq!(progress.detail, "Analyzing tracked sample 2/5.");
                assert!((progress.progress - 0.4).abs() < f64::EPSILON);
                assert_eq!(progress.tracking_tier.as_deref(), Some("partial"));
                assert_eq!(progress.coverage_ratio, Some(0.4));
            }
            RuntimeWorkerEnvelope::Success(_) | RuntimeWorkerEnvelope::Error(_) => {
                panic!("expected a progress envelope")
            }
        }
    }

    #[test]
    fn parse_worker_response_line_accepts_success_envelopes() {
        let envelope = parse_worker_response_line::<Value>(
            r#"{"protocolVersion":1,"requestId":8,"ok":true,"result":{"status":"ok","samples":3}}"#,
            8,
            1,
        )
        .expect("success envelope should parse");

        match envelope {
            RuntimeWorkerEnvelope::Success(result) => {
                assert_eq!(result.get("status").and_then(Value::as_str), Some("ok"));
                assert_eq!(result.get("samples").and_then(Value::as_i64), Some(3));
            }
            RuntimeWorkerEnvelope::Progress(_) | RuntimeWorkerEnvelope::Error(_) => {
                panic!("expected a success envelope")
            }
        }
    }

    #[test]
    fn parse_worker_response_line_rejects_progress_without_payload() {
        let result = parse_worker_response_line::<Value>(
            r#"{"protocolVersion":1,"requestId":9,"kind":"progress"}"#,
            9,
            1,
        );

        match result {
            Err(RuntimeWorkerInvokeError::Recoverable(message)) => {
                assert!(message.contains("without a progress payload"));
            }
            Ok(_) | Err(RuntimeWorkerInvokeError::Unrecoverable(_)) => {
                panic!("expected a recoverable progress payload error")
            }
        }
    }
}