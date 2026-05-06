use std::io::{BufRead, BufReader};
use std::process::Stdio;
use std::sync::mpsc;

use tauri::{AppHandle, Emitter};

use crate::contracts::{DownloadProgressPayload, VideoInfo};
use crate::platform::process::{find_bundled, hidden_command};

#[derive(Debug)]
struct YtdlpProgress {
    percent: f64,
    size: String,
    speed: String,
    eta: String,
}

fn parse_ytdlp_progress(line: &str) -> Option<YtdlpProgress> {
    if !line.contains("[download]") && !line.contains("[progress]") {
        return None;
    }

    let trimmed = line.trim();
    let parts: Vec<&str> = trimmed.split_whitespace().collect();

    let mut percent: Option<f64> = None;
    let mut size = String::new();
    let mut speed = String::new();
    let mut eta = String::new();

    for (index, part) in parts.iter().enumerate() {
        if part.ends_with('%') {
            if let Ok(value) = part.trim_end_matches('%').parse::<f64>() {
                percent = Some(value);
            }
        }
        if *part == "of" {
            if let Some(value) = parts.get(index + 1) {
                size = value.trim_start_matches('~').to_string();
            }
        }
        if *part == "at" {
            if let Some(value) = parts.get(index + 1) {
                speed = value.to_string();
            }
        }
        if *part == "ETA" {
            if let Some(value) = parts.get(index + 1) {
                eta = value.to_string();
            }
        }
    }

    percent.map(|progress| YtdlpProgress {
        percent: progress,
        size,
        speed,
        eta,
    })
}

fn detect_phase(line: &str) -> Option<String> {
    let trimmed = line.trim();
    if trimmed.starts_with("[download] Destination:") {
        if trimmed.contains(".f") || trimmed.contains("video") {
            return Some("downloading_video".to_string());
        }
        return Some("downloading".to_string());
    }
    if trimmed.starts_with("[Merger]") || trimmed.starts_with("[Merge]") || trimmed.contains("Merging") {
        return Some("merging".to_string());
    }
    if trimmed.starts_with("[ExtractAudio]") || trimmed.starts_with("[ffmpeg]") {
        return Some("converting".to_string());
    }
    if trimmed.starts_with("[download] 100%") {
        return Some("finalizing".to_string());
    }
    None
}

fn build_status_text(phase: &str, progress: &YtdlpProgress) -> String {
    let mut parts: Vec<String> = Vec::new();

    if !progress.size.is_empty() && progress.size != "NA" {
        parts.push(progress.size.clone());
    }
    if !progress.speed.is_empty() && progress.speed != "NA" {
        parts.push(progress.speed.clone());
    }
    if !progress.eta.is_empty() && progress.eta != "NA" {
        parts.push(format!("ETA {}", progress.eta));
    }

    let phase_label = match phase {
        "downloading_video" => "Downloading",
        "downloading" => "Downloading",
        "merging" => "Merging",
        "converting" => "Converting",
        "finalizing" => "Finalizing",
        _ => "Downloading",
    };

    if parts.is_empty() {
        format!("{}...", phase_label)
    } else {
        format!("{}  •  {}", phase_label, parts.join("  •  "))
    }
}

#[tauri::command]
pub async fn get_youtube_info(url: String) -> Result<VideoInfo, String> {
    let ytdlp = find_bundled("yt-dlp")?;

    let output = hidden_command(&ytdlp)
        .args([
            "--dump-json",
            "--no-playlist",
            "--force-ipv4",
            "--encoding",
            "utf-8",
            &url,
        ])
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUTF8", "1")
        .output()
        .map_err(|error| format!("Failed to execute yt-dlp: {}", error))?;

    if !output.status.success() {
        let error = String::from_utf8_lossy(&output.stderr);
        return Err(format!("yt-dlp error: {}", error));
    }

    let json_str = String::from_utf8_lossy(&output.stdout);
    let value: serde_json::Value = serde_json::from_str(&json_str)
        .map_err(|error| format!("Failed to parse JSON: {}", error))?;

    Ok(VideoInfo {
        title: value["title"].as_str().unwrap_or("Unknown").to_string(),
        thumbnail: value["thumbnail"].as_str().unwrap_or("").to_string(),
        duration: value["duration"].as_u64().unwrap_or(0) as u32,
    })
}

