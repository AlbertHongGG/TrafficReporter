use std::collections::BTreeMap;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Stdio};
use std::sync::{Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use tauri::Emitter;

use crate::contracts::{
    AiEvidenceProgressPayload, AiEvidenceRequestPayload, AiEvidenceResponsePayload,
    FrameExportRequest, LprAnalysisProvenancePayload,
    LprEvidenceExportRequestPayload, LprEvidenceExportResponsePayload,
    LprFrameAnalysisRequestPayload, LprFrameAnalysisResponsePayload,
    LprIntervalAnalysisRequestPayload, LprIntervalAnalysisResponsePayload,
    LprReviewStatePayload, LprRuntimeStatusPayload,
    LprTargetScanRequestPayload, LprTargetScanResponsePayload, MediaProbePayload,
    VideoMarkerRectPayload,
};
use crate::platform::process::{find_bundled, find_lpr_runtime_root, find_python_runtime, hidden_command};

const LPR_RUNTIME_RETRY_LIMIT: usize = 1;
const LPR_RUNTIME_PROTOCOL_VERSION: u8 = 1;
const APP_LOG_EVENT: &str = "app/log";
const AI_EVIDENCE_PROGRESS_EVENT: &str = "editor/ai-evidence-progress";

static LPR_RUNTIME_WORKER: OnceLock<Mutex<Option<PersistentLprRuntime>>> = OnceLock::new();
static LPR_RUNTIME_WORKER_PID: OnceLock<Mutex<Option<u32>>> = OnceLock::new();

struct PersistentLprRuntime {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
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
    ok: bool,
    result: Option<TResponse>,
    error: Option<String>,
    runtime: Option<LprRuntimeStatusPayload>,
    traceback: Option<String>,
}

enum RuntimeWorkerInvokeError {
    Recoverable(String),
    Unrecoverable(String),
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct AppLogPayload {
    level: String,
    scope: String,
    message: String,
}

fn emit_app_log(app_handle: &tauri::AppHandle, level: &str, scope: &str, message: impl Into<String>) {
    let message = message.into();
    match level {
        "debug" => log::debug!(target: scope, "{}", message),
        "info" => log::info!(target: scope, "{}", message),
        "warn" => log::warn!(target: scope, "{}", message),
        _ => log::error!(target: scope, "{}", message),
    }

    let _ = app_handle.emit(
        APP_LOG_EVENT,
        AppLogPayload {
            level: level.to_string(),
            scope: scope.to_string(),
            message,
        },
    );
}

impl PersistentLprRuntime {
    fn start(app_handle: tauri::AppHandle) -> Result<Self, String> {
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

        set_runtime_worker_pid(Some(child_pid));

        Ok(Self {
            child,
            stdin,
            stdout: BufReader::new(stdout),
            next_request_id: 1,
        })
    }

    fn is_alive(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(None))
    }

    fn invoke<TRequest, TResponse>(
        &mut self,
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

        let mut response_line = String::new();
        let bytes_read = self.stdout.read_line(&mut response_line).map_err(|error| {
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

        let response: RuntimeWorkerResponse<TResponse> = serde_json::from_str(response_line.trim_end()).map_err(|error| {
            RuntimeWorkerInvokeError::Recoverable(format!(
                "Failed to parse the LPR runtime worker response: {}\n{}",
                error,
                response_line.trim()
            ))
        })?;

        if response.request_id != request.request_id {
            return Err(RuntimeWorkerInvokeError::Recoverable(format!(
                "Mismatched LPR runtime worker response: expected request {}, received {}.",
                request.request_id,
                response.request_id,
            )));
        }

        if response.protocol_version != request.protocol_version {
            return Err(RuntimeWorkerInvokeError::Recoverable(format!(
                "Mismatched LPR runtime worker protocol: expected version {}, received {}.",
                request.protocol_version,
                response.protocol_version,
            )));
        }

        if response.ok {
            return response.result.ok_or_else(|| {
                RuntimeWorkerInvokeError::Unrecoverable(
                    "The local LPR runtime worker returned success without a payload.".to_string(),
                )
            });
        }

        Err(RuntimeWorkerInvokeError::Unrecoverable(format_worker_error(response)))
    }
}

fn runtime_worker_slot() -> &'static Mutex<Option<PersistentLprRuntime>> {
    LPR_RUNTIME_WORKER.get_or_init(|| Mutex::new(None))
}

fn runtime_worker_pid_slot() -> &'static Mutex<Option<u32>> {
    LPR_RUNTIME_WORKER_PID.get_or_init(|| Mutex::new(None))
}

fn set_runtime_worker_pid(pid: Option<u32>) {
    if let Ok(mut guard) = runtime_worker_pid_slot().lock() {
        *guard = pid;
    }
}

fn active_runtime_worker_pid() -> Result<Option<u32>, String> {
    runtime_worker_pid_slot()
        .lock()
        .map(|guard| *guard)
        .map_err(|_| "Failed to lock the local LPR runtime worker pid slot.".to_string())
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

fn terminate_lpr_runtime_process(app_handle: &tauri::AppHandle, reason: &str) -> Result<bool, String> {
    let Some(pid) = active_runtime_worker_pid()? else {
        emit_app_log(app_handle, "debug", "LprRuntimeWorker", format!("Cancellation skipped: no active worker. reason={}", reason));
        return Ok(false);
    };

    emit_app_log(
        app_handle,
        "warn",
        "LprRuntimeWorker",
        format!("Terminating persistent Python runtime worker pid={} reason={}", pid, reason),
    );
    kill_process_tree(pid)?;
    set_runtime_worker_pid(None);
    Ok(true)
}

fn emit_lpr_request_log(
    app_handle: &tauri::AppHandle,
    command: &str,
    request_id: Option<&str>,
    analysis_profile_id: Option<&str>,
    developer_diagnostics_enabled: bool,
) {
    emit_app_log(
        app_handle,
        "info",
        "LprRuntimeRequest",
        format!(
            "command={} requestId={} profile={} developerDiagnostics={}",
            command,
            request_id.unwrap_or("-"),
            analysis_profile_id.unwrap_or("-"),
            developer_diagnostics_enabled,
        ),
    );
}

fn emit_lpr_result_log(
    app_handle: &tauri::AppHandle,
    provenance: &LprAnalysisProvenancePayload,
    review: &LprReviewStatePayload,
    candidate_count: usize,
) {
    emit_app_log(
        app_handle,
        "info",
        "LprRuntimeResult",
        format!(
            "command={} requestId={} status={} suggested={} accepted={} candidates={} profile={} runtimeVersion={}",
            provenance.command,
            provenance.request_id.as_deref().unwrap_or("-"),
            review.status,
            review.suggested_candidate_id.as_deref().unwrap_or("-"),
            review.accepted_candidate_id.as_deref().unwrap_or("-"),
            candidate_count,
            provenance.analysis_profile_id.as_deref().unwrap_or("-"),
            provenance.runtime_version.as_deref().unwrap_or("-"),
        ),
    );
}

fn emit_ai_evidence_progress(
    app_handle: &tauri::AppHandle,
    request_id: Option<&str>,
    progress: f64,
    stage: &str,
    detail: impl Into<String>,
    done: bool,
    failed: bool,
) {
    let _ = app_handle.emit(
        AI_EVIDENCE_PROGRESS_EVENT,
        AiEvidenceProgressPayload {
            progress,
            stage: stage.to_string(),
            detail: detail.into(),
            done,
            failed,
            request_id: request_id.map(|value| value.to_string()),
        },
    );
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

fn parse_decimal_seconds_to_ms(value: &str) -> Option<u64> {
    let seconds = value.trim().parse::<f64>().ok()?;
    Some((seconds * 1000.0).round().max(0.0) as u64)
}

fn parse_clock_to_ms(value: &str) -> Option<u64> {
    let mut parts = value.trim().split(':');
    let hours = parts.next()?.parse::<f64>().ok()?;
    let minutes = parts.next()?.parse::<f64>().ok()?;
    let seconds = parts.next()?.parse::<f64>().ok()?;
    Some((((hours * 3600.0) + (minutes * 60.0) + seconds) * 1000.0).round().max(0.0) as u64)
}

fn parse_stream_resolution(line: &str) -> Option<(u32, u32)> {
    for token in line.split(|character: char| character == ',' || character.is_whitespace()) {
        let candidate = token.trim_matches(|character: char| !character.is_ascii_alphanumeric() && character != 'x');
        let Some((width, height)) = candidate.split_once('x') else {
            continue;
        };
        if width.is_empty() || height.is_empty() {
            continue;
        }

        if let (Ok(width), Ok(height)) = (width.parse::<u32>(), height.parse::<u32>()) {
            return Some((width, height));
        }
    }

    None
}

fn seconds_from_ms(value: u64) -> String {
    format!("{:.3}", value as f64 / 1000.0)
}

fn export_ai_evidence_clip(
    source_path: &str,
    start_ms: u64,
    end_ms: u64,
    output_path: &Path,
) -> Result<(), String> {
    if end_ms <= start_ms {
        return Err("AI evidence clip export requires a non-empty interval.".to_string());
    }

    if let Some(parent) = output_path.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)
                .map_err(|error| format!("Failed to create AI evidence clip directory: {}", error))?;
        }
    }

    let ffmpeg = find_bundled("ffmpeg")?;
    let duration_ms = end_ms.saturating_sub(start_ms);
    let args = vec![
        "-y".to_string(),
        "-hide_banner".to_string(),
        "-loglevel".to_string(),
        "error".to_string(),
        "-ss".to_string(),
        seconds_from_ms(start_ms),
        "-t".to_string(),
        seconds_from_ms(duration_ms),
        "-i".to_string(),
        source_path.to_string(),
        "-map".to_string(),
        "0:v:0".to_string(),
        "-map".to_string(),
        "0:a?".to_string(),
        "-c:v".to_string(),
        "libx264".to_string(),
        "-preset".to_string(),
        "faster".to_string(),
        "-pix_fmt".to_string(),
        "yuv420p".to_string(),
        "-c:a".to_string(),
        "aac".to_string(),
        "-movflags".to_string(),
        "+faststart".to_string(),
        output_path.to_string_lossy().to_string(),
    ];
    let output = hidden_command(&ffmpeg)
        .args(&args)
        .output()
        .map_err(|error| format!("Failed to execute ffmpeg for AI evidence clip export: {}", error))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(if stderr.is_empty() {
            "ffmpeg failed to export the AI evidence clip.".to_string()
        } else {
            stderr
        });
    }

    Ok(())
}

