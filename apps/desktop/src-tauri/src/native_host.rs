//! Native messaging exposes only the address of this running desktop instance.
//! No bootstrap, vault, device, or bearer credential crosses this channel.
use serde_json::{json, Value};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::time::Duration;

pub fn directory() -> Option<PathBuf> {
    std::env::var_os("VAULT_BROWSER_DISCOVERY_DIR")
        .map(PathBuf::from)
        .or_else(|| {
            std::env::var_os("VAULT_DATA_DIR")
                .map(PathBuf::from)
                .or_else(|| {
                    std::env::var_os("LOCALAPPDATA").map(|v| PathBuf::from(v).join("VaultUnified"))
                })
                .map(|v| v.join("browser-bridge"))
        })
}

#[cfg(windows)]
fn registered_directory() -> Option<PathBuf> {
    use windows_sys::Win32::System::Registry::{RegGetValueW, HKEY_CURRENT_USER, RRF_RT_REG_SZ};
    for browser in ["Google\\Chrome", "Microsoft\\Edge"] {
        let subkey: Vec<u16> =
            format!("Software\\{browser}\\NativeMessagingHosts\\org.vaultunified.desktop\0")
                .encode_utf16()
                .collect();
        let mut size = 0u32;
        let result = unsafe {
            RegGetValueW(
                HKEY_CURRENT_USER,
                subkey.as_ptr(),
                std::ptr::null(),
                RRF_RT_REG_SZ,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                &mut size,
            )
        };
        if result != 0 || size == 0 || size > 8192 || size % 2 != 0 {
            continue;
        }
        let mut value = vec![0u16; (size / 2) as usize];
        let result = unsafe {
            RegGetValueW(
                HKEY_CURRENT_USER,
                subkey.as_ptr(),
                std::ptr::null(),
                RRF_RT_REG_SZ,
                std::ptr::null_mut(),
                value.as_mut_ptr().cast(),
                &mut size,
            )
        };
        if result != 0 {
            continue;
        }
        if let Some(end) = value.iter().position(|v| *v == 0) {
            if let Ok(text) = String::from_utf16(&value[..end]) {
                let path = PathBuf::from(text);
                if path.is_absolute()
                    && path.file_name().and_then(|v| v.to_str()) == Some("native-host.json")
                {
                    return path.parent().map(|v| v.to_path_buf());
                }
            }
        }
    }
    None
}

#[cfg(not(windows))]
fn registered_directory() -> Option<PathBuf> {
    None
}

fn valid_origin(value: &str) -> bool {
    let tail = value.strip_prefix("chrome-extension://").unwrap_or("");
    let id = tail.strip_suffix('/').unwrap_or(tail);
    id.len() == 32 && id.bytes().all(|b| (b'a'..=b'p').contains(&b))
}

fn read_json(path: &std::path::Path) -> Result<Value, ()> {
    let mut data = Vec::new();
    std::fs::File::open(path)
        .map_err(|_| ())?
        .take(8193)
        .read_to_end(&mut data)
        .map_err(|_| ())?;
    if data.len() > 8192 {
        return Err(());
    }
    serde_json::from_slice(&data).map_err(|_| ())
}

fn manifest_belongs_to(manifest: &std::path::Path, executable: &std::path::Path) -> bool {
    let Ok(value) = read_json(manifest) else { return false; };
    if value.get("name").and_then(Value::as_str) != Some("org.vaultunified.desktop") {
        return false;
    }
    let Some(path) = value.get("path").and_then(Value::as_str) else { return false; };
    let path = std::path::Path::new(path);
    if !path.is_absolute() { return false; }
    match (path.canonicalize(), executable.canonicalize()) {
        (Ok(left), Ok(right)) => left.to_string_lossy().eq_ignore_ascii_case(&right.to_string_lossy()),
        _ => false,
    }
}

