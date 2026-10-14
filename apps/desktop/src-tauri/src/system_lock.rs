//! Windows session/power notifications revoke API access even if the webview stalls.
#[cfg(windows)]
mod windows {
    use crate::shutdown_api_sidecar;
    use std::sync::mpsc::{channel, Sender};
    use std::time::Duration;
    use tauri::{AppHandle, Emitter, Manager};
    use windows_sys::Win32::{
        Foundation::{HWND, LPARAM, LRESULT, WPARAM},
        System::RemoteDesktop::{
            WTSRegisterSessionNotification, WTSUnRegisterSessionNotification,
            NOTIFY_FOR_THIS_SESSION,
        },
        UI::{
            Shell::{DefSubclassProc, RemoveWindowSubclass, SetWindowSubclass},
            WindowsAndMessaging::{
                PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND, PBT_APMSUSPEND, WM_NCDESTROY,
                WM_POWERBROADCAST, WM_WTSSESSION_CHANGE,
            },
        },
    };

    const SUBCLASS_ID: usize = 0x56554c54;
    enum Event {
        Session(bool),
        Suspend(bool),
    }
    struct Observer {
        app: AppHandle,
        send: Sender<(Event, Sender<bool>)>,
    }

    fn notify_api(app: &AppHandle, blocked: bool) -> Result<(), String> {
        let body = if blocked {
            "{\"blocked\":true}"
        } else {
            "{\"blocked\":false}"
        };
        crate::native_api::request(
            app,
            "POST",
            "/auth/system-state",
            body,
            None,
            Duration::from_millis(400),
        )
        .map(|_| ())
    }

    unsafe extern "system" fn observe(
        hwnd: HWND,
        msg: u32,
        w: WPARAM,
        l: LPARAM,
        id: usize,
        data: usize,
    ) -> LRESULT {
        let observer = &*(data as *const Observer);
        let event = match (msg, w as u32) {
            (WM_WTSSESSION_CHANGE, 7) => Some(Event::Session(true)),
            (WM_WTSSESSION_CHANGE, 8) => Some(Event::Session(false)),
            (WM_POWERBROADCAST, PBT_APMSUSPEND) => Some(Event::Suspend(true)),
            (WM_POWERBROADCAST, PBT_APMRESUMEAUTOMATIC | PBT_APMRESUMESUSPEND) => {
                Some(Event::Suspend(false))
            }
            _ => None,
        };
        if let Some(event) = event {
            crate::hello::cancel_pending(&observer.app);
            // Clear visible secrets immediately, without a draft confirmation dialog.
            let _ = observer.app.emit("desktop-system-locked", ());
            let (acknowledge, received) = channel();
            let sent = observer.send.send((event, acknowledge)).is_ok();
            // Windows allows about two seconds for suspend handling. Finish the
            // API revocation before returning; a stalled API is terminated.
            if !sent || received.recv_timeout(Duration::from_millis(1500)) != Ok(true) {
                shutdown_api_sidecar(&observer.app);
                observer.app.exit(1);
            }
        }
        if msg == WM_NCDESTROY {
            WTSUnRegisterSessionNotification(hwnd);
            RemoveWindowSubclass(hwnd, Some(observe), id);
            drop(Box::from_raw(data as *mut Observer));
        }
        DefSubclassProc(hwnd, msg, w, l)
    }

    pub fn setup(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
        let window = app
            .get_webview_window("main")
            .ok_or("Main window unavailable")?;
        let hwnd = window.hwnd()?.0 as HWND;
        let (send, receive) = channel();
        let observer = Box::new(Observer {
            app: app.clone(),
            send,
        });
        let data = Box::into_raw(observer);
        unsafe {
            if WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION) == 0 {
                drop(Box::from_raw(data));
                return Err(std::io::Error::last_os_error().into());
            }
            if SetWindowSubclass(hwnd, Some(observe), SUBCLASS_ID, data as usize) == 0 {
                WTSUnRegisterSessionNotification(hwnd);
                drop(Box::from_raw(data));
                return Err(std::io::Error::last_os_error().into());
            }
        }
        let app = app.clone();
        std::thread::spawn(move || {
            let (mut locked, mut suspended) = (false, false);
            while let Ok((event, acknowledge)) = receive.recv() {
                match event {
                    Event::Session(value) => locked = value,
                    Event::Suspend(value) => suspended = value,
                }
                let success = notify_api(&app, locked || suspended).is_ok();
                let _ = acknowledge.send(success);
                if !success {
                    break;
                }
            }
        });
        Ok(())
    }
}

#[cfg(windows)]
pub use windows::setup;
#[cfg(not(windows))]
pub fn setup(_: &tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    Ok(())
}
