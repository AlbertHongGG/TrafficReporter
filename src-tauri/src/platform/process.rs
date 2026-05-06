use std::path::PathBuf;
use std::process::{Command, Stdio};

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[cfg(target_os = "windows")]
pub fn hidden_command(program: &str) -> Command {
    const CREATE_NO_WINDOW: u32 = 0x08000000;
    let mut cmd = Command::new(program);
    cmd.creation_flags(CREATE_NO_WINDOW);
    cmd
}

#[cfg(not(target_os = "windows"))]
pub fn hidden_command(program: &str) -> Command {
    Command::new(program)
}

pub fn find_bundled(name: &str) -> Result<String, String> {
    let exe_name = format!("{}.exe", name);

    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(dir) = exe_path.parent() {
            let candidate = dir.join("bin").join(&exe_name);
            if candidate.exists() {
                return Ok(candidate.to_string_lossy().to_string());
            }

            let candidate = dir.join(&exe_name);
            if candidate.exists() {
                return Ok(candidate.to_string_lossy().to_string());
            }
        }
    }

    if let Ok(manifest_dir) = std::env::var("CARGO_MANIFEST_DIR") {
        let candidate = PathBuf::from(&manifest_dir).join("bin").join(&exe_name);
        if candidate.exists() {
            return Ok(candidate.to_string_lossy().to_string());
        }
    }

    if hidden_command(name)
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .is_ok()
    {
        return Ok(name.to_string());
    }

    Err(format!(
        "{} not found. Expected it in src-tauri/bin/{} or in system PATH.",
        name, exe_name
    ))
}