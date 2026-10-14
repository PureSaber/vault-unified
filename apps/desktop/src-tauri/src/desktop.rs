use serde::{Deserialize, Serialize};
use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex,
    },
};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager, WebviewWindow,
};
use tauri_plugin_global_shortcut::GlobalShortcutExt;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Preferences {
    pub close_to_tray: bool,
    pub shortcut: String,
    pub locale: String,
    #[serde(default)]
    pub check_updates: bool,
}

impl Default for Preferences {
    fn default() -> Self {
        Self {
            close_to_tray: true,
            shortcut: "Control+Shift+Space".into(),
            locale: "zh".into(),
            check_updates: false,
        }
    }
}

impl Preferences {
    fn validate(&self) -> Result<(), String> {
        if ![
            "",
            "Control+Shift+Space",
            "Control+Alt+KeyV",
            "Control+Shift+KeyY",
        ]
        .contains(&self.shortcut.as_str())
        {
            return Err("unsupported_shortcut".into());
        }
        if self.locale != "en" && self.locale != "zh" {
            return Err("unsupported_locale".into());
        }
        Ok(())
    }
}

#[derive(Clone, Serialize)]
pub struct DesktopStatus {
    preferences: Preferences,
    tray_available: bool,
    shortcut_registered: bool,
}

pub struct DesktopState {
    status: Mutex<DesktopStatus>,
    preferences_path: PathBuf,
    ready: AtomicBool,
    search_pending: AtomicBool,
}

fn check_window(window: &WebviewWindow) -> Result<(), String> {
    if window.label() == "main" {
        Ok(())
    } else {
        Err("unsupported_window".into())
    }
}

pub fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

#[tauri::command]
pub fn show_desktop_approval(app: AppHandle, window: WebviewWindow) -> Result<(), String> {
    check_window(&window)?;
    show_main(&app);
    Ok(())
}

pub fn quick_search(app: &AppHandle) {
    show_main(app);
    if let Some(state) = app.try_state::<DesktopState>() {
        if state.ready.load(Ordering::Acquire) {
            let _ = app.emit_to("main", "desktop-quick-search", ());
        } else {
            state.search_pending.store(true, Ordering::Release);
        }
    }
}

fn tray_menu(app: &AppHandle, locale: &str) -> tauri::Result<Menu<tauri::Wry>> {
    let zh = locale == "zh";
    let show = MenuItem::with_id(
        app,
        "show",
        if zh {
            "打开 Vault Unified"
        } else {
            "Open Vault Unified"
        },
        true,
        None::<&str>,
    )?;
    let search = MenuItem::with_id(
        app,
        "search",
        if zh { "快捷搜索" } else { "Quick search" },
        true,
        None::<&str>,
    )?;
    let lock = MenuItem::with_id(
        app,
        "lock",
        if zh { "锁定密码库" } else { "Lock vault" },
        true,
        None::<&str>,
    )?;
    let quit = MenuItem::with_id(
        app,
        "quit",
        if zh { "退出" } else { "Quit" },
        true,
        None::<&str>,
    )?;
    Menu::with_items(app, &[&show, &search, &lock, &quit])
}

pub fn request_exit(app: &AppHandle) {
    if app
        .try_state::<DesktopState>()
        .is_some_and(|state| state.ready.load(Ordering::Acquire))
    {
        show_main(app);
        let _ = app.emit_to("main", "desktop-exit-requested", ());
    } else {
        app.exit(0);
    }
}

pub fn close_requested(app: &AppHandle) {
    let hide = app
        .try_state::<DesktopState>()
        .and_then(|state| {
            state
                .status
                .lock()
                .ok()
                .map(|status| status.tray_available && status.preferences.close_to_tray)
        })
        .unwrap_or(false);
    if hide {
        if let Some(window) = app.get_webview_window("main") {
            if window.hide().is_ok() {
                let _ = app.emit_to("main", "desktop-hidden", ());
                return;
            }
        }
    }
    request_exit(app);
}

