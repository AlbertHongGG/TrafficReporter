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
    FrameExportRequest, LprEvidenceExportRequestPayload, LprEvidenceExportResponsePayload,
    LprFrameAnalysisRequestPayload, LprFrameAnalysisResponsePayload,
    LprIntervalAnalysisRequestPayload, LprIntervalAnalysisResponsePayload,
    LprRuntimeStatusPayload, LprTargetScanRequestPayload, LprTargetScanResponsePayload,
    MediaProbePayload, VideoMarkerRectPayload,
};
use crate::platform::process::{find_bundled, find_lpr_runtime_root, find_python_runtime, hidden_command};

const LPR_RUNTIME_RETRY_LIMIT: usize = 1;
const APP_LOG_EVENT: &str = "app/log";

static LPR_RUNTIME_WORKER: OnceLock<Mutex<Option<PersistentLprRuntime>>> = OnceLock::new();

struct PersistentLprRuntime {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
    next_request_id: u64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeWorkerRequest<'a, TRequest: Serialize> {
    request_id: u64,
    subcommand: &'a str,
    payload: &'a TRequest,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeWorkerResponse<TResponse> {
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
    tauri::async_runtime::spawn_blocking(move || invoke_lpr_runtime(app_handle, "scan-targets", &request))
        .await
        .map_err(|error| format!("Failed to join target scan task: {}", error))?
}

#[tauri::command]
pub async fn analyze_lpr_frame(
    app_handle: tauri::AppHandle,
    request: LprFrameAnalysisRequestPayload,
) -> Result<LprFrameAnalysisResponsePayload, String> {
    tauri::async_runtime::spawn_blocking(move || invoke_lpr_runtime(app_handle, "analyze-frame", &request))
        .await
        .map_err(|error| format!("Failed to join frame analysis task: {}", error))?
}

#[tauri::command]
pub async fn analyze_lpr_interval(
    app_handle: tauri::AppHandle,
    request: LprIntervalAnalysisRequestPayload,
) -> Result<LprIntervalAnalysisResponsePayload, String> {
    tauri::async_runtime::spawn_blocking(move || invoke_lpr_runtime(app_handle, "analyze-interval", &request))
        .await
        .map_err(|error| format!("Failed to join interval analysis task: {}", error))?
}

#[tauri::command]
pub async fn export_lpr_evidence(
    request: LprEvidenceExportRequestPayload,
) -> Result<LprEvidenceExportResponsePayload, String> {
    tauri::async_runtime::spawn_blocking(move || {
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
    .map_err(|error| format!("Failed to join evidence export task: {}", error))?
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
