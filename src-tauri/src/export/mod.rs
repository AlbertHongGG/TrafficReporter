use std::collections::{HashMap, HashSet};
use std::io::{BufRead, BufReader};
use std::process::Stdio;

use tauri::{AppHandle, Emitter, State};

use crate::app::AppState;
use crate::contracts::{
    ExportProgressPayload, ExportSnapshotPayload, ExportSource, RenderProfilePayload,
    TimelineClipPayload, TimelineExportRequest,
};
use crate::platform::process::{find_bundled, hidden_command};

#[tauri::command]
pub fn set_pending_export_session(
    state: State<AppState>,
    session: ExportSnapshotPayload,
) -> Result<(), String> {
    let mut guard = state
        .pending_export_snapshot
        .lock()
        .map_err(|_| "Failed to lock export session state.".to_string())?;
    *guard = Some(session);
    Ok(())
}

#[tauri::command]
pub fn get_pending_export_session(state: State<AppState>) -> Result<Option<ExportSnapshotPayload>, String> {
    let guard = state
        .pending_export_snapshot
        .lock()
        .map_err(|_| "Failed to lock export session state.".to_string())?;
    Ok(guard.clone())
}

fn seconds_from_ms(value: u64) -> String {
    format!("{:.3}", value as f64 / 1000.0)
}

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

fn make_even(value: u32) -> u32 {
    let normalized = value.max(2);
    if normalized % 2 == 0 {
        normalized
    } else {
        normalized - 1
    }
}

fn scaled_dimensions_for_quality(width: u32, height: u32, quality: Option<&str>) -> (u32, u32) {
    let base_width = width.max(2);
    let base_height = height.max(2);

    let target_height = match quality.unwrap_or("1080p") {
        "source" => return (make_even(base_width), make_even(base_height)),
        "2160p" => 2160,
        "1440p" => 1440,
        "1080p" => 1080,
        "720p" => 720,
        "480p" => 480,
        _ => 1080,
    };

    if base_height <= target_height {
        return (make_even(base_width), make_even(base_height));
    }

    let scale = target_height as f64 / base_height as f64;
    let scaled_width = ((base_width as f64) * scale).round() as u32;
    (make_even(scaled_width), make_even(target_height))
}

