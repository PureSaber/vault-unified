use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;
use tauri::Manager;

struct ApiSidecar(Mutex<Option<Child>>);

fn exe_dir() -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()))
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default())
}

fn find_pyproject(start: &Path, max_levels: usize) -> Option<PathBuf> {
    let mut path = start.to_path_buf();
    for _ in 0..=max_levels {
        if path.join("pyproject.toml").exists() {
            return Some(path);
        }
        if !path.pop() {
            break;
        }
    }
    None
}

fn find_sidecar_binary(exe: &Path, resource_dir: Option<&Path>) -> Option<PathBuf> {
    let names = ["vault-api-sidecar.exe", "vault-api-sidecar"];

    for name in &names {
        let candidate = exe.join(name);
        if candidate.exists() {
            return Some(candidate);
        }
    }

    if let Some(rd) = resource_dir {
        for name in &names {
            let candidate = rd.join(name);
            if candidate.exists() {
                return Some(candidate);
            }
        }
    }

    if let Ok(env_path) = std::env::var("VAULT_API_SIDECAR") {
        let candidate = PathBuf::from(env_path);
        if candidate.exists() {
            return Some(candidate);
        }
        eprintln!(
            "[vault-unified] VAULT_API_SIDECAR set but not found: {}",
            candidate.display()
        );
    }

    None
}

fn python_exe(root: &Path) -> PathBuf {
    let venv = root.join(".venv").join("Scripts").join("python.exe");
    if venv.exists() {
        return venv;
    }
    let venv_unix = root.join(".venv").join("bin").join("python");
    if venv_unix.exists() {
        return venv_unix;
    }
    PathBuf::from("python")
}

fn wait_for_health(timeout_secs: u64) -> bool {
    let deadline = std::time::Instant::now() + Duration::from_secs(timeout_secs);
    while std::time::Instant::now() < deadline {
        if health_ok() {
            return true;
        }
        thread::sleep(Duration::from_millis(500));
    }
    false
}

fn health_ok() -> bool {
    let mut stream = match TcpStream::connect_timeout(
        &"127.0.0.1:8765".parse().unwrap(),
        Duration::from_secs(1),
    ) {
        Ok(s) => s,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
    let req = b"GET /api/auth/check-keyring HTTP/1.1\r\nHost: 127.0.0.1:8765\r\nConnection: close\r\n\r\n";
    if stream.write_all(req).is_err() {
        return false;
    }
    let mut buf = [0u8; 512];
    match stream.read(&mut buf) {
        Ok(n) if n > 0 => {
            let text = String::from_utf8_lossy(&buf[..n]);
            text.contains("200") || text.contains("has_saved_password")
        }
        _ => false,
    }
}

fn apply_api_env(cmd: &mut Command) {
    cmd.env("VAULT_API_HOST", "127.0.0.1")
        .env("VAULT_API_PORT", "8765")
        .env("VAULT_API_DISABLE_DOCS", "1");
}

fn start_api(resource_dir: Option<PathBuf>) -> Option<Child> {
    if health_ok() {
        eprintln!("[vault-unified] API already healthy on 127.0.0.1:8765");
        return None;
    }

    let exe = exe_dir();

    if let Some(sidecar) = find_sidecar_binary(&exe, resource_dir.as_deref()) {
        eprintln!("[vault-unified] Starting API sidecar: {}", sidecar.display());
        let mut cmd = Command::new(&sidecar);
        apply_api_env(&mut cmd);
        match cmd.spawn() {
            Ok(child) => {
                if wait_for_health(20) {
                    return Some(child);
                }
                eprintln!("[vault-unified] Sidecar spawned but health check failed");
                return Some(child);
            }
            Err(err) => {
                eprintln!(
                    "[vault-unified] Failed to spawn sidecar {}: {err}",
                    sidecar.display()
                );
            }
        }
    }

    let root = find_pyproject(&exe, 8)
        .or_else(|| {
            std::env::current_dir()
                .ok()
                .and_then(|cwd| find_pyproject(&cwd, 8))
        });

    let Some(root) = root else {
        eprintln!(
            "[vault-unified] No API sidecar and no pyproject.toml found (searched from {})",
            exe.display()
        );
        return None;
    };

    let python = python_exe(&root);
    eprintln!(
        "[vault-unified] Starting API via {} -m vault_unified.api.app (cwd {})",
        python.display(),
        root.display()
    );
    let mut cmd = Command::new(&python);
    cmd.args(["-m", "vault_unified.api.app"])
        .current_dir(&root);
    apply_api_env(&mut cmd);

    match cmd.spawn() {
        Ok(child) => {
            if !wait_for_health(20) {
                eprintln!("[vault-unified] Python API spawned but health check timed out");
            }
            Some(child)
        }
        Err(err) => {
            eprintln!(
                "[vault-unified] Failed to spawn python API ({}): {err}",
                python.display()
            );
            None
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let resource_dir = app.path().resource_dir().ok();
            let child = start_api(resource_dir);
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