pub fn setup(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let directory = std::env::var_os("VAULT_CONFIG_DIR")
        .map(PathBuf::from)
        .unwrap_or(app.path().app_config_dir()?);
    let preferences_path = directory.join("desktop-preferences.json");
    let preferences = std::fs::read(&preferences_path)
        .ok()
        .and_then(|bytes| serde_json::from_slice::<Preferences>(&bytes).ok())
        .filter(|value| value.validate().is_ok())
        .unwrap_or_default();
    let shortcut_registered = !preferences.shortcut.is_empty()
        && app
            .global_shortcut()
            .register(preferences.shortcut.as_str())
            .is_ok();
    let tray_available = (|| -> tauri::Result<()> {
        let mut builder = TrayIconBuilder::with_id("vault-main")
            .tooltip("Vault Unified")
            .menu(&tray_menu(app, &preferences.locale)?)
            .show_menu_on_left_click(false)
            .on_menu_event(|app, event| match event.id.as_ref() {
                "show" => show_main(app),
                "search" => quick_search(app),
                "lock" => {
                    crate::hello::cancel_pending(app);
                    crate::auto_type::cancel_pending(app);
                    show_main(app);
                    let _ = app.emit_to("main", "desktop-lock-requested", ());
                }
                "quit" => request_exit(app),
                _ => {}
            })
            .on_tray_icon_event(|tray, event| {
                if matches!(
                    event,
                    TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    }
                ) {
                    show_main(tray.app_handle());
                }
            });
        if let Some(icon) = app.default_window_icon() {
            builder = builder.icon(icon.clone());
        }
        builder.build(app)?;
        Ok(())
    })()
    .is_ok();
    app.manage(DesktopState {
        status: Mutex::new(DesktopStatus {
            preferences,
            tray_available,
            shortcut_registered,
        }),
        preferences_path,
        ready: AtomicBool::new(false),
        search_pending: AtomicBool::new(false),
    });
    Ok(())
}

#[tauri::command]
pub fn desktop_ready(
    window: WebviewWindow,
    state: tauri::State<'_, DesktopState>,
) -> Result<bool, String> {
    check_window(&window)?;
    state.ready.store(true, Ordering::Release);
    Ok(state.search_pending.swap(false, Ordering::AcqRel))
}

#[tauri::command]
pub fn get_desktop_status(
    window: WebviewWindow,
    state: tauri::State<'_, DesktopState>,
) -> Result<DesktopStatus, String> {
    check_window(&window)?;
    state
        .status
        .lock()
        .map(|status| status.clone())
        .map_err(|_| "desktop_unavailable".into())
}

#[tauri::command]
pub fn set_desktop_preferences(
    window: WebviewWindow,
    app: AppHandle,
    state: tauri::State<'_, DesktopState>,
    preferences: Preferences,
) -> Result<DesktopStatus, String> {
    check_window(&window)?;
    preferences.validate()?;
    let mut status = state.status.lock().map_err(|_| "desktop_unavailable")?;
    let change_shortcut = preferences.shortcut != status.preferences.shortcut
        || (!preferences.shortcut.is_empty() && !status.shortcut_registered);
    let registered_new = change_shortcut && !preferences.shortcut.is_empty();
    if registered_new {
        app.global_shortcut()
            .register(preferences.shortcut.as_str())
            .map_err(|_| "shortcut_unavailable")?;
    }
    let save = (|| -> std::io::Result<()> {
        if let Some(parent) = state.preferences_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        // This file contains only UI preferences. A damaged file uses secure defaults.
        std::fs::write(&state.preferences_path, serde_json::to_vec(&preferences)?)
    })();
    if save.is_err() {
        if registered_new {
            let _ = app
                .global_shortcut()
                .unregister(preferences.shortcut.as_str());
        }
        return Err("preferences_save_failed".into());
    }
    if change_shortcut && status.shortcut_registered {
        let _ = app
            .global_shortcut()
            .unregister(status.preferences.shortcut.as_str());
    }
    if change_shortcut {
        status.shortcut_registered = registered_new;
    }
    if let Some(tray) = app.tray_by_id("vault-main") {
        if let Ok(menu) = tray_menu(&app, &preferences.locale) {
            let _ = tray.set_menu(Some(menu));
        }
    }
    status.preferences = preferences;
    Ok(status.clone())
}

#[tauri::command]
pub fn exit_desktop(window: WebviewWindow, app: AppHandle) -> Result<(), String> {
    check_window(&window)?;
    app.exit(0);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_arbitrary_shortcuts_and_invalid_preferences() {
        let mut value = Preferences::default();
        assert!(value.validate().is_ok());
        value.shortcut = "Control+KeyC".into();
        assert!(value.validate().is_err());
        value.shortcut.clear();
        assert!(value.validate().is_ok());
        value.locale = "../en".into();
        assert!(value.validate().is_err());
        assert!(serde_json::from_str::<Preferences>(
            r#"{"close_to_tray":true,"shortcut":"","locale":"en","password":"bad"}"#
        )
        .is_err());
    }
}
