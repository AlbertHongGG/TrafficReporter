mod contracts;
mod editor;
mod export;
mod media;
mod platform;

mod domain;
mod infrastructure;
mod application;
mod commands;

use tauri::Manager;
use editor::{
    export_frame_image,
    export_lpr_evidence, probe_media_source, save_generated_media_asset,
};
use commands::lpr_commands::{
    get_lpr_runtime_status, cancel_lpr_runtime_job,
    scan_lpr_targets, analyze_lpr_frame, analyze_lpr_interval, analyze_ai_evidence
};
use commands::workspace_commands::{
    get_app_state, workspace_add_files, workspace_remove_file, workspace_set_active_file,
    workspace_move_clip, workspace_trim_clip_start, workspace_trim_clip_end,
    workspace_split_clip, workspace_delete_clips, workspace_set_clips_muted,
    workspace_set_render_profile
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
			process_timeline_export,
			get_app_state,
            workspace_add_files,
            workspace_remove_file,
            workspace_set_active_file,
            workspace_move_clip,
            workspace_trim_clip_start,
            workspace_trim_clip_end,
            workspace_split_clip,
            workspace_delete_clips,
            workspace_set_clips_muted,
            workspace_set_render_profile
		])
		.setup(|app| {
			if cfg!(debug_assertions) {
				app.handle().plugin(
					tauri_plugin_log::Builder::default()
						.level(log::LevelFilter::Info)
						.build(),
				)?;
			}
			app.manage(infrastructure::state::AppState::new());
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
