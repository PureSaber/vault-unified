//! Optional signed updates. Only native code chooses endpoints and installers.
use serde::Serialize;
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex,
    },
    time::Duration,
};
use tauri::{AppHandle, Emitter, Manager, WebviewWindow};
use tauri_plugin_updater::{Update, UpdaterExt};

#[derive(Default)]
pub struct UpdateState {
    pending: Mutex<Option<Update>>,
    busy: AtomicBool,
}
#[derive(Clone, Serialize)]
pub struct UpdateInfo {
    version: String,
    notes: String,
}
#[derive(Clone, Serialize)]
pub struct Progress {
    downloaded: u64,
    total: Option<u64>,
    stage: &'static str,
}
struct Busy<'a>(&'a AtomicBool);
impl Drop for Busy<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}
fn enter(state: &UpdateState) -> Result<Busy<'_>, String> {
    state
        .busy
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| "update_busy")?;
    Ok(Busy(&state.busy))
}
fn window_allowed(window: &WebviewWindow) -> Result<(), String> {
    if window.label() == "main" {
        Ok(())
    } else {
        Err("update_unavailable".into())
    }
}
fn info(value: &Update) -> UpdateInfo {
    UpdateInfo {
        version: value.version.clone(),
        notes: value
            .body
            .as_deref()
            .unwrap_or("")
            .chars()
            .take(8000)
            .collect(),
    }
}
fn allowed_asset(url: &str, version: &str) -> bool {
    let prefix =
        format!("https://github.com/PureSaber/vault-unified/releases/download/v{version}/");
    url.strip_prefix(&prefix).is_some_and(|name| {
        !name.is_empty()
            && !name.contains(['/', '?', '#'])
            && (name.ends_with("-setup.exe") || name.ends_with(".msi"))
    })
}

#[tauri::command]
pub fn update_status(window: WebviewWindow, app: AppHandle) -> Result<Option<UpdateInfo>, String> {
    window_allowed(&window)?;
    let state = app.state::<UpdateState>();
    let pending = state.pending.lock().map_err(|_| "update_unavailable")?;
    Ok(pending.as_ref().map(info))
}

#[tauri::command]
pub async fn check_desktop_update(
    window: WebviewWindow,
    app: AppHandle,
) -> Result<Option<UpdateInfo>, String> {
    window_allowed(&window)?;
    let state = app.state::<UpdateState>();
    let _busy = enter(&state)?;
    *state.pending.lock().map_err(|_| "update_unavailable")? = None;
    let builder = app
        .updater_builder()
        .timeout(Duration::from_secs(20))
        .configure_client(|client| client.https_only(true));
    let mut update = builder
        .build()
        .map_err(|_| "update_unavailable")?
        .check()
        .await
        .map_err(|_| "update_check_failed")?;
    if let Some(value) = &mut update {
        if !allowed_asset(value.download_url.as_str(), &value.version) {
            return Err("update_source_rejected".into());
        }
        value.timeout = Some(Duration::from_secs(180));
    }
    let result = update.as_ref().map(info);
    *state.pending.lock().map_err(|_| "update_unavailable")? = update;
    Ok(result)
}

#[tauri::command]
pub async fn install_desktop_update(
    window: WebviewWindow,
    app: AppHandle,
    version: String,
    token: String,
    confirm: bool,
) -> Result<(), String> {
    window_allowed(&window)?;
    if !confirm {
        return Err("update_confirmation_required".into());
    }
    let token = zeroize::Zeroizing::new(token);
    let state = app.state::<UpdateState>();
    let _busy = enter(&state)?;
    let update = state
        .pending
        .lock()
        .map_err(|_| "update_unavailable")?
        .take()
        .ok_or("update_check_required")?;
    if version != update.version {
        return Err("update_changed".into());
    }
    let mut downloaded = 0;
    let bytes = update
        .download(
            |count, total| {
                downloaded += count as u64;
                let _ = app.emit_to(
                    "main",
                    "desktop-update-progress",
                    Progress {
                        downloaded,
                        total,
                        stage: "downloading",
                    },
                );
            },
            || {},
        )
        .await
        .map_err(|_| "update_verification_failed")?;
    let _ = app.emit_to(
        "main",
        "desktop-update-progress",
        Progress {
            downloaded,
            total: Some(downloaded),
            stage: "preparing",
        },
    );
    let backup_app = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        crate::native_api::request(
            &backup_app,
            "POST",
            "/personal/update/prepare",
            "{\"confirm\":true}",
            Some(&token),
            Duration::from_secs(60),
        )
    })
    .await
    .map_err(|_| "update_backup_failed")?
    .map_err(|_| "update_backup_failed")?;
    let _ = app.emit_to(
        "main",
        "desktop-update-progress",
        Progress {
            downloaded,
            total: Some(downloaded),
            stage: "installing",
        },
    );
    // download() has already checked the pinned signing key and signed version.
    // Windows exits only after successfully launching the installer. The process
    // owns the sidecar's kill-on-close job, so it cannot survive this exit.
    update
        .install(bytes)
        .map_err(|_| "update_install_failed".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn only_matching_release_assets_are_accepted() {
        assert!(allowed_asset("https://github.com/PureSaber/vault-unified/releases/download/v1.4.0/Vault.Unified_1.4.0_x64-setup.exe", "1.4.0"));
        for value in [
            "http://github.com/PureSaber/vault-unified/releases/download/v1.4.0/a-setup.exe",
            "https://github.com/other/repo/releases/download/v1.4.0/a-setup.exe",
            "https://github.com/PureSaber/vault-unified/releases/download/v1.3.0/a-setup.exe",
            "https://github.com/PureSaber/vault-unified/releases/download/v1.4.0/../a-setup.exe",
            "https://github.com/PureSaber/vault-unified/releases/download/v1.4.0/a.cmd",
        ] {
            assert!(!allowed_asset(value, "1.4.0"));
        }
    }
}
