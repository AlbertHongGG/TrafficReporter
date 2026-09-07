use crate::contracts::TimelineExportRequest;
use crate::platform::process::{find_bundled, hidden_command};

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

pub(crate) fn clamp_export_fps(requested_fps: u32, source_fps: Option<u32>) -> u32 {
    let requested_fps = requested_fps.max(1);
    source_fps.map(|fps| fps.max(1).min(requested_fps)).unwrap_or(requested_fps)
}

fn probe_source_video_fps(path: &str) -> Option<u32> {
    let ffprobe = find_bundled("ffprobe").ok()?;
    let output = hidden_command(&ffprobe)
        .args([
            "-v",
            "error",
            "-print_format",
            "json",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=avg_frame_rate,r_frame_rate",
            path,
        ])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }

    let value: serde_json::Value = serde_json::from_slice(&output.stdout).ok()?;
    let stream = value
        .get("streams")
        .and_then(|streams| streams.as_array())
        .and_then(|streams| streams.first())?;

    stream
        .get("avg_frame_rate")
        .and_then(|value| value.as_str())
        .and_then(parse_ffprobe_frame_rate)
        .or_else(|| {
            stream
                .get("r_frame_rate")
                .and_then(|value| value.as_str())
                .and_then(parse_ffprobe_frame_rate)
        })
}

pub(crate) fn resolved_export_fps(request: &TimelineExportRequest) -> u32 {
    let source_fps = request
        .snapshot
        .sources
        .iter()
        .find(|source| source.has_video)
        .and_then(|source| probe_source_video_fps(&source.path));
    clamp_export_fps(request.profile.fps, source_fps)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn export_fps_is_clamped_to_source_rate() {
        assert_eq!(clamp_export_fps(60, Some(30)), 30);
        assert_eq!(clamp_export_fps(24, Some(30)), 24);
        assert_eq!(clamp_export_fps(60, None), 60);
    }
}
