use std::fs;
use std::path::{Path, PathBuf};
use std::process::Stdio;

use crate::contracts::{
    FrameExportRequest, MediaProbePayload, VideoMarkerRectPayload,
};
use crate::platform::process::{find_bundled, hidden_command};

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

#[tauri::command]
pub fn export_frame_image(request: FrameExportRequest) -> Result<(), String> {
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
        "-ss".to_string(),
        seconds_from_ms(request.time_ms),
        "-i".to_string(),
        request.source_path.clone(),
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

#[cfg(test)]
mod tests {
    use super::*;

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
}
