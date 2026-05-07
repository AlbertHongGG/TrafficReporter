use std::path::PathBuf;
use std::process::{Command, Stdio};

const LPR_RUNTIME_DIR_NAME: &str = "traffic-lpr-runtime";

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

#[derive(Debug, Clone)]
pub struct ResolvedCommand {
    pub program: String,
    pub args: Vec<String>,
}

fn can_execute(program: &str, args: &[String]) -> bool {
    let mut command = hidden_command(program);
    for arg in args {
        command.arg(arg);
    }

    command
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .is_ok()
}

fn candidate_lpr_runtime_roots() -> Vec<PathBuf> {
    let mut roots = Vec::new();

    for env_key in ["TRAFFIC_LPR_RUNTIME_DIR", "TRAFFIC_LPR_SIDECAR_DIR"] {
        if let Ok(custom_root) = std::env::var(env_key) {
            let custom_root = custom_root.trim();
            if !custom_root.is_empty() {
                roots.push(PathBuf::from(custom_root));
            }
        }
    }

    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(dir) = exe_path.parent() {
            roots.push(dir.join(LPR_RUNTIME_DIR_NAME));

            if let Some(parent) = dir.parent() {
                roots.push(parent.join(LPR_RUNTIME_DIR_NAME));

                if let Some(grand_parent) = parent.parent() {
                    roots.push(grand_parent.join(LPR_RUNTIME_DIR_NAME));
                }
            }
        }
    }

    if let Ok(manifest_dir) = std::env::var("CARGO_MANIFEST_DIR") {
        let manifest_dir = PathBuf::from(manifest_dir);
        if let Some(workspace_root) = manifest_dir.parent() {
            roots.push(workspace_root.join(LPR_RUNTIME_DIR_NAME));
        }
    }

    roots
}

pub fn find_lpr_runtime_root() -> Result<PathBuf, String> {
    for root in candidate_lpr_runtime_roots() {
        if root.join("pyproject.toml").exists() {
            return Ok(root);
        }

        let candidate = root.join("traffic_lpr_runtime").join("__main__.py");
        if candidate.exists() {
            return Ok(root);
        }
    }

    Err(format!(
        "LPR runtime project not found. Expected {}/ in the workspace, next to the bundled executable, or via TRAFFIC_LPR_RUNTIME_DIR.",
        LPR_RUNTIME_DIR_NAME
    ))
}

pub fn find_python_runtime() -> Result<ResolvedCommand, String> {
    if let Ok(custom_python) = std::env::var("TRAFFIC_LPR_PYTHON") {
        if !custom_python.trim().is_empty() && can_execute(&custom_python, &[]) {
            return Ok(ResolvedCommand {
                program: custom_python,
                args: Vec::new(),
            });
        }
    }

    for root in candidate_lpr_runtime_roots() {
        let windows_candidate = root.join(".venv").join("Scripts").join("python.exe");
        if windows_candidate.exists() {
            return Ok(ResolvedCommand {
                program: windows_candidate.to_string_lossy().to_string(),
                args: Vec::new(),
            });
        }

        let unix_candidate = root.join(".venv").join("bin").join("python");
        if unix_candidate.exists() {
            return Ok(ResolvedCommand {
                program: unix_candidate.to_string_lossy().to_string(),
                args: Vec::new(),
            });
        }
    }

    let candidates = [
        ResolvedCommand {
            program: "python".to_string(),
            args: Vec::new(),
        },
        ResolvedCommand {
            program: "python3".to_string(),
            args: Vec::new(),
        },
        ResolvedCommand {
            program: "py".to_string(),
            args: vec!["-3".to_string()],
        },
    ];

    for candidate in candidates {
        if can_execute(&candidate.program, &candidate.args) {
            return Ok(candidate);
        }
    }

    Err(
        format!(
            "Python runtime not found. Create {}/.venv, set TRAFFIC_LPR_PYTHON, or point TRAFFIC_LPR_RUNTIME_DIR at a prepared runtime project.",
            LPR_RUNTIME_DIR_NAME
        ),
    )
}