fn build_drawbox_filter(marker_rect: &VideoMarkerRectPayload) -> String {
    let x = marker_rect.x.clamp(0.0, 1.0);
    let y = marker_rect.y.clamp(0.0, 1.0);
    let width = marker_rect.width.clamp(0.05, 1.0 - x);
    let height = marker_rect.height.clamp(0.05, 1.0 - y);

    format!(
        "drawbox=x=iw*{x:.6}:y=ih*{y:.6}:w=iw*{width:.6}:h=ih*{height:.6}:color=red@1:thickness=4",
    )
}

fn invoke_lpr_runtime<TRequest, TResponse>(
    app_handle: tauri::AppHandle,
    subcommand: &str,
    payload: &TRequest,
) -> Result<TResponse, String>
where
    TRequest: Serialize,
    TResponse: DeserializeOwned,
{
    let worker_slot = runtime_worker_slot();
    let mut worker_guard = worker_slot
        .lock()
        .map_err(|_| "Failed to lock the local LPR runtime worker slot.".to_string())?;
    let mut attempt = 0usize;

    loop {
        let needs_restart = worker_guard
            .as_mut()
            .map(|worker| !worker.is_alive())
            .unwrap_or(true);
        if needs_restart {
            set_runtime_worker_pid(None);
            *worker_guard = Some(PersistentLprRuntime::start(app_handle.clone())?);
        }

        let worker = worker_guard.as_mut().ok_or_else(|| {
            "The local LPR runtime worker could not be initialized.".to_string()
        })?;

        match worker.invoke(subcommand, payload) {
            Ok(response) => return Ok(response),
            Err(RuntimeWorkerInvokeError::Unrecoverable(error)) => return Err(error),
            Err(RuntimeWorkerInvokeError::Recoverable(error)) => {
                emit_app_log(&app_handle, "warn", "LprRuntimeWorker", format!("Worker request failed and will be restarted: {}", error));
                set_runtime_worker_pid(None);
                *worker_guard = None;
                if attempt >= LPR_RUNTIME_RETRY_LIMIT {
                    return Err(error);
                }
                attempt += 1;
            }
        }
    }
}

