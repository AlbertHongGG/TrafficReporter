use std::path::PathBuf;

use crate::platform::process::find_lpr_runtime_root;

fn runtime_data_root() -> Result<PathBuf, String> {
    let runtime_root = find_lpr_runtime_root()?;
    let repo_root = runtime_root
        .parent()
        .ok_or_else(|| "Failed to resolve the repository root for runtime artifacts.".to_string())?;
    Ok(repo_root.join(".runtime"))
}

pub fn runtime_run_root(run_id: &str) -> Result<PathBuf, String> {
    Ok(runtime_data_root()?.join("runs").join(run_id))
}
