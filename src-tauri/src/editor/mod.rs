mod runtime_broker;

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::Serialize;
use tauri::Emitter;
use runtime_broker::{invoke_lpr_runtime, terminate_lpr_runtime_process};

use crate::contracts::{
    AiEvidenceProgressPayload, AiEvidenceRequestPayload, AiEvidenceResponsePayload,
    FrameExportRequest, LprAnalysisProvenancePayload,
    LprEvidenceExportRequestPayload, LprEvidenceExportResponsePayload,
    LprFrameAnalysisRequestPayload, LprFrameAnalysisResponsePayload,
    LprIntervalAnalysisRequestPayload, LprIntervalAnalysisResponsePayload,
    OutputCompressionModePayload,
    LprReviewStatePayload, LprRuntimeStatusPayload,
    LprTargetScanRequestPayload, LprTargetScanResponsePayload, MediaProbePayload,
    VideoMarkerRectPayload,
};
use crate::media::{
    append_h264_aac_codec_args, resolve_audio_bitrate_kbps,
    resolve_still_image_quantization_max_colors, resolve_video_compression_settings,
    StillImageOutputTarget, VideoCompressionTarget,
};
use crate::platform::process::{find_bundled, find_lpr_runtime_root, hidden_command};

const APP_LOG_EVENT: &str = "app/log";
const AI_EVIDENCE_PROGRESS_EVENT: &str = "editor/ai-evidence-progress";

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

fn parse_stream_fps(line: &str) -> Option<u32> {
    for segment in line.split(',') {
        let trimmed = segment.trim();
        let Some(value) = trimmed.strip_suffix(" fps") else {
            continue;
        };

        let fps = value.trim().parse::<f64>().ok()?;
        if fps.is_finite() && fps > 0.0 {
            return Some(fps.round().clamp(1.0, 240.0) as u32);
        }
    }

    None
}

fn parse_stream_audio_bitrate_kbps(line: &str) -> Option<u32> {
    for segment in line.split(',') {
        let trimmed = segment.trim();
        let Some(value) = trimmed.strip_suffix(" kb/s") else {
            continue;
        };

        let bitrate_kbps = value.trim().parse::<f64>().ok()?;
        if bitrate_kbps.is_finite() && bitrate_kbps > 0.0 {
            return Some(bitrate_kbps.round().clamp(1.0, 10_000.0) as u32);
        }
    }

    None
}

fn parse_json_stream_bitrate_kbps(stream: &serde_json::Value) -> Option<u32> {
    let bitrate_bps = match stream.get("bit_rate") {
        Some(serde_json::Value::String(value)) => value.trim().parse::<u64>().ok(),
        Some(serde_json::Value::Number(value)) => value.as_u64(),
        _ => None,
    }?;

    if bitrate_bps == 0 {
        return None;
    }

    u32::try_from((bitrate_bps.saturating_add(500)) / 1000).ok()
}

fn seconds_from_ms(value: u64) -> String {
    format!("{:.3}", value as f64 / 1000.0)
}

fn runtime_data_root() -> Result<PathBuf, String> {
    let runtime_root = find_lpr_runtime_root()?;
    let repo_root = runtime_root
        .parent()
        .ok_or_else(|| "Failed to resolve the repository root for runtime artifacts.".to_string())?;
    Ok(repo_root.join(".runtime"))
}

fn runtime_run_root(run_id: &str) -> Result<PathBuf, String> {
    Ok(runtime_data_root()?.join("runs").join(run_id))
}

fn parse_ffprobe_frame_rate(value: &str) -> Option<u32> {
    let trimmed = value.trim();
    if trimmed.is_empty() || trimmed == "0/0" {
        return None;
    }

    let fps = if let Some((numerator, denominator)) = trimmed.split_once('/') {
        let numerator = numerator.trim().parse::<f64>().ok()?;
        let denominator = denominator.trim().parse::<f64>().ok()?;
        if denominator <= 0.0 {
            return None;
        }
        numerator / denominator
    } else {
        trimmed.parse::<f64>().ok()?
    };

    if !fps.is_finite() || fps <= 0.0 {
        return None;
    }

    Some(fps.round().clamp(1.0, 240.0) as u32)
}

