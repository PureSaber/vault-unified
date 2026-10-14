//! Explicit one-shot typing into a selected foreground window. Never sends Enter.
use serde::Serialize;
use std::sync::{
    atomic::{AtomicBool, AtomicU64, Ordering},
    Mutex,
};
use std::time::{Duration, Instant};
use tauri::{AppHandle, Manager, WebviewWindow};
use zeroize::Zeroizing;

#[derive(Default)]
pub struct AutoTypeState {
    target: Mutex<Option<(u64, Instant, platform::Target)>>,
    generation: AtomicU64,
    busy: AtomicBool,
}
#[derive(Serialize)]
pub struct TargetInfo {
    id: String,
    title: String,
    application: String,
}
struct Busy<'a>(&'a AtomicBool);
impl Drop for Busy<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}
fn enter(state: &AutoTypeState) -> Result<Busy<'_>, String> {
    state
        .busy
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| "type_busy")?;
    Ok(Busy(&state.busy))
}
fn main_window(window: &WebviewWindow) -> Result<(), String> {
    if window.label() != "main" {
        return Err("type_unavailable".into());
    }
    Ok(())
}
pub fn cancel_pending(app: &AppHandle) {
    if let Some(state) = app.try_state::<AutoTypeState>() {
        state.generation.fetch_add(1, Ordering::SeqCst);
        if let Ok(mut target) = state.target.lock() {
            *target = None;
        }
    }
}
#[tauri::command]
pub fn cancel_auto_type(window: WebviewWindow, app: AppHandle) -> Result<(), String> {
    main_window(&window)?;
    cancel_pending(&app);
    Ok(())
}

#[tauri::command]
pub async fn capture_type_target(
    window: WebviewWindow,
    app: AppHandle,
) -> Result<TargetInfo, String> {
    main_window(&window)?;
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<AutoTypeState>();
        let _busy = enter(&state)?;
        let generation = state.generation.fetch_add(1, Ordering::SeqCst) + 1;
        *state.target.lock().map_err(|_| "type_unavailable")? = None;
        window.hide().map_err(|_| "type_unavailable")?;
        let capture = || -> Result<TargetInfo, String> {
            for _ in 0..60 {
                std::thread::sleep(Duration::from_millis(50));
                if state.generation.load(Ordering::SeqCst) != generation {
                    return Err("type_cancelled".into());
                }
            }
            let target = platform::capture()?;
            let info = TargetInfo {
                id: generation.to_string(),
                title: target.title.clone(),
                application: target.application.clone(),
            };
            let mut stored = state.target.lock().map_err(|_| "type_unavailable")?;
            if state.generation.load(Ordering::SeqCst) != generation {
                return Err("type_cancelled".into());
            }
            *stored = Some((generation, Instant::now(), target));
            Ok(info)
        };
        let result = capture();
        crate::desktop::show_main(&app);
        result
    })
    .await
    .map_err(|_| "type_unavailable".to_string())?
}

fn take_string(value: &mut serde_json::Value, name: &str) -> Result<Zeroizing<String>, String> {
    match value.get_mut(name) {
        Some(serde_json::Value::String(text)) => Ok(Zeroizing::new(std::mem::take(text))),
        _ => Err("type_unavailable".into()),
    }
}
fn validate(sequence: &str, username: &str, password: &str, delay_ms: u64) -> Result<(), String> {
    if !["login", "username", "password"].contains(&sequence)
        || !(10..=100).contains(&delay_ms)
        || [username, password]
            .iter()
            .any(|value| value.chars().count() > 256 || value.chars().any(char::is_control))
        || (sequence != "password" && username.is_empty())
        || (sequence != "username" && password.is_empty())
    {
        return Err("type_values".into());
    }
    Ok(())
}

#[tauri::command]
pub async fn start_auto_type(
    window: WebviewWindow,
    app: AppHandle,
    target_id: String,
    entry_id: String,
    token: String,
    sequence: String,
    delay_ms: u64,
) -> Result<(), String> {
    main_window(&window)?;
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<AutoTypeState>();
        let _busy = enter(&state)?;
        let (generation, captured, target) = state
            .target
            .lock()
            .map_err(|_| "type_unavailable")?
            .take()
            .ok_or("type_target")?;
        if target_id != generation.to_string()
            || captured.elapsed() > Duration::from_secs(60)
            || state.generation.load(Ordering::SeqCst) != generation
        {
            return Err("type_target".into());
        }
        let mut values = crate::native_api::request(
            &app,
            "POST",
            "/entries/tools/auto-type",
            &serde_json::json!({"entry_id":entry_id}).to_string(),
            Some(&token),
            Duration::from_secs(5),
        )
        .map_err(|_| "type_values")?;
        let username = take_string(&mut values, "username")?;
        let password = take_string(&mut values, "password")?;
        validate(&sequence, &username, &password, delay_ms)?;
        if state.generation.load(Ordering::SeqCst) != generation {
            return Err("type_cancelled".into());
        }
        window.hide().map_err(|_| "type_unavailable")?;
        let result =
            platform::type_values(&target, &username, &password, &sequence, delay_ms, || {
                state.generation.load(Ordering::SeqCst) == generation
            });
        // Do not steal focus from the application after typing or a user focus change.
        let _ = window.show();
        result
    })
    .await
    .map_err(|_| "type_unavailable".to_string())?
}