fn build_filter_graph(request: &TimelineExportRequest) -> Result<(Vec<String>, String, Option<String>), String> {
    let snapshot = &request.snapshot;
    let format = request.profile.format.to_lowercase();
    let is_video_output = matches!(format.as_str(), "mp4" | "mkv");
    let mut args = vec![
        "-y".to_string(),
        "-hide_banner".to_string(),
        "-nostats".to_string(),
        "-progress".to_string(),
        "pipe:1".to_string(),
    ];

    let total_ms = snapshot.timeline_duration_ms.max(1000);
    let total_seconds = seconds_from_ms(total_ms);
    let (width, height) = if is_video_output {
        scaled_dimensions_for_quality(
            snapshot.dominant_width.unwrap_or(1280),
            snapshot.dominant_height.unwrap_or(720),
            request.profile.video_quality.as_deref(),
        )
    } else {
        (0, 0)
    };

    if is_video_output {
        args.extend([
            "-f".to_string(),
            "lavfi".to_string(),
            "-i".to_string(),
            format!(
                "color=c=#09090b:s={}x{}:d={}:r={}",
                width,
                height,
                total_seconds,
                request.profile.fps.max(1)
            ),
            "-f".to_string(),
            "lavfi".to_string(),
            "-i".to_string(),
            format!("anullsrc=channel_layout=stereo:sample_rate=48000:d={}", total_seconds),
        ]);
    } else {
        args.extend([
            "-f".to_string(),
            "lavfi".to_string(),
            "-i".to_string(),
            format!("anullsrc=channel_layout=stereo:sample_rate=48000:d={}", total_seconds),
        ]);
    }

    let mut next_input_index = if is_video_output { 2usize } else { 1usize };
    let used_source_ids: HashSet<&str> = snapshot.clips.iter().map(|clip| clip.asset_id.as_str()).collect();
    let used_sources: Vec<&ExportSource> = snapshot
        .sources
        .iter()
        .filter(|source| used_source_ids.contains(source.id.as_str()))
        .collect();
    if used_sources.is_empty() {
        return Err("No media sources available for export.".to_string());
    }

    let mut source_input_indices: HashMap<&str, usize> = HashMap::new();
    for source in &used_sources {
        source_input_indices.insert(source.id.as_str(), next_input_index);
        args.extend(["-i".to_string(), source.path.clone()]);
        next_input_index += 1;
    }

    let track_order_map: HashMap<&str, i32> = snapshot
        .tracks
        .iter()
        .map(|track| (track.id.as_str(), track.order))
        .collect();
    let source_map: HashMap<&str, &ExportSource> = snapshot
        .sources
        .iter()
        .map(|source| (source.id.as_str(), source))
        .collect();

    let mut filters: Vec<String> = Vec::new();

    let video_output_label = if is_video_output {
        filters.push("[0:v]format=yuv420p[vbase0]".to_string());
        let mut current_video_label = "vbase0".to_string();
        let mut video_clips: Vec<&TimelineClipPayload> = snapshot
            .clips
            .iter()
            .filter(|clip| {
                source_map
                    .get(clip.asset_id.as_str())
                    .map(|source| source.has_video)
                    .unwrap_or(false)
            })
            .collect();
        video_clips.sort_by_key(|clip| {
            (
                track_order_map.get(clip.track_id.as_str()).copied().unwrap_or_default(),
                clip.start_ms,
            )
        });

        for (index, clip) in video_clips.iter().enumerate() {
            let input_index = source_input_indices
                .get(clip.asset_id.as_str())
                .ok_or_else(|| "Missing ffmpeg input index for video clip.".to_string())?;
            let clip_label = format!("vclip{}", index);
            let next_label = format!("vbase{}", index + 1);
            let clip_end_ms = clip.start_ms + clip.out_point_ms.saturating_sub(clip.in_point_ms);

            filters.push(format!(
                "[{input}:v]trim=start={trim_start}:end={trim_end},setpts=PTS-STARTPTS+{timeline_start}/TB,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x09090b[{label}]",
                input = input_index,
                trim_start = seconds_from_ms(clip.in_point_ms),
                trim_end = seconds_from_ms(clip.out_point_ms),
                timeline_start = seconds_from_ms(clip.start_ms),
                width = width,
                height = height,
                label = clip_label,
            ));

            filters.push(format!(
                "[{base}][{clip}]overlay=eof_action=pass:enable='between(t,{enable_start},{enable_end})'[{next}]",
                base = current_video_label,
                clip = clip_label,
                enable_start = seconds_from_ms(clip.start_ms),
                enable_end = seconds_from_ms(clip_end_ms),
                next = next_label,
            ));

            current_video_label = next_label;
        }

        Some(current_video_label)
    } else {
        None
    };

    let mut audio_mix_inputs = vec![format!("[{}:a]", if is_video_output { 1 } else { 0 })];
    let mut audio_clips: Vec<&TimelineClipPayload> = snapshot
        .clips
        .iter()
        .filter(|clip| {
            !clip.muted
                && source_map
                    .get(clip.asset_id.as_str())
                    .map(|source| source.has_audio)
                    .unwrap_or(false)
        })
        .collect();
    audio_clips.sort_by_key(|clip| {
        (
            track_order_map.get(clip.track_id.as_str()).copied().unwrap_or_default(),
            clip.start_ms,
        )
    });

    for (index, clip) in audio_clips.iter().enumerate() {
        let input_index = source_input_indices
            .get(clip.asset_id.as_str())
            .ok_or_else(|| "Missing ffmpeg input index for audio clip.".to_string())?;
        let audio_label = format!("aclip{}", index);
        filters.push(format!(
            "[{input}:a]atrim=start={trim_start}:end={trim_end},asetpts=PTS-STARTPTS,adelay={delay}:all=1[{label}]",
            input = input_index,
            trim_start = seconds_from_ms(clip.in_point_ms),
            trim_end = seconds_from_ms(clip.out_point_ms),
            delay = clip.start_ms,
            label = audio_label,
        ));
        audio_mix_inputs.push(format!("[{label}]", label = audio_label));
    }

    filters.push(format!(
        "{inputs}amix=inputs={count}:duration=longest:normalize=0[aout]",
        inputs = audio_mix_inputs.join(""),
        count = audio_mix_inputs.len(),
    ));

    args.extend([
        "-filter_complex".to_string(),
        filters.join(";"),
        "-t".to_string(),
        total_seconds,
    ]);

    Ok((
        args,
        "[aout]".to_string(),
        video_output_label.map(|label| format!("[{label}]")),
    ))
}