fn probe_video_stream_profile(path: &str) -> Result<(u32, u32, u32), String> {
    let ffprobe = find_bundled("ffprobe")?;
    let output = hidden_command(&ffprobe)
        .args([
            "-v",
            "error",
            "-print_format",
            "json",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,avg_frame_rate,r_frame_rate",
            path,
        ])
        .output()
        .map_err(|error| format!("Failed to execute ffprobe for video stream profile: {}", error))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(if stderr.is_empty() {
            "ffprobe failed to inspect the video stream profile.".to_string()
        } else {
            stderr
        });
    }

    let value: serde_json::Value = serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("Failed to parse video stream profile: {}", error))?;
    let stream = value
        .get("streams")
        .and_then(|streams| streams.as_array())
        .and_then(|streams| streams.first())
        .ok_or_else(|| "ffprobe did not report a primary video stream.".to_string())?;

    let width = stream
        .get("width")
        .and_then(|value| value.as_u64())
        .and_then(|value| u32::try_from(value).ok())
        .filter(|value| *value > 0)
        .ok_or_else(|| "ffprobe did not report the video width.".to_string())?;
    let height = stream
        .get("height")
        .and_then(|value| value.as_u64())
        .and_then(|value| u32::try_from(value).ok())
        .filter(|value| *value > 0)
        .ok_or_else(|| "ffprobe did not report the video height.".to_string())?;
    let fps = stream
        .get("avg_frame_rate")
        .and_then(|value| value.as_str())
        .and_then(parse_ffprobe_frame_rate)
        .or_else(|| {
            stream
                .get("r_frame_rate")
                .and_then(|value| value.as_str())
                .and_then(parse_ffprobe_frame_rate)
        })
        .unwrap_or(30);

    Ok((width, height, fps))
}

fn build_ai_evidence_clip_args(
    source_path: &str,
    start_ms: u64,
    end_ms: u64,
    output_path: &Path,
    compression_mode: OutputCompressionModePayload,
    audio_bitrate_kbps: Option<u32>,
    stream_profile: (u32, u32, u32),
) -> Vec<String> {
    let duration_ms = end_ms.saturating_sub(start_ms);
    let (width, height, fps) = stream_profile;
    let settings = resolve_video_compression_settings(
        compression_mode,
        VideoCompressionTarget::AiEvidenceClip,
        width,
        height,
        fps,
    );
    let mut args = vec![
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
    ];
    append_h264_aac_codec_args(
        &mut args,
        settings,
        resolve_audio_bitrate_kbps(audio_bitrate_kbps),
        true,
    );
    args.push(output_path.to_string_lossy().to_string());
    args
}

fn export_ai_evidence_clip(
    source_path: &str,
    start_ms: u64,
    end_ms: u64,
    output_path: &Path,
    compression_mode: OutputCompressionModePayload,
    audio_bitrate_kbps: Option<u32>,
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
    let stream_profile = probe_video_stream_profile(source_path)?;
    let args = build_ai_evidence_clip_args(
        source_path,
        start_ms,
        end_ms,
        output_path,
        compression_mode,
        audio_bitrate_kbps,
        stream_profile,
    );
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
    let mut fps = None;
    let mut audio_bitrate_kbps = None;
    let mut width = None;
    let mut height = None;

    for stream in &streams {
        match stream.get("codec_type").and_then(|codec_type| codec_type.as_str()) {
            Some("video") => {
                has_video = true;
                fps = fps.or_else(|| {
                    stream
                        .get("avg_frame_rate")
                        .and_then(|value| value.as_str())
                        .and_then(parse_ffprobe_frame_rate)
                }).or_else(|| {
                    stream
                        .get("r_frame_rate")
                        .and_then(|value| value.as_str())
                        .and_then(parse_ffprobe_frame_rate)
                });
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
                audio_bitrate_kbps = audio_bitrate_kbps.or_else(|| parse_json_stream_bitrate_kbps(stream));
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
        fps,
        audio_bitrate_kbps,
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
    let mut fps = None;
    let mut audio_bitrate_kbps = None;
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
            if fps.is_none() {
                fps = parse_stream_fps(line);
            }
            if width.is_none() || height.is_none() {
                if let Some((parsed_width, parsed_height)) = parse_stream_resolution(line) {
                    width = Some(parsed_width);
                    height = Some(parsed_height);
                }
            }
        }

        if line.contains("Audio:") {
            has_audio = true;
            if audio_bitrate_kbps.is_none() {
                audio_bitrate_kbps = parse_stream_audio_bitrate_kbps(line);
            }
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
        fps,
        audio_bitrate_kbps,
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

fn export_frame_image_internal(
    request: &FrameExportRequest,
    output_target: StillImageOutputTarget,
) -> Result<(), String> {
    let ffmpeg = find_bundled("ffmpeg")?;
    let output_path = PathBuf::from(&request.output_path);
    ensure_png_output_path(&output_path)?;
    if let Some(parent) = output_path.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)
                .map_err(|error| format!("Failed to create output directory: {}", error))?;
        }
    }

    let temp_png_path = build_temp_png_path(&output_path);
    let export_result = (|| -> Result<(), String> {
        run_ffmpeg_command(&ffmpeg, &build_frame_export_args_for_output(request, &temp_png_path))?;

        finalize_png_export(&ffmpeg, &temp_png_path, &output_path, request.compression_mode, output_target)?;
        fs::remove_file(&temp_png_path)
            .map_err(|error| format!("Failed to clean temporary PNG export: {}", error))?;

        Ok(())
    })();

    if export_result.is_err() {
        let _ = fs::remove_file(&temp_png_path);
    }

    export_result
}

fn run_ffmpeg_command(ffmpeg: &str, args: &[String]) -> Result<(), String> {
    let output = hidden_command(ffmpeg)
        .args(args)
        .output()
        .map_err(|error| format!("Failed to execute ffmpeg: {}", error))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        Err(if stderr.is_empty() {
            "ffmpeg failed to export the frame.".to_string()
        } else {
            stderr
        })
    } else {
        Ok(())
    }
}