#[cfg(windows)]
mod platform {
    use super::*;
    use std::{
        cell::Cell,
        mem::{size_of, zeroed},
        ptr::null_mut,
    };
    use windows_sys::Win32::{
        Foundation::{CloseHandle, HWND},
        System::Threading::{
            GetCurrentProcessId, OpenProcess, QueryFullProcessImageNameW,
            PROCESS_QUERY_LIMITED_INFORMATION,
        },
        UI::{
            Accessibility::{SetWinEventHook, UnhookWinEvent, HWINEVENTHOOK},
            Input::KeyboardAndMouse::{
                GetAsyncKeyState, SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT,
                KEYEVENTF_KEYUP, KEYEVENTF_UNICODE, VK_CONTROL, VK_ESCAPE, VK_LWIN, VK_MENU,
                VK_RWIN, VK_SHIFT, VK_TAB,
            },
            WindowsAndMessaging::{
                DispatchMessageW, GetForegroundWindow, GetWindowTextW, GetWindowThreadProcessId,
                IsWindow, IsWindowVisible, PeekMessageW, SetForegroundWindow, ShowWindow,
                TranslateMessage, EVENT_SYSTEM_FOREGROUND, MSG, PM_REMOVE, SW_RESTORE,
                WINEVENT_OUTOFCONTEXT,
            },
        },
    };
    pub struct Target {
        window: isize,
        process: isize,
        pid: u32,
        pub title: String,
        pub application: String,
    }
    impl Drop for Target {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.process as _);
            }
        }
    }
    thread_local! { static TARGET: Cell<isize> = const { Cell::new(0) }; static CHANGED: Cell<bool> = const { Cell::new(false) }; }
    unsafe extern "system" fn foreground(
        _: HWINEVENTHOOK,
        _: u32,
        hwnd: HWND,
        _: i32,
        _: i32,
        _: u32,
        _: u32,
    ) {
        if TARGET.with(|value| value.get()) != hwnd as isize {
            CHANGED.with(|value| value.set(true));
        }
    }
    struct Hook(HWINEVENTHOOK);
    impl Drop for Hook {
        fn drop(&mut self) {
            unsafe {
                UnhookWinEvent(self.0);
            }
            TARGET.with(|value| value.set(0));
        }
    }
    fn title(window: HWND) -> String {
        let mut text = [0u16; 513];
        let count = unsafe { GetWindowTextW(window, text.as_mut_ptr(), text.len() as i32) };
        String::from_utf16_lossy(&text[..count.max(0) as usize])
    }
    pub fn capture() -> Result<Target, String> {
        unsafe {
            let window = GetForegroundWindow();
            let mut pid = 0;
            GetWindowThreadProcessId(window, &mut pid);
            if window.is_null()
                || pid == 0
                || pid == GetCurrentProcessId()
                || IsWindowVisible(window) == 0
            {
                return Err("type_target".into());
            }
            let name = title(window);
            if name.trim().is_empty() {
                return Err("type_target".into());
            }
            let process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
            if process.is_null() {
                return Err("type_target".into());
            }
            let mut target = Target {
                window: window as isize,
                process: process as isize,
                pid,
                title: name,
                application: String::new(),
            };
            let mut path = [0u16; 1024];
            let mut length = path.len() as u32;
            if QueryFullProcessImageNameW(process, 0, path.as_mut_ptr(), &mut length) == 0 {
                return Err("type_target".into());
            }
            target.application = String::from_utf16_lossy(&path[..length as usize])
                .rsplit('\\')
                .next()
                .unwrap_or("")
                .to_string();
            Ok(target)
        }
    }
    fn valid(target: &Target) -> bool {
        unsafe {
            let window = target.window as HWND;
            let mut pid = 0;
            GetWindowThreadProcessId(window, &mut pid);
            IsWindow(window) != 0 && pid == target.pid && title(window) == target.title
        }
    }
    fn pump() {
        unsafe {
            let mut message: MSG = zeroed();
            while PeekMessageW(&mut message, null_mut(), 0, 0, PM_REMOVE) != 0 {
                TranslateMessage(&message);
                DispatchMessageW(&message);
            }
        }
    }
    fn input(scan: u16, key: u16, up: bool) -> INPUT {
        INPUT {
            r#type: INPUT_KEYBOARD,
            Anonymous: INPUT_0 {
                ki: KEYBDINPUT {
                    wVk: key,
                    wScan: scan,
                    dwFlags: (if key == 0 { KEYEVENTF_UNICODE } else { 0 })
                        | (if up { KEYEVENTF_KEYUP } else { 0 }),
                    time: 0,
                    dwExtraInfo: 0,
                },
            },
        }
    }
    pub fn type_values(
        target: &Target,
        username: &str,
        password: &str,
        sequence: &str,
        delay_ms: u64,
        current: impl Fn() -> bool,
    ) -> Result<(), String> {
        if !valid(target) || !current() {
            return Err("type_target".into());
        }
        unsafe {
            ShowWindow(target.window as HWND, SW_RESTORE);
            if SetForegroundWindow(target.window as HWND) == 0 {
                return Err("type_target".into());
            }
        }
        std::thread::sleep(Duration::from_millis(180));
        if unsafe { GetForegroundWindow() } as isize != target.window {
            return Err("type_focus".into());
        }
        TARGET.with(|value| value.set(target.window));
        CHANGED.with(|value| value.set(false));
        let hook = Hook(unsafe {
            SetWinEventHook(
                EVENT_SYSTEM_FOREGROUND,
                EVENT_SYSTEM_FOREGROUND,
                null_mut(),
                Some(foreground),
                0,
                0,
                WINEVENT_OUTOFCONTEXT,
            )
        });
        if hook.0.is_null() {
            return Err("type_unavailable".into());
        }
        let start = Instant::now();
        let guard = || -> Result<(), String> {
            pump();
            if !current() || start.elapsed() > Duration::from_secs(30) {
                return Err("type_cancelled".into());
            }
            if CHANGED.with(|value| value.get())
                || unsafe { GetForegroundWindow() } as isize != target.window
                || !valid(target)
            {
                return Err("type_focus".into());
            }
            if [VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN, VK_ESCAPE]
                .iter()
                .any(|key| unsafe { GetAsyncKeyState(*key as i32) } < 0)
            {
                return Err("type_cancelled".into());
            }
            Ok(())
        };
        let send = |units: &[u16], tab: bool| -> Result<(), String> {
            guard()?;
            let mut inputs = Vec::new();
            for unit in units {
                let key = if tab { VK_TAB } else { 0 };
                inputs.push(input(if tab { 0 } else { *unit }, key, false));
                inputs.push(input(if tab { 0 } else { *unit }, key, true));
            }
            let count = unsafe {
                SendInput(
                    inputs.len() as u32,
                    inputs.as_ptr(),
                    size_of::<INPUT>() as i32,
                )
            };
            for value in &mut inputs {
                value.Anonymous.ki.wScan = 0;
            }
            if count != inputs.len() as u32 {
                return Err("type_unavailable".into());
            }
            std::thread::sleep(Duration::from_millis(delay_ms));
            guard()
        };
        let text = |value: &str| -> Result<(), String> {
            for character in value.chars() {
                let mut units = Zeroizing::new([0u16; 2]);
                send(character.encode_utf16(&mut *units), false)?;
            }
            Ok(())
        };
        guard()?;
        if sequence != "password" {
            text(username)?;
        }
        if sequence == "login" {
            send(&[0], true)?;
            std::thread::sleep(Duration::from_millis(150));
            guard()?;
        }
        if sequence != "username" {
            text(password)?;
        }
        Ok(())
    }
}
#[cfg(not(windows))]
mod platform {
    pub struct Target {
        pub title: String,
        pub application: String,
    }
    pub fn capture() -> Result<Target, String> {
        Err("type_unavailable".into())
    }
    pub fn type_values(
        _: &Target,
        _: &str,
        _: &str,
        _: &str,
        _: u64,
        _: impl Fn() -> bool,
    ) -> Result<(), String> {
        Err("type_unavailable".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn sequences_are_literal_and_never_accept_submit_or_control_characters() {
        assert!(validate("login", "generated{ENTER}", "generated!中文", 20).is_ok());
        for sequence in ["enter", "login_enter", ""] {
            assert!(validate(sequence, "user", "value", 20).is_err());
        }
        for value in ["line\nnext", "tab\tfield", "escape\u{1b}"] {
            assert!(validate("login", "user", value, 20).is_err());
        }
        assert!(validate("password", "", "value", 20).is_ok());
        assert!(validate("login", "", "value", 20).is_err());
        assert!(validate("login", "user", "value", 0).is_err());
    }
}
