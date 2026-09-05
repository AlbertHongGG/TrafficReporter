// Tauri Commands
pub mod lpr_commands;
pub mod workspace_commands;
pub mod media_commands;

pub fn create_builder() -> tauri_specta::Builder<tauri::Wry> {
    tauri_specta::Builder::<tauri::Wry>::new()
        .commands(tauri_specta::collect_commands![
            workspace_commands::get_app_state,
            workspace_commands::workspace_add_files,
            workspace_commands::workspace_remove_file,
            workspace_commands::workspace_set_active_file,
            workspace_commands::workspace_move_clip,
            workspace_commands::workspace_trim_clip_start,
            workspace_commands::workspace_trim_clip_end,
            workspace_commands::workspace_split_clip,
            workspace_commands::workspace_delete_clips,
            workspace_commands::workspace_set_clips_muted,
            workspace_commands::workspace_set_render_profile,
            lpr_commands::get_lpr_runtime_status,
            lpr_commands::cancel_lpr_runtime_job,
            lpr_commands::scan_lpr_targets,
            lpr_commands::analyze_lpr_frame,
            lpr_commands::analyze_lpr_interval,
            lpr_commands::analyze_ai_evidence,
            media_commands::probe_media_source,
            media_commands::save_generated_media_asset,
            media_commands::export_frame_image,
            media_commands::export_lpr_evidence,
            media_commands::process_timeline_export,
        ])
}