fn probe_with_ffprobe(path: &str) -> Result<MediaProbePayload, String> {
    let ffprobe = find_bundled("ffprobe")?;
    let output = hidden_command(&ffprobe)
        .args([
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ])
        .output()
        .map_err(|error| format!("Failed to execute ffprobe: {}", error))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(if stderr.is_empty() {
            "ffprobe failed to inspect the media file.".to_string()
        } else {
            stderr
        });
    }

    let value: serde_json::Value = serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("Failed to parse ffprobe output: {}", error))?;

    let duration_ms = value
        .get("format")
        .and_then(|format| format.get("duration"))
        .and_then(|duration| match duration {
            serde_json::Value::String(value) => parse_decimal_seconds_to_ms(value),
            serde_json::Value::Number(value) => parse_decimal_seconds_to_ms(&value.to_string()),
            _ => None,
        })
        .unwrap_or(0)
        .max(1000);

    let streams = value
        .get("streams")
        .and_then(|streams| streams.as_array())
        .cloned()
        .unwrap_or_default();

    let mut has_video = false;
    let mut has_audio = false;
    let mut width = None;
    let mut height = None;

    for stream in &streams {
        match stream.get("codec_type").and_then(|codec_type| codec_type.as_str()) {
            Some("video") => {
                has_video = true;
                width = width.or_else(|| {
                    stream
                        .get("width")
                        .and_then(|value| value.as_u64())
                        .and_then(|value| u32::try_from(value).ok())
                });
                height = height.or_else(|| {
                    stream
                        .get("height")
                        .and_then(|value| value.as_u64())
                        .and_then(|value| u32::try_from(value).ok())
                });
            }
            Some("audio") => {
                has_audio = true;
            }
            _ => {}
        }
    }

    if !has_video && !has_audio {
        return Err("ffprobe did not report any playable audio or video streams.".to_string());
    }

    Ok(MediaProbePayload {
        duration_ms,
        has_video,
        has_audio,
        width,
        height,
    })
}

