use serde::Serialize;
use std::sync::{
    atomic::{AtomicBool, AtomicU64, Ordering},
    Mutex,
};
use std::time::Duration;
use tauri::{AppHandle, Manager, WebviewWindow};
use zeroize::Zeroizing;

#[derive(Clone)]
struct Grant {
    challenge: Vec<u8>,
    id: String,
}
#[derive(Default)]
pub struct HelloState {
    grant: Mutex<Option<Grant>>,
    busy: AtomicBool,
    generation: AtomicU64,
}
#[derive(Serialize)]
pub struct HelloStatus {
    supported: bool,
    ready: bool,
    busy: bool,
}
struct Busy<'a>(&'a AtomicBool);
impl Drop for Busy<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}

fn check_window(window: &WebviewWindow) -> Result<(), String> {
    if window.label() != "main" {
        return Err("hello_unavailable".into());
    }
    Ok(())
}
pub fn cancel_pending(app: &AppHandle) {
    if let Some(state) = app.try_state::<HelloState>() {
        state.generation.fetch_add(1, Ordering::SeqCst);
    }
}

#[tauri::command]
pub fn cancel_windows_hello(window: WebviewWindow, app: AppHandle) -> Result<(), String> {
    check_window(&window)?;
    cancel_pending(&app);
    Ok(())
}
fn enter(state: &HelloState) -> Result<Busy<'_>, String> {
    state
        .busy
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| "hello_busy")?;
    Ok(Busy(&state.busy))
}
fn hex(value: &[u8]) -> Zeroizing<String> {
    Zeroizing::new(value.iter().map(|byte| format!("{byte:02x}")).collect())
}
fn valid_id(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}
const API_TIMEOUT: Duration = Duration::from_secs(8);

#[tauri::command]
pub async fn windows_hello_status(
    window: WebviewWindow,
    app: AppHandle,
) -> Result<HelloStatus, String> {
    check_window(&window)?;
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<HelloState>();
        HelloStatus {
            supported: platform::supported(),
            ready: state
                .grant
                .lock()
                .map(|value| value.is_some())
                .unwrap_or(false),
            busy: state.busy.load(Ordering::Acquire),
        }
    })
    .await
    .map_err(|_| "hello_unavailable".into())
}

#[tauri::command]
pub async fn enable_windows_hello(
    window: WebviewWindow,
    app: AppHandle,
    token: String,
) -> Result<HelloStatus, String> {
    check_window(&window)?;
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<HelloState>();
        let _busy = enter(&state)?;
        let generation = state.generation.load(Ordering::SeqCst);
        let challenge = platform::challenge()?;
        let key = platform::derive(&app, &challenge, true)?;
        if generation != state.generation.load(Ordering::SeqCst) {
            return Err("hello_cancelled".into());
        }
        let body = Zeroizing::new(format!("{{\"key\":\"{}\"}}", &*hex(&key)));
        let result = crate::native_api::request(
            &app,
            "POST",
            "/auth/hello/prepare",
            &body,
            Some(&token),
            API_TIMEOUT,
        )?;
        let id = result
            .get("grant_id")
            .and_then(|value| value.as_str())
            .filter(|value| valid_id(value))
            .ok_or("hello_unavailable")?
            .to_owned();
        if generation != state.generation.load(Ordering::SeqCst) {
            let _ =
                crate::native_api::request(&app, "DELETE", "/auth/hello", "{}", None, API_TIMEOUT);
            return Err("hello_cancelled".into());
        }
        *state.grant.lock().map_err(|_| "hello_unavailable")? = Some(Grant { challenge, id });
        Ok(HelloStatus {
            supported: true,
            ready: true,
            busy: false,
        })
    })
    .await
    .map_err(|_| "hello_unavailable".to_string())?
}

#[tauri::command]
pub async fn unlock_windows_hello(
    window: WebviewWindow,
    app: AppHandle,
) -> Result<serde_json::Value, String> {
    check_window(&window)?;
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<HelloState>();
        let _busy = enter(&state)?;
        let generation = state.generation.load(Ordering::SeqCst);
        let grant = state
            .grant
            .lock()
            .map_err(|_| "hello_unavailable")?
            .clone()
            .ok_or("hello_needs_master")?;
        let key = platform::derive(&app, &grant.challenge, false)?;
        if generation != state.generation.load(Ordering::SeqCst) {
            return Err("hello_cancelled".into());
        }
        let body = Zeroizing::new(format!(
            "{{\"grant_id\":\"{}\",\"key\":\"{}\"}}",
            grant.id,
            &*hex(&key)
        ));
        let result = crate::native_api::request(
            &app,
            "POST",
            "/auth/hello/unlock",
            &body,
            None,
            API_TIMEOUT,
        );
        if generation != state.generation.load(Ordering::SeqCst) {
            if let Ok(value) = &result {
                if let Some(token) = value.get("token").and_then(|value| value.as_str()) {
                    let _ = crate::native_api::request(
                        &app,
                        "POST",
                        "/auth/lock",
                        "{}",
                        Some(token),
                        API_TIMEOUT,
                    );
                }
            }
            return Err("hello_cancelled".into());
        }
        if result
            .as_ref()
            .is_err_and(|error| error == "hello_needs_master")
        {
            *state.grant.lock().map_err(|_| "hello_unavailable")? = None;
        }
        result
    })
    .await
    .map_err(|_| "hello_unavailable".to_string())?
}

