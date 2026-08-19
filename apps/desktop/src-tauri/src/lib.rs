use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{mpsc, Mutex};
use std::thread;
use std::time::Duration;
use tauri::Manager;

const READY_PREFIX: &str = "VAULT_API_READY ";
const MIN_BOOTSTRAP_SECRET_LENGTH: usize = 32;

#[derive(Clone, Debug, Serialize)]
struct ApiRuntimeConfig {
    base_url: String,
    bootstrap_secret: String,
    instance_id: String,
}

#[derive(Debug, Deserialize)]
struct SidecarReady {
    host: String,
    port: u16,
    bootstrap_secret: String,
    instance_id: String,
}

struct ApiSidecar {
    child: Mutex<Option<Child>>,
    config: ApiRuntimeConfig,
}

#[tauri::command]
fn get_api_runtime_config(state: tauri::State<'_, ApiSidecar>) -> ApiRuntimeConfig {
    state.config.clone()
}

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

fn apply_api_env(cmd: &mut Command) {
    // The child owns its socket and generates a fresh bootstrap secret. Never
    // inherit a static secret or a remotely bindable API configuration.
    cmd.env_remove("VAULT_API_BOOTSTRAP_SECRET")
        .env_remove("VAULT_API_INSTANCE_ID")
        .env("VAULT_API_HOST", "127.0.0.1")
        .env("VAULT_API_PORT", "0")
        .env("VAULT_API_ALLOW_REMOTE", "0")
        .env("VAULT_API_DISABLE_DOCS", "1")
        .env("PYTHONUNBUFFERED", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());
}

fn read_sidecar_ready(child: &mut Child, timeout_secs: u64) -> Result<SidecarReady, String> {
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "sidecar stdout pipe was not created".to_string())?;
    let (sender, receiver) = mpsc::sync_channel(1);

    thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();

        loop {
            line.clear();
            match reader.read_line(&mut line) {
                Ok(0) => {
                    let _ = sender.send(Err(
                        "sidecar exited before sending its authenticated runtime handshake"
                            .to_string(),
                    ));
                    return;
                }
                Ok(_) => {
                    let trimmed = line.trim_end_matches(&['\r', '\n'][..]);
                    if let Some(payload) = trimmed.strip_prefix(READY_PREFIX) {
                        let parsed = serde_json::from_str::<SidecarReady>(payload)
                            .map_err(|err| format!("invalid sidecar ready payload: {err}"));
                        let _ = sender.send(parsed);
                        break;
                    }
                    if !trimmed.is_empty() {
                        eprintln!("[vault-api] {trimmed}");
                    }
                }
                Err(err) => {
                    let _ = sender.send(Err(format!("failed reading sidecar stdout: {err}")));
                    return;
                }
            }
        }

        // Keep draining stdout so a noisy child can never block on a full pipe.
        for line in reader.lines() {
            match line {
                Ok(text) if !text.is_empty() => eprintln!("[vault-api] {text}"),
                Ok(_) => {}
                Err(err) => {
                    eprintln!("[vault-unified] sidecar stdout closed with error: {err}");
                    break;
                }
            }
        }
    });

    receiver
        .recv_timeout(Duration::from_secs(timeout_secs))
        .map_err(|_| "timed out waiting for sidecar runtime handshake".to_string())?
}

fn health_ok(ready: &SidecarReady) -> bool {
    if ready.host != "127.0.0.1" || ready.port == 0 {
        return false;
    }
    if ready.bootstrap_secret.len() < MIN_BOOTSTRAP_SECRET_LENGTH
        || ready.instance_id.is_empty()
    {
        return false;
    }

    let address: SocketAddr = match format!("127.0.0.1:{}", ready.port).parse() {
        Ok(value) => value,
        Err(_) => return false,
    };
    let mut stream = match TcpStream::connect_timeout(&address, Duration::from_secs(1)) {
        Ok(value) => value,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));

    let request = format!(
        "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nX-Vault-Bootstrap: {}\r\nConnection: close\r\n\r\n",
        ready.port, ready.bootstrap_secret
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }

    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    let Some((headers, body)) = response.split_once("\r\n\r\n") else {
        return false;
    };
    if !(headers.starts_with("HTTP/1.1 200") || headers.starts_with("HTTP/1.0 200")) {
        return false;
    }

    let payload: serde_json::Value = match serde_json::from_str(body) {
        Ok(value) => value,
        Err(_) => return false,
    };
    payload.get("status").and_then(|value| value.as_str()) == Some("ok")
        && payload
            .get("instance_id")
            .and_then(|value| value.as_str())
            == Some(ready.instance_id.as_str())
}