fn probe_with_ffmpeg(path: &str) -> Result<MediaProbePayload, String> {
    let ffmpeg = find_bundled("ffmpeg")?;
    let output = hidden_command(&ffmpeg)
        .args(["-hide_banner", "-i", path])
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .output()
        .map_err(|error| format!("Failed to execute ffmpeg: {}", error))?;

    let stderr_output = String::from_utf8_lossy(&output.stderr).to_string();
    let mut duration_ms = 0;
    let mut has_video = false;
    let mut has_audio = false;
    let mut width = None;
    let mut height = None;

    for raw_line in stderr_output.lines() {
        let line = raw_line.trim();

        if duration_ms == 0 {
            if let Some(duration_section) = line.strip_prefix("Duration:") {
                if let Some(duration_value) = duration_section.split(',').next() {
                    duration_ms = parse_clock_to_ms(duration_value.trim()).unwrap_or(0);
                }
            }
        }

        if line.contains("Video:") {
            has_video = true;
            if width.is_none() || height.is_none() {
                if let Some((parsed_width, parsed_height)) = parse_stream_resolution(line) {
                    width = Some(parsed_width);
                    height = Some(parsed_height);
                }
            }
        }

        if line.contains("Audio:") {
            has_audio = true;
        }
    }

    if !has_video && !has_audio {
        let detail = stderr_output
            .lines()
            .rev()
            .take(6)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect::<Vec<_>>()
            .join("\n");
        return Err(if detail.trim().is_empty() {
            "ffmpeg could not inspect the media file.".to_string()
        } else {
            detail
        });
    }

    Ok(MediaProbePayload {
        duration_ms: duration_ms.max(1000),
        has_video,
        has_audio,
        width,
        height,
    })
}

#[tauri::command]
pub async fn probe_media_source(path: String) -> Result<MediaProbePayload, String> {
    let file_name = Path::new(&path)
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or(&path)
        .to_string();

    let metadata = fs::metadata(&path)
        .map_err(|error| format!("Unable to access {}: {}", file_name, error))?;
    if !metadata.is_file() {
        return Err(format!("{} is not a file.", file_name));
    }

    match probe_with_ffprobe(&path) {
        Ok(payload) => Ok(payload),
        Err(ffprobe_error) => probe_with_ffmpeg(&path).map_err(|ffmpeg_error| {
            format!(
                "Unable to read metadata for {}.\nffprobe: {}\nffmpeg: {}",
                file_name, ffprobe_error, ffmpeg_error
            )
        }),
    }
}

fn export_frame_image_internal(request: &FrameExportRequest) -> Result<(), String> {
    let ffmpeg = find_bundled("ffmpeg")?;
    let output_path = PathBuf::from(&request.output_path);
    if let Some(parent) = output_path.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)
                .map_err(|error| format!("Failed to create output directory: {}", error))?;
        }
    }

    let mut args = vec![
        "-y".to_string(),
        "-hide_banner".to_string(),
        "-loglevel".to_string(),
        "error".to_string(),
        "-i".to_string(),
        request.source_path.clone(),
        "-ss".to_string(),
        seconds_from_ms(request.time_ms),
    ];

    if let Some(marker_rect) = request.marker_rect.as_ref() {
        args.extend(["-vf".to_string(), build_drawbox_filter(marker_rect)]);
    }

    args.extend([
        "-frames:v".to_string(),
        "1".to_string(),
        output_path.to_string_lossy().to_string(),
    ]);

    let output = hidden_command(&ffmpeg)
        .args(&args)
        .output()
        .map_err(|error| format!("Failed to execute ffmpeg: {}", error))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(if stderr.is_empty() {
            "ffmpeg failed to export the frame.".to_string()
        } else {
            stderr
        });
    }

    Ok(())
}

#[tauri::command]
pub fn export_frame_image(request: FrameExportRequest) -> Result<(), String> {
    export_frame_image_internal(&request)
}

#[tauri::command]
pub async fn get_lpr_runtime_status(
    app_handle: tauri::AppHandle,
) -> Result<LprRuntimeStatusPayload, String> {
    tauri::async_runtime::spawn_blocking(move || invoke_lpr_runtime(app_handle, "status", &serde_json::json!({})))
        .await
        .map_err(|error| format!("Failed to join runtime status task: {}", error))?
}

