use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{mpsc, Mutex};
use std::thread;
use std::time::Duration;
use tauri::Manager;

#[cfg(windows)]
use std::os::windows::io::AsRawHandle;
#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
use windows_sys::Win32::Foundation::{CloseHandle, HANDLE, INVALID_HANDLE_VALUE};
#[cfg(windows)]
use windows_sys::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Thread32First, Thread32Next, TH32CS_SNAPTHREAD, THREADENTRY32,
};
#[cfg(windows)]
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
    SetInformationJobObject, TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};
#[cfg(windows)]
use windows_sys::Win32::System::Threading::{
    OpenThread, ResumeThread, CREATE_SUSPENDED, THREAD_SUSPEND_RESUME,
};

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
    job: Mutex<Option<SidecarJob>>,
    config: ApiRuntimeConfig,
}

#[cfg(windows)]
struct SidecarJob {
    handle: isize,
}

#[cfg(not(windows))]
struct SidecarJob;

#[cfg(windows)]
impl SidecarJob {
    fn create() -> Result<Self, String> {
        let handle = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
        if handle.is_null() {
            return Err(format!(
                "failed to create sidecar job object: {}",
                std::io::Error::last_os_error()
            ));
        }

        let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let configured = unsafe {
            SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                &limits as *const _ as *const core::ffi::c_void,
                std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            )
        };
        if configured == 0 {
            let err = std::io::Error::last_os_error();
            unsafe {
                CloseHandle(handle);
            }
            return Err(format!("failed to configure sidecar job object: {err}"));
        }

        Ok(Self {
            handle: handle as isize,
        })
    }

    fn raw(&self) -> HANDLE {
        self.handle as HANDLE
    }

    fn assign(&self, child: &Child) -> Result<(), String> {
        let assigned =
            unsafe { AssignProcessToJobObject(self.raw(), child.as_raw_handle() as HANDLE) };
        if assigned == 0 {
            return Err(format!(
                "failed to assign sidecar to job object: {}",
                std::io::Error::last_os_error()
            ));
        }
        Ok(())
    }

    fn terminate(&self) {
        unsafe {
            TerminateJobObject(self.raw(), 1);
        }
    }
}

#[cfg(not(windows))]
impl SidecarJob {
    fn terminate(&self) {}
}

#[cfg(windows)]
impl Drop for SidecarJob {
    fn drop(&mut self) {
        if self.handle != 0 {
            unsafe {
                CloseHandle(self.raw());
            }
            self.handle = 0;
        }
    }
}

#[cfg(windows)]
fn resume_suspended_process(process_id: u32) -> Result<(), String> {
    let snapshot = unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0) };
    if snapshot == INVALID_HANDLE_VALUE {
        return Err(format!(
            "failed to enumerate suspended sidecar threads: {}",
            std::io::Error::last_os_error()
        ));
    }

    let result = (|| {
        let mut entry = THREADENTRY32::default();
        entry.dwSize = std::mem::size_of::<THREADENTRY32>() as u32;
        let mut found = unsafe { Thread32First(snapshot, &mut entry) } != 0;
        while found {
            if entry.th32OwnerProcessID == process_id {
                let thread = unsafe { OpenThread(THREAD_SUSPEND_RESUME, 0, entry.th32ThreadID) };
                if thread.is_null() {
                    return Err(format!(
                        "failed to open suspended sidecar thread: {}",
                        std::io::Error::last_os_error()
                    ));
                }
                let resumed = unsafe { ResumeThread(thread) };
                unsafe {
                    CloseHandle(thread);
                }
                if resumed == u32::MAX {
                    return Err(format!(
                        "failed to resume sidecar process: {}",
                        std::io::Error::last_os_error()
                    ));
                }
                return Ok(());
            }
            found = unsafe { Thread32Next(snapshot, &mut entry) } != 0;
        }
        Err("suspended sidecar primary thread was not found".to_string())
    })();

    unsafe {
        CloseHandle(snapshot);
    }
    result
}

fn spawn_sidecar_process(
    mut command: Command,
    label: &str,
) -> Result<(Child, Option<SidecarJob>), String> {
    #[cfg(windows)]
    {
        // PyInstaller one-file executables spawn a worker process. Create the
        // direct child suspended, assign it to a kill-on-close Job Object, and
        // only then resume it so every descendant inherits the job boundary.
        let job = SidecarJob::create()?;
        command.creation_flags(CREATE_SUSPENDED);
        let mut child = command
            .spawn()
            .map_err(|err| format!("failed to spawn {label}: {err}"))?;
        if let Err(err) = job
            .assign(&child)
            .and_then(|_| resume_suspended_process(child.id()))
        {
            job.terminate();
            let _ = child.kill();
            let _ = child.wait();
            return Err(err);
        }
        return Ok((child, Some(job)));
    }

    #[cfg(not(windows))]
    {
        let child = command
            .spawn()
            .map_err(|err| format!("failed to spawn {label}: {err}"))?;
        Ok((child, None))
    }
}

fn terminate_sidecar(child: &mut Child, job: &mut Option<SidecarJob>) {
    if let Some(owned_job) = job.as_ref() {
        owned_job.terminate();
    }
    let _ = child.kill();
    let _ = child.wait();
    job.take();
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
    if ready.bootstrap_secret.len() < MIN_BOOTSTRAP_SECRET_LENGTH || ready.instance_id.is_empty() {
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
        && payload.get("instance_id").and_then(|value| value.as_str())
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

fn spawn_api(
    mut command: Command,
    label: &str,
) -> Result<(Child, ApiRuntimeConfig, Option<SidecarJob>), String> {
    apply_api_env(&mut command);
    let (mut child, mut job) = spawn_sidecar_process(command, label)?;

    let ready = match read_sidecar_ready(&mut child, 20) {
        Ok(value) => value,
        Err(err) => {
            terminate_sidecar(&mut child, &mut job);
            return Err(err);
        }
    };

    if !wait_for_health(&ready, 20) {
        terminate_sidecar(&mut child, &mut job);
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
    Ok((child, config, job))
}

fn start_api(
    resource_dir: Option<PathBuf>,
) -> Result<(Child, ApiRuntimeConfig, Option<SidecarJob>), String> {
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

fn shutdown_api_sidecar(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<ApiSidecar>() {
        let mut owned_job = state.job.lock().ok().and_then(|mut guard| guard.take());
        if let Some(job) = owned_job.as_ref() {
            job.terminate();
        }
        if let Ok(mut guard) = state.child.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
        owned_job.take();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![get_api_runtime_config])
        .setup(|app| {
            let resource_dir = app.path().resource_dir().ok();
            let (child, config, job) = start_api(resource_dir)
                .map_err(|message| std::io::Error::new(std::io::ErrorKind::Other, message))?;
            app.manage(ApiSidecar {
                child: Mutex::new(Some(child)),
                job: Mutex::new(job),
                config,
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| match event {
            tauri::RunEvent::WindowEvent {
                label,
                event: tauri::WindowEvent::Destroyed,
                ..
            } if label == "main" => {
                shutdown_api_sidecar(app);
                app.exit(0);
            }
            tauri::RunEvent::Exit => shutdown_api_sidecar(app),
            _ => {}
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