#[tauri::command]
pub async fn download_youtube(
    app: AppHandle,
    url: String,
    format: String,
    quality: String,
    save_dir: String,
) -> Result<(), String> {
    let ytdlp = find_bundled("yt-dlp")?;
    let output_template = format!(
        "{}{}%(title)s.%(ext)s",
        save_dir,
        if save_dir.ends_with('\\') || save_dir.ends_with('/') {
            ""
        } else {
            "\\"
        }
    );

    let mut args = vec![
        "--no-playlist".to_string(),
        "--newline".to_string(),
        "--progress".to_string(),
        "--force-ipv4".to_string(),
        "--encoding".to_string(),
        "utf-8".to_string(),
        "--progress-template".to_string(),
        "[progress] %(progress._percent_str)s of %(progress._total_bytes_str)s at %(progress._speed_str)s ETA %(progress._eta_str)s".to_string(),
        "--windows-filenames".to_string(),
        "-o".to_string(),
        output_template,
    ];

    let is_video = format == "mp4" || format == "mkv" || format == "webm";
    if is_video {
        args.push("-f".to_string());
        let quality_clean = quality.split_whitespace().next().unwrap_or(&quality);
        let height = match quality_clean {
            "2160p" => 2160,
            "1440p" => 1440,
            "1080p" => 1080,
            "720p" => 720,
            "480p" => 480,
            "360p" => 360,
            _ => 1080,
        };
        args.push(format!("bestvideo[height<={}]+bestaudio/best[height<={}]", height, height));
        args.push("--merge-output-format".to_string());
        args.push(format.clone());
    } else {
        args.push("-x".to_string());
        args.push("--audio-format".to_string());
        args.push(format.clone());
        let abr = match quality.as_str() {
            "320kbps" => "320",
            "256kbps" => "256",
            "192kbps" => "192",
            "128kbps" => "128",
            "64kbps" => "64",
            _ => "192",
        };
        args.push("--audio-quality".to_string());
        args.push(abr.to_string());
    }

    args.push(url);

    let mut child = hidden_command(&ytdlp)
        .args(&args)
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUTF8", "1")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("Failed to execute yt-dlp: {}", error))?;

    let (sender, receiver) = mpsc::channel::<(String, bool)>();
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();

    let stdout_sender = sender.clone();
    let stdout_handle = std::thread::spawn(move || {
        if let Some(stdout) = stdout {
            let reader = BufReader::new(stdout);
            for line in reader.lines().map_while(Result::ok) {
                if stdout_sender.send((line, false)).is_err() {
                    break;
                }
            }
        }
    });

    let stderr_sender = sender;
    let stderr_handle = std::thread::spawn(move || {
        if let Some(stderr) = stderr {
            let reader = BufReader::new(stderr);
            for line in reader.lines().map_while(Result::ok) {
                if stderr_sender.send((line, true)).is_err() {
                    break;
                }
            }
        }
    });

    let mut current_phase = if is_video {
        "downloading_video".to_string()
    } else {
        "downloading".to_string()
    };

    let _ = app.emit(
        "download-progress",
        DownloadProgressPayload {
            percent: 0.0,
            status: "downloading".to_string(),
            status_text: "Starting download...".to_string(),
            phase: current_phase.clone(),
        },
    );

    let mut last_error = String::new();

    for (line, is_stderr) in receiver {
        if is_stderr && (line.contains("ERROR:") || line.contains("ffmpeg") || line.contains("error")) {
            last_error = line.clone();
        }

        if let Some(phase) = detect_phase(&line) {
            current_phase = phase;
            let phase_text = match current_phase.as_str() {
                "merging" => "Merging video and audio...".to_string(),
                "converting" => "Converting audio format...".to_string(),
                "finalizing" => "Finalizing...".to_string(),
                _ => String::new(),
            };
            if !phase_text.is_empty() {
                let _ = app.emit(
                    "download-progress",
                    DownloadProgressPayload {
                        percent: 99.0,
                        status: "processing".to_string(),
                        status_text: phase_text,
                        phase: current_phase.clone(),
                    },
                );
            }
        }

        if let Some(progress) = parse_ytdlp_progress(&line) {
            let _ = app.emit(
                "download-progress",
                DownloadProgressPayload {
                    percent: progress.percent,
                    status: if progress.percent >= 100.0 {
                        "done".to_string()
                    } else {
                        "downloading".to_string()
                    },
                    status_text: build_status_text(&current_phase, &progress),
                    phase: current_phase.clone(),
                },
            );
        }
    }

    let _ = stdout_handle.join();
    let _ = stderr_handle.join();

    let status = child
        .wait()
        .map_err(|error| format!("Failed to wait on yt-dlp: {}", error))?;
    if !status.success() {
        let display_error = if last_error.is_empty() {
            "Download failed. Please check your internet connection or URL.".to_string()
        } else {
            last_error.clone()
        };

        let _ = app.emit(
            "download-progress",
            DownloadProgressPayload {
                percent: 0.0,
                status: "error".to_string(),
                status_text: display_error.clone(),
                phase: "error".to_string(),
            },
        );
        return Err(format!("yt-dlp failed: {}", display_error));
    }

    let _ = app.emit(
        "download-progress",
        DownloadProgressPayload {
            percent: 100.0,
            status: "done".to_string(),
            status_text: "Download complete!".to_string(),
            phase: "done".to_string(),
        },
    );

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_progress_template_output() {
        let parsed = parse_ytdlp_progress("[progress] 12.5% of 10.00MiB at 1.00MiB ETA 00:10")
            .expect("progress should parse");
        assert_eq!(parsed.percent, 12.5);
        assert_eq!(parsed.size, "10.00MiB");
        assert_eq!(parsed.speed, "1.00MiB");
        assert_eq!(parsed.eta, "00:10");
    }

    #[test]
    fn detects_merge_phase() {
        assert_eq!(detect_phase("[Merger] Merging formats into file"), Some("merging".to_string()));
    }
}