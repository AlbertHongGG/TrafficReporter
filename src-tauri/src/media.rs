use crate::contracts::OutputCompressionModePayload;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VideoCompressionTarget {
    TimelineExport,
    AiEvidenceClip,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StillImageOutputTarget {
    FrameExport,
    EvidenceSourceFrame,
    AiEvidenceKeyframe,
    EvidenceDecisionArtifact,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct VideoCompressionSettings {
    pub preset: &'static str,
    pub crf: u32,
    pub gop_size: u32,
    pub min_keyframe_interval: u32,
    pub b_frames: u32,
    pub sc_threshold: u32,
    pub maxrate_kbps: Option<u32>,
    pub bufsize_kbps: Option<u32>,
}

pub fn resolve_audio_bitrate_kbps(requested_kbps: Option<u32>) -> u32 {
    requested_kbps.unwrap_or(320).clamp(96, 320)
}

pub fn resolve_video_compression_settings(
    compression_mode: OutputCompressionModePayload,
    output_target: VideoCompressionTarget,
    width: u32,
    height: u32,
    fps: u32,
) -> VideoCompressionSettings {
    let safe_fps = fps.max(1);
    let is_compact = compression_mode.is_compact();
    let gop_size = match (output_target, is_compact) {
        (VideoCompressionTarget::TimelineExport, true) => safe_fps.saturating_mul(10),
        (VideoCompressionTarget::AiEvidenceClip, true) => safe_fps.saturating_mul(4),
        (_, false) => safe_fps.saturating_mul(2),
    };
    let min_keyframe_interval = if is_compact {
        safe_fps.max(1)
    } else {
        (safe_fps / 2).max(1)
    };

    let maxrate_kbps = if is_compact {
        Some(compact_video_maxrate_kbps(width, height, fps, output_target))
    } else {
        None
    };

    VideoCompressionSettings {
        preset: if is_compact { "veryslow" } else { "medium" },
        crf: if is_compact { 34 } else { 18 },
        gop_size,
        min_keyframe_interval,
        b_frames: if is_compact { 4 } else { 2 },
        sc_threshold: if is_compact { 0 } else { 40 },
        maxrate_kbps,
        bufsize_kbps: maxrate_kbps.map(|value| value.saturating_mul(2)),
    }
}

pub fn append_h264_aac_codec_args(
    args: &mut Vec<String>,
    settings: VideoCompressionSettings,
    audio_bitrate_kbps: u32,
    include_faststart: bool,
) {
    args.extend([
        "-c:v".to_string(),
        "libx264".to_string(),
        "-preset".to_string(),
        settings.preset.to_string(),
        "-crf".to_string(),
        settings.crf.to_string(),
        "-pix_fmt".to_string(),
        "yuv420p".to_string(),
        "-g".to_string(),
        settings.gop_size.to_string(),
        "-keyint_min".to_string(),
        settings.min_keyframe_interval.to_string(),
        "-bf".to_string(),
        settings.b_frames.to_string(),
        "-sc_threshold".to_string(),
        settings.sc_threshold.to_string(),
    ]);

    if let (Some(maxrate), Some(bufsize)) = (settings.maxrate_kbps, settings.bufsize_kbps) {
        args.extend([
            "-maxrate".to_string(),
            format!("{}k", maxrate),
            "-bufsize".to_string(),
            format!("{}k", bufsize),
        ]);
    }

    args.extend([
        "-c:a".to_string(),
        "aac".to_string(),
        "-b:a".to_string(),
        format!("{}k", audio_bitrate_kbps),
    ]);

    if include_faststart {
        args.extend(["-movflags".to_string(), "+faststart".to_string()]);
    }
}

pub fn resolve_still_image_quantization_max_colors(
    compression_mode: OutputCompressionModePayload,
    output_target: StillImageOutputTarget,
) -> Option<u32> {
    if !compression_mode.is_compact() {
        return None;
    }

    Some(match output_target {
        StillImageOutputTarget::EvidenceDecisionArtifact => 224,
        StillImageOutputTarget::FrameExport
        | StillImageOutputTarget::EvidenceSourceFrame
        | StillImageOutputTarget::AiEvidenceKeyframe => 192,
    })
}

fn compact_video_maxrate_kbps(
    width: u32,
    height: u32,
    fps: u32,
    output_target: VideoCompressionTarget,
) -> u32 {
    let longer_side = width.max(height);
    let base_kbps: u32 = match longer_side {
        0..=640 => 300,
        641..=960 => 500,
        961..=1280 => 700,
        1281..=1920 => 1400,
        1921..=2560 => 2200,
        _ => 3200,
    };

    let fps_adjusted = if fps > 30 {
        (base_kbps.saturating_mul(120).saturating_add(99)) / 100
    } else {
        base_kbps
    };

    match output_target {
        VideoCompressionTarget::TimelineExport => fps_adjusted,
        VideoCompressionTarget::AiEvidenceClip => {
            (fps_adjusted.saturating_mul(85).saturating_add(99)) / 100
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compact_timeline_video_settings_are_materially_stronger_than_standard() {
        let standard = resolve_video_compression_settings(
            OutputCompressionModePayload::Standard,
            VideoCompressionTarget::TimelineExport,
            1920,
            1080,
            60,
        );
        let compact = resolve_video_compression_settings(
            OutputCompressionModePayload::Compact,
            VideoCompressionTarget::TimelineExport,
            1920,
            1080,
            60,
        );

        assert_eq!(standard.preset, "medium");
        assert_eq!(compact.preset, "veryslow");
        assert_eq!(standard.crf, 18);
        assert_eq!(compact.crf, 34);
        assert_eq!(compact.gop_size, 600);
        assert_eq!(compact.maxrate_kbps, Some(1680));
        assert_eq!(compact.bufsize_kbps, Some(3360));
    }

    #[test]
    fn compact_ai_clip_uses_target_specific_rate_control() {
        let timeline = resolve_video_compression_settings(
            OutputCompressionModePayload::Compact,
            VideoCompressionTarget::TimelineExport,
            1920,
            1080,
            60,
        );
        let clip = resolve_video_compression_settings(
            OutputCompressionModePayload::Compact,
            VideoCompressionTarget::AiEvidenceClip,
            1920,
            1080,
            60,
        );

        assert_eq!(clip.gop_size, 240);
        assert!(clip.maxrate_kbps.unwrap_or_default() < timeline.maxrate_kbps.unwrap_or_default());
    }

    #[test]
    fn compact_still_image_outputs_enable_quantization() {
        assert_eq!(
            resolve_still_image_quantization_max_colors(
                OutputCompressionModePayload::Compact,
                StillImageOutputTarget::AiEvidenceKeyframe,
            ),
            Some(192)
        );
        assert_eq!(
            resolve_still_image_quantization_max_colors(
                OutputCompressionModePayload::Compact,
                StillImageOutputTarget::EvidenceDecisionArtifact,
            ),
            Some(224)
        );
        assert_eq!(
            resolve_still_image_quantization_max_colors(
                OutputCompressionModePayload::Standard,
                StillImageOutputTarget::FrameExport,
            ),
            None
        );
    }
}