#[tauri::command]
pub async fn scan_lpr_targets(
    app_handle: tauri::AppHandle,
    request: LprTargetScanRequestPayload,
) -> Result<LprTargetScanResponsePayload, String> {
    tauri::async_runtime::spawn_blocking(move || {
        emit_lpr_request_log(
            &app_handle,
            "scan-targets",
            request.request_id.as_deref(),
            None,
            false,
        );
        let response: LprTargetScanResponsePayload = invoke_lpr_runtime(app_handle.clone(), "scan-targets", &request)?;
        emit_app_log(
            &app_handle,
            "info",
            "LprRuntimeResult",
            format!(
                "command=scan-targets requestId={} detections={}",
                request.request_id.as_deref().unwrap_or("-"),
                response.detections.len(),
            ),
        );
        Ok(response)
    })
        .await
        .map_err(|error| format!("Failed to join target scan task: {}", error))?
}

#[tauri::command]
pub async fn analyze_lpr_frame(
    app_handle: tauri::AppHandle,
    request: LprFrameAnalysisRequestPayload,
) -> Result<LprFrameAnalysisResponsePayload, String> {
    tauri::async_runtime::spawn_blocking(move || {
        emit_lpr_request_log(
            &app_handle,
            "analyze-frame",
            request.request_id.as_deref(),
            request.analysis_profile_id.as_deref(),
            request.enable_developer_diagnostics.unwrap_or(false),
        );
        let response: LprFrameAnalysisResponsePayload =
            invoke_lpr_runtime(app_handle.clone(), "analyze-frame", &request)?;
        emit_lpr_result_log(&app_handle, &response.provenance, &response.review, response.candidates.len());
        Ok(response)
    })
        .await
        .map_err(|error| format!("Failed to join frame analysis task: {}", error))?
}

#[tauri::command]
pub async fn analyze_lpr_interval(
    app_handle: tauri::AppHandle,
    request: LprIntervalAnalysisRequestPayload,
) -> Result<LprIntervalAnalysisResponsePayload, String> {
    tauri::async_runtime::spawn_blocking(move || {
        emit_lpr_request_log(
            &app_handle,
            "analyze-interval",
            request.request_id.as_deref(),
            request.analysis_profile_id.as_deref(),
            request.enable_developer_diagnostics.unwrap_or(false),
        );
        let response: LprIntervalAnalysisResponsePayload =
            invoke_lpr_runtime(app_handle.clone(), "analyze-interval", &request)?;
        emit_lpr_result_log(&app_handle, &response.provenance, &response.review, response.candidates.len());
        Ok(response)
    })
        .await
        .map_err(|error| format!("Failed to join interval analysis task: {}", error))?
}

#[tauri::command]
pub async fn analyze_ai_evidence(
    app_handle: tauri::AppHandle,
    request: AiEvidenceRequestPayload,
) -> Result<AiEvidenceResponsePayload, String> {
    let request_id = request.request_id.clone();
    emit_ai_evidence_progress(
        &app_handle,
        request_id.as_deref(),
        0.05,
        "prepare",
        "Preparing AI evidence workflow.",
        false,
        false,
    );

    let app_handle_for_task = app_handle.clone();
    let response = tauri::async_runtime::spawn_blocking(move || -> Result<AiEvidenceResponsePayload, String> {
        emit_app_log(
            &app_handle_for_task,
            "info",
            "AiEvidenceRequest",
            format!(
                "requestId={} description={} vehicleKind={}",
                request.request_id.as_deref().unwrap_or("-"),
                request.description.as_str(),
                request.target_vehicle_kind.as_str(),
            ),
        );
        emit_ai_evidence_progress(
            &app_handle_for_task,
            request.request_id.as_deref(),
            0.15,
            "analyze",
            "Running AI evidence localization and range analysis.",
            false,
            false,
        );

        let mut response: AiEvidenceResponsePayload = invoke_lpr_runtime(
            app_handle_for_task.clone(),
            "ai-evidence",
            &request,
        )?;

        if let Some(interval) = response.interval.clone() {
            let request_folder = response
                .request_id
                .clone()
                .or_else(|| request.request_id.clone())
                .unwrap_or_else(|| format!("ai-evidence-{}", SystemTime::now().duration_since(UNIX_EPOCH).map(|value| value.as_millis()).unwrap_or(0)));
            let clip_path = find_lpr_runtime_root()?
                .join(".runtime")
                .join("ai-evidence")
                .join(request_folder)
                .join("clip.mp4");

            emit_ai_evidence_progress(
                &app_handle_for_task,
                response.request_id.as_deref(),
                0.8,
                "export-clip",
                "Exporting resolved AI evidence clip.",
                false,
                false,
            );
            export_ai_evidence_clip(
                &request.source_path,
                interval.start_ms,
                interval.end_ms,
                &clip_path,
            )?;
            response.clip_path = Some(clip_path.to_string_lossy().to_string());
        }

        Ok(response)
    })
    .await
    .map_err(|error| format!("Failed to join AI evidence task: {}", error))?;

    match response {
        Ok(payload) => {
            emit_ai_evidence_progress(
                &app_handle,
                payload.request_id.as_deref(),
                1.0,
                "completed",
                "AI evidence workflow completed.",
                true,
                false,
            );
            emit_app_log(
                &app_handle,
                "info",
                "AiEvidenceResult",
                format!(
                    "requestId={} plate={} clip={} keyframes={}",
                    payload.request_id.as_deref().unwrap_or("-"),
                    payload.plate_number.as_deref().unwrap_or("-"),
                    payload.clip_path.as_deref().unwrap_or("-"),
                    payload.keyframes.len(),
                ),
            );
            Ok(payload)
        }
        Err(error) => {
            emit_ai_evidence_progress(
                &app_handle,
                request_id.as_deref(),
                1.0,
                "failed",
                error.clone(),
                true,
                true,
            );
            Err(error)
        }
    }
}

