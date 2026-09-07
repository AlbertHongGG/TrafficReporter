use crate::contracts::RenderProfilePayload;
use crate::media::{
    append_h264_aac_codec_args, resolve_audio_bitrate_kbps,
    resolve_video_compression_settings, VideoCompressionTarget,
};

pub(crate) fn codec_args_for_profile(profile: &RenderProfilePayload, video_dimensions: Option<(u32, u32)>, export_fps: u32) -> Vec<String> {
    let format = profile.format.to_lowercase();
    let bitrate = resolve_audio_bitrate_kbps(profile.audio_bitrate_kbps);
    let (width, height) = video_dimensions.unwrap_or((1280, 720));
    let settings = resolve_video_compression_settings(
        profile.compression_mode,
        VideoCompressionTarget::TimelineExport,
        width,
        height,
        export_fps.max(1),
    );

    match format.as_str() {
        "mp4" => {
            let mut args = Vec::new();
            append_h264_aac_codec_args(&mut args, settings, bitrate, true);
            args
        }
        "mkv" => {
            let mut args = Vec::new();
            append_h264_aac_codec_args(&mut args, settings, bitrate, false);
            args
        }
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
        _ => {
            let mut args = Vec::new();
            append_h264_aac_codec_args(&mut args, settings, bitrate, true);
            args
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compact_profile_prefers_smaller_x264_settings() {
        let args = codec_args_for_profile(&RenderProfilePayload {
            format: "mp4".to_string(),
            fps: 60,
            video_quality: Some("1080p".to_string()),
            audio_bitrate_kbps: Some(320),
            compression_mode: crate::contracts::OutputCompressionModePayload::Compact,
        }, Some((1920, 1080)), 60);

        assert!(args.windows(2).any(|window| window == ["-preset", "veryslow"]));
        assert!(args.windows(2).any(|window| window == ["-crf", "34"]));
        assert!(args.windows(2).any(|window| window == ["-b:a", "320k"]));
        assert!(args.windows(2).any(|window| window == ["-g", "600"]));
        assert!(args.windows(2).any(|window| window == ["-bf", "4"]));
        assert!(args.windows(2).any(|window| window == ["-maxrate", "1680k"]));
        assert!(args.windows(2).any(|window| window == ["-bufsize", "3360k"]));
    }
}
