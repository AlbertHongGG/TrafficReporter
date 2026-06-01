mod contracts;
mod editor;
mod export;
mod media;
mod platform;
use editor::{
	analyze_ai_evidence, analyze_lpr_frame, analyze_lpr_interval, cancel_lpr_runtime_job, export_frame_image,
	export_lpr_evidence, get_lpr_runtime_status, probe_media_source, save_generated_media_asset,
	scan_lpr_targets,
};
use export::process_timeline_export;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
	let app = tauri::Builder::default()
		.plugin(tauri_plugin_shell::init())
		.plugin(tauri_plugin_dialog::init())
		.invoke_handler(tauri::generate_handler![
			probe_media_source,
			analyze_ai_evidence,
			export_frame_image,
			export_lpr_evidence,
			save_generated_media_asset,
			cancel_lpr_runtime_job,
			get_lpr_runtime_status,
			scan_lpr_targets,
			analyze_lpr_frame,
			analyze_lpr_interval,
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
		.build(tauri::generate_context!())
		.expect("error while building tauri application");

	app.run(|app_handle, event| {
		if let tauri::RunEvent::Exit = event {
			let _ = editor::terminate_runtime_for_app_exit(app_handle);
		}
	});
}