#[tauri::command]
pub async fn disable_windows_hello(window: WebviewWindow, app: AppHandle) -> Result<(), String> {
    check_window(&window)?;
    cancel_pending(&app);
    *app.state::<HelloState>()
        .grant
        .lock()
        .map_err(|_| "hello_unavailable")? = None;
    tauri::async_runtime::spawn_blocking(move || {
        crate::native_api::request(&app, "DELETE", "/auth/hello", "{}", None, API_TIMEOUT)
            .map(|_| ())
    })
    .await
    .map_err(|_| "hello_unavailable".to_string())?
}

#[cfg(windows)]
mod platform {
    use super::*;
    use sha2::{Digest, Sha256};
    use windows::{
        core::HSTRING,
        Security::{
            Credentials::{KeyCredentialCreationOption, KeyCredentialManager, KeyCredentialStatus},
            Cryptography::CryptographicBuffer,
        },
        Storage::Streams::{DataReader, IBuffer},
        Win32::System::WinRT::{RoInitialize, RoUninitialize, RO_INIT_MULTITHREADED},
    };
    struct Apartment;
    impl Apartment {
        fn new() -> Result<Self, String> {
            unsafe { RoInitialize(RO_INIT_MULTITHREADED) }.map_err(|_| "hello_unavailable")?;
            Ok(Self)
        }
    }
    impl Drop for Apartment {
        fn drop(&mut self) {
            unsafe { RoUninitialize() };
        }
    }
    fn bytes(value: IBuffer) -> windows::core::Result<Vec<u8>> {
        let mut result = vec![0; value.Length()? as usize];
        DataReader::FromBuffer(&value)?.ReadBytes(&mut result)?;
        Ok(result)
    }
    pub fn supported() -> bool {
        let Ok(_apartment) = Apartment::new() else {
            return false;
        };
        KeyCredentialManager::IsSupportedAsync()
            .and_then(|operation| operation.join())
            .unwrap_or(false)
    }
    pub fn challenge() -> Result<Vec<u8>, String> {
        let _apartment = Apartment::new()?;
        CryptographicBuffer::GenerateRandom(32)
            .and_then(bytes)
            .map_err(|_| "hello_unavailable".into())
    }
    pub fn derive(
        app: &AppHandle,
        challenge: &[u8],
        create: bool,
    ) -> Result<Zeroizing<Vec<u8>>, String> {
        let _apartment = Apartment::new()?;
        let name = HSTRING::from(format!("{}.windows-hello", app.config().identifier));
        let execute = || -> windows::core::Result<_> {
            let mut result = if create {
                KeyCredentialManager::RequestCreateAsync(
                    &name,
                    KeyCredentialCreationOption::FailIfExists,
                )?
                .join()?
            } else {
                KeyCredentialManager::OpenAsync(&name)?.join()?
            };
            if result.Status()? == KeyCredentialStatus::CredentialAlreadyExists {
                result = KeyCredentialManager::OpenAsync(&name)?.join()?;
            }
            let status = result.Status()?;
            if status != KeyCredentialStatus::Success {
                return Ok(Err(if status == KeyCredentialStatus::UserCanceled {
                    "hello_cancelled"
                } else {
                    "hello_unavailable"
                }
                .into()));
            }
            let signed = result
                .Credential()?
                .RequestSignAsync(&CryptographicBuffer::CreateFromByteArray(challenge)?)?
                .join()?;
            let status = signed.Status()?;
            if status != KeyCredentialStatus::Success {
                return Ok(Err(if status == KeyCredentialStatus::UserCanceled {
                    "hello_cancelled"
                } else {
                    "hello_unavailable"
                }
                .into()));
            }
            let signature = Zeroizing::new(bytes(signed.Result()?)?);
            Ok(Ok(Zeroizing::new(Sha256::digest(&*signature).to_vec())))
        };
        execute().map_err(|_| "hello_unavailable".to_string())?
    }
}

#[cfg(not(windows))]
mod platform {
    use super::*;
    pub fn supported() -> bool {
        false
    }
    pub fn challenge() -> Result<Vec<u8>, String> {
        Err("hello_unavailable".into())
    }
    pub fn derive(_: &AppHandle, _: &[u8], _: bool) -> Result<Zeroizing<Vec<u8>>, String> {
        Err("hello_unavailable".into())
    }
}
