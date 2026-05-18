mod app;
mod contracts;
mod downloader;
mod editor;
mod export;
mod platform;

use std::sync::Mutex;

use app::AppState;
use downloader::{download_youtube, get_youtube_info};
use editor::{
	analyze_ai_evidence, analyze_lpr_frame, analyze_lpr_interval, cancel_lpr_runtime_job, export_frame_image,
	export_lpr_evidence, get_lpr_runtime_status, probe_media_source, scan_lpr_targets,
};
use export::{get_pending_export_session, process_timeline_export, set_pending_export_session};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
	tauri::Builder::default()
		.manage(AppState {
			pending_export_snapshot: Mutex::new(None),
		})
		.plugin(tauri_plugin_shell::init())
		.plugin(tauri_plugin_dialog::init())
		.invoke_handler(tauri::generate_handler![
			get_youtube_info,
			download_youtube,
			probe_media_source,
			analyze_ai_evidence,
			export_frame_image,
			export_lpr_evidence,
			cancel_lpr_runtime_job,
			get_lpr_runtime_status,
			scan_lpr_targets,
			analyze_lpr_frame,
			analyze_lpr_interval,
			set_pending_export_session,
			get_pending_export_session,
			process_timeline_export
		])
		.setup(|app| {
			if cfg!(debug_assertions) {
				app.handle().plugin(
					tauri_plugin_log::Builder::default()
						.level(log::LevelFilter::Info)
						.build(),
				)?;
			}
			Ok(())
		})
		.run(tauri::generate_context!())
		.expect("error while running tauri application");
}
