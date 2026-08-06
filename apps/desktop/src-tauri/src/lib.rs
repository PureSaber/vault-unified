use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::Manager;

struct ApiSidecar(Mutex<Option<Child>>);

fn project_root() -> PathBuf {
    let mut path = std::env::current_exe().unwrap_or_default();
    for _ in 0..6 {
        if path.join("pyproject.toml").exists() {
            return path;
        }
        if !path.pop() {
            break;
        }
    }
    PathBuf::from(r"C:\develop\token&password")
}

fn python_exe(root: &PathBuf) -> PathBuf {
    let venv = root.join(".venv").join("Scripts").join("python.exe");
    if venv.exists() {
        return venv;
    }
    PathBuf::from("python")
}

fn start_api(root: &PathBuf) -> Option<Child> {
    let python = python_exe(root);
    Command::new(python)
        .args(["-m", "vault_unified.api.app"])
        .current_dir(root)
        .env("VAULT_API_PORT", "8765")
        .env("VAULT_API_HOST", "127.0.0.1")
        .spawn()
        .ok()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let root = project_root();
            let child = start_api(&root);
            app.manage(ApiSidecar(Mutex::new(child)));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(state) = app.try_state::<ApiSidecar>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(mut child) = guard.take() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        });
}
