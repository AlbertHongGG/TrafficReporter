use std::io::{BufRead, BufReader};
use std::process::Stdio;

use tauri::{AppHandle, Emitter};

use crate::contracts::{ExportProgressPayload, TimelineExportRequest};
use crate::platform::process::{find_bundled, hidden_command};

use super::codec::codec_args_for_profile;
use super::dimensions::resolved_video_dimensions;
use super::filter_graph::{build_filter_graph, seconds_from_ms};
use super::fps::resolved_export_fps;

fn emit_export_progress(
    app: &AppHandle,
    progress: f64,
    stage: &str,
    detail: String,
    done: bool,
    failed: bool,
) {
    let _ = app.emit(
        "editor/export-progress",
        ExportProgressPayload {
            progress,
            stage: stage.to_string(),
            detail,
            done,
            failed,
        },
    );
}

pub async fn process_timeline_export(app: AppHandle, request: TimelineExportRequest) -> Result<(), String> {
    let ffmpeg = find_bundled("ffmpeg")?;
    let total_ms = request.snapshot.timeline_duration_ms.max(1000.0);
    let format = request.profile.format.to_lowercase();
    let is_video_output = matches!(format.as_str(), "mp4" | "mkv");

    emit_export_progress(
        &app,
        0.02,
        if is_video_output { "render" } else { "mix" },
        "Preparing ffmpeg graph...".to_string(),
        false,
        false,
    );

    let export_fps = resolved_export_fps(&request);
    let (mut args, audio_map, video_map) = build_filter_graph(&request, export_fps)?;
    if let Some(video_map) = video_map {
        args.extend(["-map".to_string(), video_map]);
    }
    args.extend(["-map".to_string(), audio_map]);
    args.extend(codec_args_for_profile(&request.profile, resolved_video_dimensions(&request), export_fps));
    args.push(request.output_path.clone());

    let mut child = hidden_command(&ffmpeg)
        .args(&args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("Failed to execute ffmpeg: {}", error))?;

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "Failed to capture ffmpeg progress output.".to_string())?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "Failed to capture ffmpeg error output.".to_string())?;

    let stderr_handle = std::thread::spawn(move || {
        let reader = BufReader::new(stderr);
        let mut lines = Vec::new();
        for line in reader.lines().map_while(Result::ok) {
            lines.push(line);
        }
        lines.join("\n")
    });

    let progress_reader = BufReader::new(stdout);
    let mut last_out_time_ms = 0u64;
    let mut last_speed = String::new();
    for line in progress_reader.lines().map_while(Result::ok) {
        let trimmed = line.trim();
        if let Some(value) = trimmed.strip_prefix("out_time_us=") {
            if let Ok(parsed) = value.parse::<u64>() {
                last_out_time_ms = parsed / 1000;
            }
            continue;
        }
        if let Some(value) = trimmed.strip_prefix("out_time_ms=") {
            if let Ok(parsed) = value.parse::<u64>() {
                last_out_time_ms = parsed / 1000;
            }
            continue;
        }
        if let Some(value) = trimmed.strip_prefix("speed=") {
            last_speed = value.trim().to_string();
            continue;
        }
        if trimmed == "progress=continue" || trimmed == "progress=end" {
            let progress = (last_out_time_ms as f64 / total_ms as f64).clamp(0.0, 0.98);
            let detail = if last_speed.is_empty() {
                format!("{} / {}", seconds_from_ms(last_out_time_ms as f64), seconds_from_ms(total_ms))
            } else {
                format!(
                    "{} / {}  •  {}",
                    seconds_from_ms(last_out_time_ms as f64),
                    seconds_from_ms(total_ms),
                    last_speed
                )
            };

            emit_export_progress(
                &app,
                if trimmed == "progress=end" { 0.99 } else { progress },
                if is_video_output { "render" } else { "mix" },
                detail,
                false,
                false,
            );
        }
    }

    let status = child
        .wait()
        .map_err(|error| format!("Failed to wait on ffmpeg: {}", error))?;
    let stderr_output = stderr_handle.join().unwrap_or_default();

    if !status.success() {
        let detail = if stderr_output.trim().is_empty() {
            "ffmpeg exited with a failure status.".to_string()
        } else {
            stderr_output
                .lines()
                .rev()
                .take(8)
                .collect::<Vec<_>>()
                .into_iter()
                .rev()
                .collect::<Vec<_>>()
                .join("\n")
        };
        emit_export_progress(&app, 0.0, "error", detail.clone(), false, true);
        return Err(detail);
    }

    emit_export_progress(
        &app,
        1.0,
        "done",
        format!("Saved to {}", request.output_path),
        true,
        false,
    );

    Ok(())
}