fn finalize_png_export(
    ffmpeg: &str,
    staged_png_path: &Path,
    output_path: &Path,
    compression_mode: OutputCompressionModePayload,
    output_target: StillImageOutputTarget,
) -> Result<(), String> {
    if let Some(max_colors) = resolve_still_image_quantization_max_colors(compression_mode, output_target) {
        run_ffmpeg_command(ffmpeg, &build_png_quantize_args(staged_png_path, output_path, max_colors))
    } else {
        fs::copy(staged_png_path, output_path)
            .map_err(|error| format!("Failed to finalize PNG export: {}", error))?;
        Ok(())
    }
}

fn finalize_existing_png_asset_in_place(
    ffmpeg: &str,
    output_path: &Path,
    compression_mode: OutputCompressionModePayload,
    output_target: StillImageOutputTarget,
) -> Result<(), String> {
    ensure_png_output_path(output_path)?;
    let temp_png_path = build_temp_png_path(output_path);
    fs::copy(output_path, &temp_png_path)
        .map_err(|error| format!("Failed to stage PNG artifact for finalization: {}", error))?;

    let result = finalize_png_export(ffmpeg, &temp_png_path, output_path, compression_mode, output_target);
    let cleanup_result = fs::remove_file(&temp_png_path)
        .map_err(|error| format!("Failed to clean temporary PNG artifact: {}", error));

    match (result, cleanup_result) {
        (Ok(()), Ok(())) => Ok(()),
        (Err(error), _) => Err(error),
        (Ok(()), Err(error)) => Err(error),
    }
}

fn copy_png_asset_with_compression(
    ffmpeg: &str,
    source_path: &Path,
    output_path: &Path,
    compression_mode: OutputCompressionModePayload,
    output_target: StillImageOutputTarget,
) -> Result<(), String> {
    ensure_png_output_path(output_path)?;
    finalize_png_export(ffmpeg, source_path, output_path, compression_mode, output_target)
}

fn finalize_ai_keyframe_artifacts(
    response: &mut AiEvidenceResponsePayload,
    compression_mode: OutputCompressionModePayload,
) -> Result<(), String> {
    if response.keyframes.is_empty() {
        return Ok(());
    }

    let ffmpeg = find_bundled("ffmpeg")?;
    for keyframe in &response.keyframes {
        let Some(image_path) = keyframe.frame.image_path.as_deref() else {
            continue;
        };

        let path = PathBuf::from(image_path);
        if !path.exists() {
            continue;
        }

        let is_png = path
            .extension()
            .and_then(|value| value.to_str())
            .map(|value| value.eq_ignore_ascii_case("png"))
            .unwrap_or(false);
        if is_png {
            finalize_existing_png_asset_in_place(
                &ffmpeg,
                &path,
                compression_mode,
                StillImageOutputTarget::AiEvidenceKeyframe,
            )?;
        }
    }

    Ok(())
}

