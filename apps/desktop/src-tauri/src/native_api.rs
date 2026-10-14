use crate::{ApiRuntimeConfig, ApiSidecar};
use serde_json::Value;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::Duration;
use tauri::Manager;
use zeroize::Zeroizing;

pub fn request(
    app: &tauri::AppHandle,
    method: &str,
    path: &str,
    body: &str,
    token: Option<&str>,
    timeout: Duration,
) -> Result<Value, String> {
    call(
        &app.state::<ApiSidecar>().config,
        method,
        path,
        body,
        token,
        timeout,
    )
}

fn call(
    config: &ApiRuntimeConfig,
    method: &str,
    path: &str,
    body: &str,
    token: Option<&str>,
    timeout: Duration,
) -> Result<Value, String> {
    let run = || -> Result<Value, String> {
        let authority = config
            .base_url
            .strip_prefix("http://")
            .and_then(|value| value.strip_suffix("/api"))
            .ok_or("hello_unavailable")?;
        let address: SocketAddr = authority.parse().map_err(|_| "hello_unavailable")?;
        if !address.ip().is_loopback()
            || !["POST", "DELETE"].contains(&method)
            || ![
                "/auth/hello/prepare",
                "/auth/hello/unlock",
                "/auth/hello",
                "/auth/lock",
                "/auth/system-state",
                "/entries/tools/auto-type",
            ]
            .contains(&path)
        {
            return Err("hello_unavailable".into());
        }
        if token.is_some_and(|value| {
            value.len() != 36
                || !value
                    .bytes()
                    .all(|byte| byte.is_ascii_hexdigit() || byte == b'-')
        }) {
            return Err("hello_needs_master".into());
        }
        let mut stream =
            TcpStream::connect_timeout(&address, timeout).map_err(|_| "hello_unavailable")?;
        stream
            .set_read_timeout(Some(timeout))
            .map_err(|_| "hello_unavailable")?;
        stream
            .set_write_timeout(Some(timeout))
            .map_err(|_| "hello_unavailable")?;
        let authorization = Zeroizing::new(
            token
                .map(|value| format!("Authorization: Bearer {value}\r\n"))
                .unwrap_or_default(),
        );
        let message = Zeroizing::new(format!("{method} /api{path} HTTP/1.1\r\nHost: {authority}\r\nX-Vault-Bootstrap: {}\r\nX-Vault-Native: {}\r\nX-Vault-Client: vault-unified-desktop\r\n{}Content-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", config.bootstrap_secret, config.native_secret, &*authorization, body.len()));
        stream
            .write_all(message.as_bytes())
            .map_err(|_| "hello_unavailable")?;
        let mut response = Zeroizing::new(Vec::new());
        stream
            .take(65_536)
            .read_to_end(&mut response)
            .map_err(|_| "hello_unavailable")?;
        let split = response
            .windows(4)
            .position(|value| value == b"\r\n\r\n")
            .ok_or("hello_unavailable")?;
        let header = std::str::from_utf8(&response[..split]).map_err(|_| "hello_unavailable")?;
        let status = header
            .lines()
            .next()
            .and_then(|value| value.split_whitespace().nth(1))
            .ok_or("hello_unavailable")?;
        if status != "200" {
            return Err(match status {
                "401" | "409" => "hello_needs_master",
                "423" => "hello_cancelled",
                _ => "hello_unavailable",
            }
            .into());
        }
        serde_json::from_slice(&response[split + 4..]).map_err(|_| "hello_unavailable".into())
    };
    run()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn native_capability_is_never_serialized_to_the_renderer() {
        let config = ApiRuntimeConfig {
            base_url: "http://127.0.0.1:1234/api".into(),
            bootstrap_secret: "generated-bootstrap".into(),
            instance_id: "generated-instance".into(),
            native_secret: "generated-native-only".into(),
        };
        let value = serde_json::to_value(&config).unwrap();
        assert_eq!(value.as_object().unwrap().len(), 3);
        assert!(value.get("native_secret").is_none());
        assert_eq!(
            call(
                &config,
                "POST",
                "/auth/hello/prepare",
                "{}",
                Some("bad\r\nheader"),
                Duration::from_millis(1)
            )
            .unwrap_err(),
            "hello_needs_master"
        );
    }
}
