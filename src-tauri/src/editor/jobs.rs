use crate::infrastructure::python_client::terminate_lpr_runtime_process;

pub(crate) fn terminate_runtime_for_app_exit(
    app_handle: &tauri::AppHandle,
) -> Result<bool, String> {
    terminate_lpr_runtime_process(app_handle, "app-exit")
}