fn ensure_png_output_path(output_path: &Path) -> Result<(), String> {
    let extension = output_path
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| value.to_ascii_lowercase());
    if matches!(extension.as_deref(), Some("png")) {
        Ok(())
    } else {
        Err("Frame and evidence image exports only support PNG output paths.".to_string())
    }
}

#[cfg(test)]
fn build_frame_export_args(request: &FrameExportRequest) -> Vec<String> {
    build_frame_export_args_for_output(request, &PathBuf::from(&request.output_path))
}

fn build_frame_export_args_for_output(request: &FrameExportRequest, output_path: &Path) -> Vec<String> {
    let output_path_string = output_path.to_string_lossy().to_string();

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
    ]);

    args.push(output_path_string);
    args
}

fn build_png_quantize_args(input_path: &Path, output_path: &Path, max_colors: u32) -> Vec<String> {
    vec![
        "-y".to_string(),
        "-hide_banner".to_string(),
        "-loglevel".to_string(),
        "error".to_string(),
        "-i".to_string(),
        input_path.to_string_lossy().to_string(),
        "-filter_complex".to_string(),
        format!(
            "[0:v]split=2[work][palette];[palette]palettegen=max_colors={max_colors}:stats_mode=single[p];[work][p]paletteuse=dither=bayer:bayer_scale=3:new=1[quantized]"
        ),
        "-map".to_string(),
        "[quantized]".to_string(),
        "-frames:v".to_string(),
        "1".to_string(),
        output_path.to_string_lossy().to_string(),
    ]
}

fn build_temp_png_path(output_path: &Path) -> PathBuf {
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_micros())
        .unwrap_or(0);
    let stem = output_path
        .file_stem()
        .and_then(|value| value.to_str())
        .filter(|value| !value.is_empty())
        .unwrap_or("frame-export");
    output_path.with_file_name(format!("{stem}.render-{timestamp}.png"))
}

fn build_evidence_source_frame_path(
    bundle_dir: &Path,
    _compression_mode: OutputCompressionModePayload,
) -> PathBuf {
    bundle_dir.join("source-frame.png")
}

#[tauri::command]
pub fn save_generated_media_asset(source_path: String, output_path: String) -> Result<(), String> {
    let source_path = PathBuf::from(source_path);
    if !source_path.exists() {
        return Err(format!("Source artifact does not exist: {}", source_path.display()));
    }

    let output_path = PathBuf::from(output_path);
    if let Some(parent) = output_path.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)
                .map_err(|error| format!("Failed to create output directory: {}", error))?;
        }
    }

    fs::copy(&source_path, &output_path)
        .map_err(|error| format!("Failed to save generated media asset: {}", error))?;
    Ok(())
}