#[tauri::command]
pub fn cancel_lpr_runtime_job(
    app_handle: tauri::AppHandle,
) -> Result<bool, String> {
    terminate_lpr_runtime_process(&app_handle, "ui-request")
}

#[tauri::command]
pub async fn export_lpr_evidence(
    app_handle: tauri::AppHandle,
    request: LprEvidenceExportRequestPayload,
) -> Result<LprEvidenceExportResponsePayload, String> {
    let log_request_id = request
        .provenance
        .as_ref()
        .and_then(|provenance| provenance.request_id.clone());
    let log_analysis_profile_id = request
        .provenance
        .as_ref()
        .and_then(|provenance| provenance.analysis_profile_id.clone());
    let log_review_status = request.review.as_ref().map(|review| review.status.clone());
    let response = tauri::async_runtime::spawn_blocking(move || -> Result<LprEvidenceExportResponsePayload, String> {
        let json_path = PathBuf::from(&request.output_path);
        if let Some(parent) = json_path.parent() {
            if !parent.as_os_str().is_empty() {
                fs::create_dir_all(parent)
                    .map_err(|error| format!("Failed to create evidence directory: {}", error))?;
            }
        }

        let bundle_dir = build_evidence_bundle_dir(&json_path);
        fs::create_dir_all(&bundle_dir)
            .map_err(|error| format!("Failed to create evidence bundle directory: {}", error))?;

        let image_path = bundle_dir.join("source-frame.png");
        export_frame_image_internal(&FrameExportRequest {
            output_path: image_path.to_string_lossy().to_string(),
            source_path: request.source_path.clone(),
            time_ms: request.time_ms,
            marker_rect: request.marker_rect.clone(),
        })?;

        let decision_frames = select_decision_samples(&request.accepted_candidate, &request.samples);
        let mut exported_file_count = 1usize;
        let exported_decision_frames = export_decision_frames(&bundle_dir, &decision_frames, &mut exported_file_count)?;

        let exported_at_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| format!("System clock error while exporting evidence: {}", error))?
            .as_millis() as u64;

        let snapshot = serde_json::json!({
            "exportedAtMs": exported_at_ms,
            "sourcePath": request.source_path,
            "timeMs": request.time_ms,
            "interval": request.interval,
            "markerRect": request.marker_rect,
            "targetTrack": request.target_track,
            "acceptedCandidate": request.accepted_candidate,
            "candidates": request.candidates,
            "samples": request.samples,
            "review": request.review,
            "provenance": request.provenance,
            "imagePath": image_path.to_string_lossy(),
            "bundleDir": bundle_dir.to_string_lossy(),
            "decisionFrames": exported_decision_frames,
        });

        let serialized_snapshot = serde_json::to_vec_pretty(&snapshot)
            .map_err(|error| format!("Failed to serialize evidence snapshot: {}", error))?;
        fs::write(&json_path, serialized_snapshot)
            .map_err(|error| format!("Failed to write evidence snapshot: {}", error))?;
        exported_file_count += 1;

        Ok(LprEvidenceExportResponsePayload {
            json_path: json_path.to_string_lossy().to_string(),
            image_path: image_path.to_string_lossy().to_string(),
            bundle_dir: bundle_dir.to_string_lossy().to_string(),
            exported_file_count,
            decision_frame_count: decision_frames.len(),
        })
    })
    .await
    .map_err(|error| format!("Failed to join evidence export task: {}", error))??;

    emit_app_log(
        &app_handle,
        "info",
        "LprEvidenceExport",
        format!(
            "requestId={} profile={} reviewStatus={} output={}",
            log_request_id.as_deref().unwrap_or("-"),
            log_analysis_profile_id.as_deref().unwrap_or("-"),
            log_review_status.as_deref().unwrap_or("-"),
            response.bundle_dir,
        ),
    );

    Ok(response)
}

