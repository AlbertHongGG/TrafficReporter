use crate::contracts::TimelineExportRequest;

fn make_even(value: u32) -> u32 {
    let normalized = value.max(2);
    if normalized % 2 == 0 {
        normalized
    } else {
        normalized - 1
    }
}

fn source_dimensions(width: u32, height: u32) -> (u32, u32) {
    (make_even(width.max(2)), make_even(height.max(2)))
}

fn scaled_dimensions_for_quality(width: u32, height: u32, quality: Option<&str>) -> (u32, u32) {
    let (base_width, base_height) = source_dimensions(width, height);

    let target_height = match quality.unwrap_or("source") {
        "source" => return (base_width, base_height),
        "2160p" => 2160,
        "1440p" => 1440,
        "1080p" => 1080,
        "720p" => 720,
        "480p" => 480,
        _ => return (base_width, base_height),
    };

    if base_height <= target_height {
        return (base_width, base_height);
    }

    let scale = target_height as f64 / base_height as f64;
    let scaled_width = ((base_width as f64) * scale).round() as u32;
    (make_even(scaled_width), make_even(target_height))
}

pub(crate) fn resolved_video_dimensions(request: &TimelineExportRequest) -> Option<(u32, u32)> {
    let format = request.profile.format.to_lowercase();
    if !matches!(format.as_str(), "mp4" | "mkv") {
        return None;
    }

    Some(scaled_dimensions_for_quality(
        request.snapshot.dominant_width.unwrap_or(1280),
        request.snapshot.dominant_height.unwrap_or(720),
        request.profile.video_quality.as_deref(),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn source_dimensions_are_even_and_preserve_size() {
        assert_eq!(source_dimensions(1921, 1081), (1920, 1080));
    }

    #[test]
    fn source_dimensions_do_not_downscale_smaller_inputs() {
        assert_eq!(source_dimensions(1280, 720), (1280, 720));
    }

    #[test]
    fn scaled_dimensions_respect_requested_quality() {
        assert_eq!(scaled_dimensions_for_quality(3840, 2160, Some("1080p")), (1920, 1080));
    }

    #[test]
    fn scaled_dimensions_never_upscale_beyond_source() {
        assert_eq!(scaled_dimensions_for_quality(1280, 720, Some("2160p")), (1280, 720));
    }
}