#[tauri::command]
pub fn export_frame_image(request: FrameExportRequest) -> Result<(), String> {
    export_frame_image_internal(&request, StillImageOutputTarget::FrameExport)
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
                "requestId={} description={} vehicleKind={} compressionMode={}",
                request.request_id.as_deref().unwrap_or("-"),
                request.description.as_str(),
                request.target_vehicle_kind.as_str(),
                if request.compression_mode.is_compact() { "compact" } else { "standard" },
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
        finalize_ai_keyframe_artifacts(&mut response, request.compression_mode)?;

        if let Some(interval) = response.interval.clone() {
            let request_folder = response
                .request_id
                .clone()
                .or_else(|| request.request_id.clone())
                .unwrap_or_else(|| format!("ai-evidence-{}", SystemTime::now().duration_since(UNIX_EPOCH).map(|value| value.as_millis()).unwrap_or(0)));
            let clip_path = runtime_run_root(&request_folder)?
                .join("ai-evidence")
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
                request.compression_mode,
                request.audio_bitrate_kbps,
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

        let image_path = build_evidence_source_frame_path(&bundle_dir, request.compression_mode);
        export_frame_image_internal(&FrameExportRequest {
            output_path: image_path.to_string_lossy().to_string(),
            source_path: request.source_path.clone(),
            time_ms: request.time_ms,
            marker_rect: request.marker_rect.clone(),
            compression_mode: request.compression_mode,
        }, StillImageOutputTarget::EvidenceSourceFrame)?;

        let decision_frames = select_decision_samples(&request.accepted_candidate, &request.samples);
        let mut exported_file_count = 1usize;
        let exported_decision_frames = export_decision_frames(
            &bundle_dir,
            &decision_frames,
            request.compression_mode,
            &mut exported_file_count,
        )?;

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
            "compressionMode": request.compression_mode,
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
    compression_mode: OutputCompressionModePayload,
    exported_file_count: &mut usize,
) -> Result<Vec<serde_json::Value>, String> {
    let decision_root = bundle_dir.join("decision-frames");
    fs::create_dir_all(&decision_root)
        .map_err(|error| format!("Failed to create decision frame directory: {}", error))?;

    let compact_png_copy = compression_mode.is_compact();
    let ffmpeg = if compact_png_copy {
        Some(find_bundled("ffmpeg")?)
    } else {
        None
    };
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
            let is_png = extension.eq_ignore_ascii_case("png");
            if is_png && compact_png_copy {
                copy_png_asset_with_compression(
                    ffmpeg.as_deref().unwrap_or_default(),
                    source_path,
                    &destination,
                    compression_mode,
                    StillImageOutputTarget::EvidenceDecisionArtifact,
                )?;
            } else {
                fs::copy(source_path, &destination)
                    .map_err(|error| format!("Failed to copy evidence artifact {}: {}", source_path.display(), error))?;
            }
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
mod ai_clip_tests {
    use super::*;

    #[test]
    fn parse_ffprobe_frame_rate_handles_fractional_values() {
        assert_eq!(parse_ffprobe_frame_rate("60000/1001"), Some(60));
        assert_eq!(parse_ffprobe_frame_rate("30000/1001"), Some(30));
        assert_eq!(parse_ffprobe_frame_rate("0/0"), None);
    }

    #[test]
    fn compact_ai_clip_args_use_shared_video_policy_and_audio_bitrate() {
        let args = build_ai_evidence_clip_args(
            "demo.mp4",
            1000,
            4000,
            Path::new("clip.mp4"),
            OutputCompressionModePayload::Compact,
            Some(256),
            (1920, 1080, 60),
        );

        assert!(args.windows(2).any(|window| window == ["-preset", "veryslow"]));
        assert!(args.windows(2).any(|window| window == ["-crf", "34"]));
        assert!(args.windows(2).any(|window| window == ["-g", "240"]));
        assert!(args.windows(2).any(|window| window == ["-maxrate", "1428k"]));
        assert!(args.windows(2).any(|window| window == ["-b:a", "256k"]));
        assert!(args.windows(2).any(|window| window == ["-movflags", "+faststart"]));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contracts::{
        LprFrameSamplePayload, LprPlateCandidatePayload, LprQualityMetricsPayload,
        OutputCompressionModePayload,
    };

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
    fn chooses_evidence_frame_extension_from_compression_mode() {
        let compact_path = build_evidence_source_frame_path(
            Path::new("C:/tmp/review/evidence.bundle"),
            OutputCompressionModePayload::Compact,
        );
        let standard_path = build_evidence_source_frame_path(
            Path::new("C:/tmp/review/evidence.bundle"),
            OutputCompressionModePayload::Standard,
        );

        assert_eq!(compact_path, PathBuf::from("C:/tmp/review/evidence.bundle/source-frame.png"));
        assert_eq!(standard_path, PathBuf::from("C:/tmp/review/evidence.bundle/source-frame.png"));
    }

    #[test]
    fn compact_png_quantization_uses_palette_filters() {
        let args = build_png_quantize_args(
            Path::new("C:/tmp/frame.render.png"),
            Path::new("C:/tmp/frame.png"),
            192,
        );

        assert!(args.windows(2).any(|window| window == ["-map", "[quantized]"]));
        assert!(args.iter().any(|value| value.contains("palettegen=max_colors=192")));
        assert!(args.iter().any(|value| value.contains("paletteuse=dither=bayer")));
    }

    #[test]
    fn raw_frame_exports_target_png_output() {
        let args = build_frame_export_args(&FrameExportRequest {
            output_path: "C:/tmp/frame.png".to_string(),
            source_path: "C:/tmp/source.mp4".to_string(),
            time_ms: 1250,
            marker_rect: None,
            compression_mode: OutputCompressionModePayload::Compact,
        });

        assert_eq!(args.last().map(String::as_str), Some("C:/tmp/frame.png"));
        assert!(!args.iter().any(|value| value == "-q:v"));
    }

    #[test]
    fn rejects_non_png_frame_output_paths() {
        assert!(ensure_png_output_path(Path::new("C:/tmp/frame.jpg")).is_err());
        assert!(ensure_png_output_path(Path::new("C:/tmp/frame.png")).is_ok());
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