fn codec_args_for_profile(profile: &RenderProfilePayload) -> Vec<String> {
    let format = profile.format.to_lowercase();
    let bitrate = profile.audio_bitrate_kbps.unwrap_or(320).clamp(96, 320);

    match format.as_str() {
        "mp4" => vec![
            "-c:v".to_string(),
            "libx264".to_string(),
            "-preset".to_string(),
            "medium".to_string(),
            "-crf".to_string(),
            "18".to_string(),
            "-pix_fmt".to_string(),
            "yuv420p".to_string(),
            "-c:a".to_string(),
            "aac".to_string(),
            "-b:a".to_string(),
            format!("{}k", bitrate.min(192)),
            "-movflags".to_string(),
            "+faststart".to_string(),
        ],
        "mkv" => vec![
            "-c:v".to_string(),
            "libx264".to_string(),
            "-preset".to_string(),
            "medium".to_string(),
            "-crf".to_string(),
            "18".to_string(),
            "-pix_fmt".to_string(),
            "yuv420p".to_string(),
            "-c:a".to_string(),
            "aac".to_string(),
            "-b:a".to_string(),
            format!("{}k", bitrate.min(192)),
        ],
        "mp3" => vec![
            "-c:a".to_string(),
            "libmp3lame".to_string(),
            "-b:a".to_string(),
            format!("{}k", bitrate),
        ],
        "m4a" => vec![
            "-c:a".to_string(),
            "aac".to_string(),
            "-b:a".to_string(),
            format!("{}k", bitrate),
        ],
        "wav" => vec!["-c:a".to_string(), "pcm_s16le".to_string()],
        _ => vec![
            "-c:v".to_string(),
            "libx264".to_string(),
            "-preset".to_string(),
            "medium".to_string(),
            "-crf".to_string(),
            "18".to_string(),
            "-pix_fmt".to_string(),
            "yuv420p".to_string(),
            "-c:a".to_string(),
            "aac".to_string(),
            "-b:a".to_string(),
            "192k".to_string(),
            "-movflags".to_string(),
            "+faststart".to_string(),
        ],
    }
}

#[tauri::command]
pub async fn process_timeline_export(app: AppHandle, request: TimelineExportRequest) -> Result<(), String> {
    let ffmpeg = find_bundled("ffmpeg")?;
    let total_ms = request.snapshot.timeline_duration_ms.max(1000);
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

    let (mut args, audio_map, video_map) = build_filter_graph(&request)?;
    if let Some(video_map) = video_map {
        args.extend(["-map".to_string(), video_map]);
    }
    args.extend(["-map".to_string(), audio_map]);
    args.extend(codec_args_for_profile(&request.profile));
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
                format!("{} / {}", seconds_from_ms(last_out_time_ms), seconds_from_ms(total_ms))
            } else {
                format!(
                    "{} / {}  •  {}",
                    seconds_from_ms(last_out_time_ms),
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scales_to_even_dimensions() {
        assert_eq!(scaled_dimensions_for_quality(1921, 1081, Some("720p")), (1278, 720));
    }

    #[test]
    fn keeps_source_dimensions_when_requested() {
        assert_eq!(scaled_dimensions_for_quality(1921, 1081, Some("source")), (1920, 1080));
    }
}