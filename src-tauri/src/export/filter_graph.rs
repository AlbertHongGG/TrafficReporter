use std::collections::{HashMap, HashSet};

use crate::contracts::{ExportSource, TimelineClipPayload, TimelineExportRequest};

use super::dimensions::resolved_video_dimensions;

pub(crate) fn seconds_from_ms(value: f64) -> String {
    format!("{:.3}", value / 1000.0)
}

pub(crate) fn build_filter_graph(request: &TimelineExportRequest, export_fps: u32) -> Result<(Vec<String>, String, Option<String>), String> {
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

    let total_ms = snapshot.timeline_duration_ms.max(1000.0);
    let total_seconds = seconds_from_ms(total_ms);
    let (width, height) = resolved_video_dimensions(request).unwrap_or((0, 0));

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
                export_fps.max(1)
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
        video_clips.sort_by(|a, b| {
            let order_a = track_order_map.get(a.track_id.as_str()).copied().unwrap_or_default();
            let order_b = track_order_map.get(b.track_id.as_str()).copied().unwrap_or_default();
            order_a.cmp(&order_b).then_with(|| {
                a.start_ms.partial_cmp(&b.start_ms).unwrap_or(std::cmp::Ordering::Equal)
            })
        });

        for (index, clip) in video_clips.iter().enumerate() {
            let input_index = source_input_indices
                .get(clip.asset_id.as_str())
                .ok_or_else(|| "Missing ffmpeg input index for video clip.".to_string())?;
            let clip_label = format!("vclip{}", index);
            let next_label = format!("vbase{}", index + 1);
            let clip_end_ms = clip.start_ms + (clip.out_point_ms - clip.in_point_ms).max(0.0);

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
    audio_clips.sort_by(|a, b| {
        let order_a = track_order_map.get(a.track_id.as_str()).copied().unwrap_or_default();
        let order_b = track_order_map.get(b.track_id.as_str()).copied().unwrap_or_default();
        order_a.cmp(&order_b).then_with(|| {
            a.start_ms.partial_cmp(&b.start_ms).unwrap_or(std::cmp::Ordering::Equal)
        })
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
            delay = clip.start_ms.round() as u64,
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
