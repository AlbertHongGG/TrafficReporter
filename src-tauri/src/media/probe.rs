use std::fs;
use std::path::Path;
use std::process::Stdio;

use crate::contracts::MediaProbePayload;
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

pub(crate) fn parse_ffprobe_frame_rate(value: &str) -> Option<u32> {
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

pub(crate) fn probe_video_stream_profile(path: &str) -> Result<(u32, u32, u32), String> {
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
        duration_ms: duration_ms as f64,
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
        duration_ms: (duration_ms.max(1000)) as f64,
        has_video,
        has_audio,
        fps,
        audio_bitrate_kbps,
        width,
        height,
    })
}

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
}