/// The uninstaller only removes current-user registrations that still point to
/// this exact executable. It never deletes a vault, identity, or another install.
#[cfg(windows)]
pub fn unregister() -> bool {
    use windows_sys::Win32::System::Registry::{RegDeleteKeyW, RegGetValueW, HKEY_CURRENT_USER, RRF_RT_REG_SZ};
    let Ok(executable) = std::env::current_exe() else { return false; };
    let mut success = true;
    for browser in ["Google\\Chrome", "Microsoft\\Edge"] {
        let subkey: Vec<u16> = format!("Software\\{browser}\\NativeMessagingHosts\\org.vaultunified.desktop\0").encode_utf16().collect();
        let mut value = [0u16; 4096];
        let mut size = std::mem::size_of_val(&value) as u32;
        let result = unsafe { RegGetValueW(HKEY_CURRENT_USER, subkey.as_ptr(), std::ptr::null(), RRF_RT_REG_SZ, std::ptr::null_mut(), value.as_mut_ptr().cast(), &mut size) };
        if result == 2 { continue; } // not registered
        if result != 0 || size == 0 || size % 2 != 0 { success = false; continue; }
        let Some(end) = value.iter().position(|v| *v == 0) else { success = false; continue; };
        let Ok(path) = String::from_utf16(&value[..end]) else { success = false; continue; };
        if manifest_belongs_to(std::path::Path::new(&path), &executable) {
            let result = unsafe { RegDeleteKeyW(HKEY_CURRENT_USER, subkey.as_ptr()) };
            success &= result == 0 || result == 2;
        }
    }
    success
}

#[cfg(not(windows))]
pub fn unregister() -> bool { true }

fn discover(origin: &str, dir: &std::path::Path) -> Result<Value, ()> {
    if !valid_origin(origin) {
        return Err(());
    }
    let manifest = read_json(&dir.join("native-host.json"))?;
    let allowed = manifest
        .get("allowed_origins")
        .and_then(Value::as_array)
        .ok_or(())?;
    let canonical = format!("{}/", origin.trim_end_matches('/'));
    if !allowed
        .iter()
        .any(|v| v.as_str() == Some(canonical.as_str()))
    {
        return Err(());
    }
    let runtime = read_json(&dir.join("runtime.json"))?;
    if runtime.get("protocol").and_then(Value::as_u64) != Some(1) {
        return Err(());
    }
    let url = runtime.get("base_url").and_then(Value::as_str).ok_or(())?;
    let port = url
        .strip_prefix("http://127.0.0.1:")
        .and_then(|v| v.strip_suffix("/api"))
        .and_then(|v| v.parse::<u16>().ok())
        .filter(|v| *v != 0)
        .ok_or(())?;
    let instance = runtime
        .get("instance_id")
        .and_then(Value::as_str)
        .filter(|v| v.len() <= 128)
        .ok_or(())?;
    // A stale port or an unrelated listener is not a running desktop instance.
    let address: SocketAddr = format!("127.0.0.1:{port}").parse().map_err(|_| ())?;
    let mut stream =
        TcpStream::connect_timeout(&address, Duration::from_secs(1)).map_err(|_| ())?;
    stream
        .set_read_timeout(Some(Duration::from_secs(2)))
        .map_err(|_| ())?;
    stream
        .set_write_timeout(Some(Duration::from_secs(2)))
        .map_err(|_| ())?;
    write!(stream, "GET /api/browser/discovery HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n").map_err(|_| ())?;
    let mut response = String::new();
    stream
        .take(8193)
        .read_to_string(&mut response)
        .map_err(|_| ())?;
    if response.len() > 8192 {
        return Err(());
    }
    let (headers, body) = response.split_once("\r\n\r\n").ok_or(())?;
    if !headers.starts_with("HTTP/1.1 200 ") && !headers.starts_with("HTTP/1.0 200 ") {
        return Err(());
    }
    let live: Value = serde_json::from_str(body).map_err(|_| ())?;
    if live.get("instance_id").and_then(Value::as_str) != Some(instance) {
        return Err(());
    }
    let mut reply = json!({"protocol": 1, "base_url": url, "instance_id": instance});
    // The connect nonce only lets an extension ask for a desktop-approved
    // connection. It is released after the allowed_origins check above, never
    // to other callers (docs/browser-connection-approval.md).
    if let Ok(connect) = read_json(&dir.join("connect.json")) {
        let nonce = connect
            .get("connect_nonce")
            .and_then(Value::as_str)
            .filter(|v| !v.is_empty() && v.len() <= 128);
        if connect.get("instance_id").and_then(Value::as_str) == Some(instance) {
            if let Some(nonce) = nonce {
                reply["connect_nonce"] = Value::from(nonce);
            }
        }
    }
    Ok(reply)
}

fn read_request(input: &mut impl Read) -> Result<(), ()> {
    let mut prefix = [0u8; 4];
    input.read_exact(&mut prefix).map_err(|_| ())?;
    let length = u32::from_ne_bytes(prefix) as usize;
    if length == 0 || length > 1024 {
        return Err(());
    }
    let mut data = vec![0; length];
    input.read_exact(&mut data).map_err(|_| ())?;
    let request: Value = serde_json::from_slice(&data).map_err(|_| ())?;
    if request != json!({"type": "discover", "protocol": 1}) {
        return Err(());
    }
    Ok(())
}