fn wait_for_health(ready: &SidecarReady, timeout_secs: u64) -> bool {
    let deadline = std::time::Instant::now() + Duration::from_secs(timeout_secs);
    while std::time::Instant::now() < deadline {
        if health_ok(ready) {
            return true;
        }
        thread::sleep(Duration::from_millis(250));
    }
    false
}

fn spawn_api(mut command: Command, label: &str) -> Result<(Child, ApiRuntimeConfig), String> {
    apply_api_env(&mut command);
    let mut child = command
        .spawn()
        .map_err(|err| format!("failed to spawn {label}: {err}"))?;

    let ready = match read_sidecar_ready(&mut child, 20) {
        Ok(value) => value,
        Err(err) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(err);
        }
    };

    if !wait_for_health(&ready, 20) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(
            "sidecar handshake was received, but authenticated health verification failed"
                .to_string(),
        );
    }

    let config = ApiRuntimeConfig {
        base_url: format!("http://127.0.0.1:{}/api", ready.port),
        bootstrap_secret: ready.bootstrap_secret,
        instance_id: ready.instance_id,
    };
    Ok((child, config))
}

fn start_api(resource_dir: Option<PathBuf>) -> Result<(Child, ApiRuntimeConfig), String> {
    let exe = exe_dir();

    if let Some(sidecar) = find_sidecar_binary(&exe, resource_dir.as_deref()) {
        eprintln!("[vault-unified] Starting bundled API sidecar");
        let command = Command::new(&sidecar);
        return spawn_api(command, &format!("sidecar {}", sidecar.display()));
    }

    let root = find_pyproject(&exe, 8).or_else(|| {
        std::env::current_dir()
            .ok()
            .and_then(|cwd| find_pyproject(&cwd, 8))
    });

    let Some(root) = root else {
        return Err(format!(
            "no bundled API sidecar and no pyproject.toml found from {}",
            exe.display()
        ));
    };

    let python = python_exe(&root);
    eprintln!(
        "[vault-unified] Starting development API via Python (cwd {})",
        root.display()
    );
    let mut command = Command::new(&python);
    command
        .args(["-m", "vault_unified.api.app"])
        .current_dir(&root);
    spawn_api(command, &format!("python API {}", python.display()))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![get_api_runtime_config])
        .setup(|app| {
            let resource_dir = app.path().resource_dir().ok();
            let (child, config) = start_api(resource_dir).map_err(|message| {
                std::io::Error::new(std::io::ErrorKind::Other, message)
            })?;
            app.manage(ApiSidecar {
                child: Mutex::new(Some(child)),
                config,
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(state) = app.try_state::<ApiSidecar>() {
                    if let Ok(mut guard) = state.child.lock() {
                        if let Some(mut child) = guard.take() {
                            let _ = child.kill();
                            let _ = child.wait();
                        }
                    }
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::{SidecarReady, READY_PREFIX};

    #[test]
    fn parses_ready_payload_without_logging_secret() {
        let line = format!(
            "{}{}",
            READY_PREFIX,
            r#"{"host":"127.0.0.1","port":54321,"bootstrap_secret":"abcdefghijklmnopqrstuvwxyz123456","instance_id":"instance-1"}"#
        );
        let payload = line.strip_prefix(READY_PREFIX).unwrap();
        let ready: SidecarReady = serde_json::from_str(payload).unwrap();
        assert_eq!(ready.host, "127.0.0.1");
        assert_eq!(ready.port, 54321);
        assert_eq!(ready.instance_id, "instance-1");
    }
}