struct DecisionSampleExport<'a> {
    sample: &'a crate::contracts::LprFrameSamplePayload,
    artifacts: Vec<(String, PathBuf)>,
    matched_candidate: Option<&'a crate::contracts::LprPlateCandidatePayload>,
    score: f64,
}

fn build_evidence_bundle_dir(json_path: &Path) -> PathBuf {
    let stem = json_path
        .file_stem()
        .and_then(|stem| stem.to_str())
        .filter(|stem| !stem.is_empty())
        .unwrap_or("lpr-evidence");
    json_path.with_file_name(format!("{}.bundle", stem))
}

fn normalize_plate_text(text: &str) -> String {
    text.chars()
        .filter(|character| character.is_ascii_alphanumeric())
        .map(|character| character.to_ascii_uppercase())
        .collect()
}

fn sanitize_path_component(value: &str) -> String {
    let sanitized: String = value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || matches!(character, '-' | '_') {
                character
            } else {
                '_'
            }
        })
        .collect();
    if sanitized.is_empty() {
        "evidence".to_string()
    } else {
        sanitized
    }
}

fn extract_sample_artifacts(
    sample: &crate::contracts::LprFrameSamplePayload,
) -> Vec<(String, PathBuf)> {
    let mut artifacts: BTreeMap<String, PathBuf> = BTreeMap::new();
    if let Some(image_path) = &sample.image_path {
        let path = PathBuf::from(image_path);
        if path.exists() {
            artifacts.insert("working".to_string(), path);
        }
    }

    if let Some(diagnostics) = &sample.diagnostics {
        if let Some(extra_artifacts) = diagnostics
            .get("plateProcessing")
            .and_then(|value| value.get("artifacts"))
            .and_then(|value| value.as_object())
        {
            for (key, value) in extra_artifacts {
                if let Some(path_value) = value.as_str() {
                    let path = PathBuf::from(path_value);
                    if path.exists() {
                        artifacts.insert(key.clone(), path);
                    }
                }
            }
        }
    }

    artifacts.into_iter().collect()
}

fn select_decision_samples<'a>(
    accepted_candidate: &'a Option<crate::contracts::LprPlateCandidatePayload>,
    samples: &'a [crate::contracts::LprFrameSamplePayload],
) -> Vec<DecisionSampleExport<'a>> {
    let accepted_text = accepted_candidate
        .as_ref()
        .map(|candidate| normalize_plate_text(&candidate.text))
        .unwrap_or_default();
    let mut ranked: Vec<DecisionSampleExport<'a>> = samples
        .iter()
        .filter_map(|sample| {
            let artifacts = extract_sample_artifacts(sample);
            let matched_candidate = sample
                .candidates
                .iter()
                .find(|candidate| !accepted_text.is_empty() && normalize_plate_text(&candidate.text) == accepted_text);
            let top_candidate = sample.candidates.first();
            if artifacts.is_empty() && matched_candidate.is_none() && top_candidate.is_none() {
                return None;
            }
            let candidate_confidence = matched_candidate
                .or(top_candidate)
                .map(|candidate| candidate.confidence)
                .unwrap_or(0.0);
            let quality_score = sample.quality.as_ref().map(|quality| quality.overall_score).unwrap_or(0.0);
            let artifact_bonus = if artifacts.is_empty() { 0.0 } else { 0.08 };
            let exact_bonus = if matched_candidate.is_some() { 0.22 } else { 0.0 };
            Some(DecisionSampleExport {
                sample,
                artifacts,
                matched_candidate,
                score: (candidate_confidence * 0.62) + (quality_score * 0.30) + artifact_bonus + exact_bonus,
            })
        })
        .collect();

    ranked.sort_by(|left, right| right.score.partial_cmp(&left.score).unwrap_or(std::cmp::Ordering::Equal));
    ranked.truncate(4);
    ranked
}

