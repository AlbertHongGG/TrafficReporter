pub mod contracts;
pub mod editor;
pub mod export;
pub mod media;
pub mod platform;

pub mod domain;
pub mod infrastructure;
pub mod application;
pub mod commands;
pub mod ai;
pub mod events;

pub use commands::create_builder;

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = commands::create_builder();

	let app = tauri::Builder::default()
		.plugin(tauri_plugin_shell::init())
		.plugin(tauri_plugin_dialog::init())
		.invoke_handler(builder.invoke_handler())
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