fn serve(input: &mut impl Read, output: &mut impl Write, origin: &str, dir: Option<PathBuf>) {
    let result = read_request(input)
        .and_then(|_| discover(origin, &dir.ok_or(())?))
        .unwrap_or_else(|_| json!({"error": "desktop-unavailable", "protocol": 1}));
    if let Ok(data) = serde_json::to_vec(&result) {
        let _ = output.write_all(&(data.len() as u32).to_ne_bytes());
        let _ = output.write_all(&data);
        let _ = output.flush();
    }
}

pub fn run_if_requested() -> bool {
    let Some(origin) = std::env::args()
        .nth(1)
        .filter(|v| v.starts_with("chrome-extension://"))
    else {
        return false;
    };
    let host_directory = std::env::var_os("VAULT_BROWSER_DISCOVERY_DIR")
        .map(PathBuf::from)
        .or_else(registered_directory)
        .or_else(directory);
    serve(
        &mut std::io::stdin().lock(),
        &mut std::io::stdout().lock(),
        &origin,
        host_directory,
    );
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_oversize_truncated_and_wrong_requests_without_opening_desktop() {
        for mut bytes in [
            vec![255; 4],
            vec![2, 0, 0, 0, b'{'],
            vec![2, 0, 0, 0, b'{', b'}'],
        ] {
            let mut out = vec![];
            serve(
                &mut bytes.as_slice(),
                &mut out,
                "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/",
                None,
            );
            let len = u32::from_ne_bytes(out[..4].try_into().unwrap()) as usize;
            assert_eq!(len, out.len() - 4);
            assert_eq!(
                serde_json::from_slice::<Value>(&out[4..]).unwrap()["error"],
                "desktop-unavailable"
            );
            bytes.clear();
        }
    }
    #[test]
    fn releases_the_connect_nonce_only_to_allowed_origins_of_the_live_instance() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        std::thread::spawn(move || {
            for stream in listener.incoming().take(2) {
                let mut stream = stream.unwrap();
                let mut request = [0u8; 1024];
                let _ = stream.read(&mut request);
                let body = r#"{"protocol":1,"instance_id":"generated-instance"}"#;
                let _ = write!(stream, "HTTP/1.1 200 OK
Content-Length: {}

{body}", body.len());
            }
        });
        let temp = tempfile::tempdir().unwrap();
        let allowed = "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let write = |name: &str, value: Value| std::fs::write(temp.path().join(name), value.to_string()).unwrap();
        write("native-host.json", json!({"name": "org.vaultunified.desktop", "allowed_origins": [format!("{allowed}/")]}));
        write("runtime.json", json!({"protocol": 1, "base_url": format!("http://127.0.0.1:{port}/api"), "instance_id": "generated-instance"}));
        write("connect.json", json!({"instance_id": "generated-instance", "connect_nonce": "generated-nonce"}));
        assert!(discover("chrome-extension://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", temp.path()).is_err());
        assert_eq!(discover(allowed, temp.path()).unwrap()["connect_nonce"], "generated-nonce");
        write("connect.json", json!({"instance_id": "older-instance", "connect_nonce": "stale-nonce"}));
        assert!(discover(allowed, temp.path()).unwrap().get("connect_nonce").is_none());
    }
    #[test]
    fn validates_chromium_origins() {
        assert!(valid_origin(
            "chrome-extension://abcdefghijklmnopabcdefghijklmnop/"
        ));
        assert!(!valid_origin("https://abcdefghijklmnopabcdefghijklmnop/"));
        assert!(!valid_origin("chrome-extension://../../etc"));
    }
    #[test]
    fn uninstall_registration_must_belong_to_this_executable() {
        let temp = tempfile::tempdir().unwrap();
        let this = temp.path().join("installed.exe");
        let other = temp.path().join("other.exe");
        std::fs::write(&this, b"generated").unwrap();
        std::fs::write(&other, b"generated").unwrap();
        let manifest = temp.path().join("native-host.json");
        for (path, name, expected) in [(&this, "org.vaultunified.desktop", true), (&other, "org.vaultunified.desktop", false), (&this, "another.host", false)] {
            std::fs::write(&manifest, json!({"name": name, "path": path}).to_string()).unwrap();
            assert_eq!(manifest_belongs_to(&manifest, &this), expected);
        }
        std::fs::write(&manifest, b"invalid").unwrap();
        assert!(!manifest_belongs_to(&manifest, &this));
    }
}