fn export_decision_frames(
    bundle_dir: &Path,
    decision_frames: &[DecisionSampleExport<'_>],
    exported_file_count: &mut usize,
) -> Result<Vec<serde_json::Value>, String> {
    let decision_root = bundle_dir.join("decision-frames");
    fs::create_dir_all(&decision_root)
        .map_err(|error| format!("Failed to create decision frame directory: {}", error))?;

    let mut exported: Vec<serde_json::Value> = Vec::new();
    for (index, decision_frame) in decision_frames.iter().enumerate() {
        let frame_dir = decision_root.join(format!(
            "{:02}-{}",
            index + 1,
            sanitize_path_component(&decision_frame.sample.id)
        ));
        fs::create_dir_all(&frame_dir)
            .map_err(|error| format!("Failed to create evidence frame directory: {}", error))?;

        let mut artifact_paths = serde_json::Map::new();
        for (artifact_key, source_path) in &decision_frame.artifacts {
            let extension = source_path
                .extension()
                .and_then(|value| value.to_str())
                .filter(|value| !value.is_empty())
                .unwrap_or("png");
            let destination = frame_dir.join(format!("{}.{}", sanitize_path_component(artifact_key), extension));
            fs::copy(source_path, &destination)
                .map_err(|error| format!("Failed to copy evidence artifact {}: {}", source_path.display(), error))?;
            *exported_file_count += 1;
            artifact_paths.insert(
                artifact_key.clone(),
                serde_json::Value::String(destination.to_string_lossy().to_string()),
            );
        }

        let frame_metadata = serde_json::json!({
            "rank": index + 1,
            "score": decision_frame.score,
            "matchedCandidate": decision_frame.matched_candidate,
            "sample": decision_frame.sample,
            "artifactPaths": artifact_paths,
        });
        let frame_json_path = frame_dir.join("frame.json");
        fs::write(
            &frame_json_path,
            serde_json::to_vec_pretty(&frame_metadata)
                .map_err(|error| format!("Failed to serialize evidence frame metadata: {}", error))?,
        )
        .map_err(|error| format!("Failed to write evidence frame metadata: {}", error))?;
        *exported_file_count += 1;

        exported.push(serde_json::json!({
            "sampleId": decision_frame.sample.id,
            "timeMs": decision_frame.sample.time_ms,
            "score": decision_frame.score,
            "matchedCandidate": decision_frame.matched_candidate,
            "artifactPaths": artifact_paths,
            "metadataPath": frame_json_path.to_string_lossy(),
        }));
    }

    Ok(exported)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contracts::{LprFrameSamplePayload, LprPlateCandidatePayload, LprQualityMetricsPayload};

    fn sample_quality(overall_score: f64) -> LprQualityMetricsPayload {
        LprQualityMetricsPayload {
            sharpness: 0.8,
            contrast: 0.8,
            plate_area: 0.2,
            angle_score: 0.7,
            occlusion_score: 0.9,
            glare_score: 0.9,
            legibility_score: 0.8,
            overall_score,
            legibility_level: "good".to_string(),
        }
    }

    fn sample_candidate(id: &str, text: &str, confidence: f64) -> LprPlateCandidatePayload {
        LprPlateCandidatePayload {
            id: id.to_string(),
            text: text.to_string(),
            confidence,
            source: "baseline".to_string(),
            frame_time_ms: Some(0),
            country_code: None,
            r#box: None,
            quality: None,
            diagnostics: None,
        }
    }

    #[test]
    fn parses_clock_values_to_milliseconds() {
        assert_eq!(parse_clock_to_ms("00:00:01.500"), Some(1500));
    }

    #[test]
    fn finds_stream_resolution_tokens() {
        assert_eq!(
            parse_stream_resolution("Stream #0:0: Video: h264, yuv420p, 1920x1080"),
            Some((1920, 1080))
        );
    }

    #[test]
    fn builds_drawbox_filter_from_normalized_marker_rect() {
        let filter = build_drawbox_filter(&VideoMarkerRectPayload {
            x: 0.2,
            y: 0.25,
            width: 0.3,
            height: 0.2,
        });

        assert!(filter.contains("drawbox="));
        assert!(filter.contains("iw*0.200000"));
        assert!(filter.contains("ih*0.250000"));
    }

    #[test]
    fn builds_bundle_directory_next_to_snapshot_json() {
        let bundle_dir = build_evidence_bundle_dir(Path::new("C:/tmp/review/evidence.json"));
        assert_eq!(bundle_dir, PathBuf::from("C:/tmp/review/evidence.bundle"));
    }

    #[test]
    fn ranks_matching_decision_samples_ahead_of_non_matching_ones() {
        let accepted_candidate = Some(sample_candidate("accepted", "ABC1234", 0.92));
        let samples = vec![
            LprFrameSamplePayload {
                id: "sample-low".to_string(),
                time_ms: 100,
                target_box: None,
                plate_box: None,
                quality: Some(sample_quality(0.4)),
                candidates: vec![sample_candidate("candidate-low", "ZZZ9999", 0.99)],
                image_path: None,
                diagnostics: None,
            },
            LprFrameSamplePayload {
                id: "sample-match".to_string(),
                time_ms: 200,
                target_box: None,
                plate_box: None,
                quality: Some(sample_quality(0.7)),
                candidates: vec![sample_candidate("candidate-match", "ABC1234", 0.81)],
                image_path: None,
                diagnostics: None,
            },
        ];

        let selected = select_decision_samples(&accepted_candidate, &samples);
        assert_eq!(selected.first().map(|entry| entry.sample.id.as_str()), Some("sample-match"));
    }
}
