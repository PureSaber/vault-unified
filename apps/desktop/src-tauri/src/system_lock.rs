//! Windows session/power notifications revoke API access even if the webview stalls.
#[cfg(windows)]
mod windows {
    use crate::{shutdown_api_sidecar, ApiSidecar};
    use std::io::{Read, Write};
    use std::net::{SocketAddr, TcpStream};
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

    fn notify_api(app: &AppHandle, blocked: bool) -> std::io::Result<()> {
        let state = app.state::<ApiSidecar>();
        let authority = state
            .config
            .base_url
            .strip_prefix("http://")
            .and_then(|value| value.strip_suffix("/api"))
            .ok_or_else(|| std::io::Error::other("Invalid API address"))?;
        let address: SocketAddr = authority
            .parse()
            .map_err(|_| std::io::Error::other("Invalid API address"))?;
        if !address.ip().is_loopback() {
            return Err(std::io::Error::other("Invalid API address"));
        }
        let mut stream = TcpStream::connect_timeout(&address, Duration::from_millis(400))?;
        stream.set_read_timeout(Some(Duration::from_millis(400)))?;
        stream.set_write_timeout(Some(Duration::from_millis(400)))?;
        let body = if blocked {
            "{\"blocked\":true}"
        } else {
            "{\"blocked\":false}"
        };
        let request = format!("POST /api/auth/system-state HTTP/1.1\r\nHost: {}\r\nX-Vault-Bootstrap: {}\r\nX-Vault-Client: vault-unified-desktop\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", authority, state.config.bootstrap_secret, body.len(), body);
        stream.write_all(request.as_bytes())?;
        let mut response = Vec::new();
        stream.take(4096).read_to_end(&mut response)?;
        if !response.starts_with(b"HTTP/1.1 200 ") {
            return Err(std::io::Error::other("System lock not acknowledged"));
        }
        Ok(())
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
