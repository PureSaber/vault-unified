//! Real Tauri updater transport/signature tests with ephemeral signing keys.
use serde_json::json;
use std::{
    io::{Read, Write},
    net::TcpListener,
    path::Path,
    process::Command,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::Duration,
};
use tauri_plugin_updater::UpdaterExt;

fn cli(args: &[&str]) {
    let script =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../node_modules/@tauri-apps/cli/tauri.js");
    let output = Command::new("node")
        .arg(script)
        .args(args)
        .output()
        .expect("Signing fixture CLI must run");
    assert!(output.status.success(), "Generated signing fixture failed");
}

#[test]
fn real_updater_rejects_tamper_wrong_version_missing_version_and_rollback() {
    let dir = tempfile::tempdir().unwrap();
    let key = dir.path().join("generated.key");
    let artifact = dir.path().join("generated-setup.exe");
    cli(&[
        "signer",
        "generate",
        "--ci",
        "--write-keys",
        key.to_str().unwrap(),
    ]);
    let payload = b"generated nonexecutable update fixture";
    std::fs::write(&artifact, payload).unwrap();
    cli(&[
        "signer",
        "sign",
        "--private-key-path",
        key.to_str().unwrap(),
        "--password",
        "",
        "--app-version",
        "99.0.0",
        artifact.to_str().unwrap(),
    ]);
    let signature = std::fs::read_to_string(artifact.with_extension("exe.sig")).unwrap();
    cli(&[
        "signer",
        "sign",
        "--private-key-path",
        key.to_str().unwrap(),
        "--password",
        "",
        artifact.to_str().unwrap(),
    ]);
    let legacy = std::fs::read_to_string(artifact.with_extension("exe.sig")).unwrap();
    let public = std::fs::read_to_string(key.with_extension("key.pub")).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    listener.set_nonblocking(true).unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let service_base = base.clone();
    let stopped = Arc::new(AtomicBool::new(false));
    let service_stopped = stopped.clone();
    let service = std::thread::spawn(move || {
        while !service_stopped.load(Ordering::Acquire) {
            let Ok((mut stream, _)) = listener.accept() else {
                std::thread::sleep(Duration::from_millis(5));
                continue;
            };
            stream
                .set_read_timeout(Some(Duration::from_secs(5)))
                .unwrap();
            let mut data = [0u8; 8192];
            let count = stream.read(&mut data).unwrap();
            let request = String::from_utf8_lossy(&data[..count]);
            let path = request.split_whitespace().nth(1).unwrap();
            let body = if path.ends_with(".exe") {
                if path.contains("tampered") {
                    b"generated changed payload".to_vec()
                } else {
                    payload.to_vec()
                }
            } else {
                json!({"version": if path == "/wrong-version" { "99.0.1" } else if path == "/old" { "0.0.0" } else { "99.0.0" },
                    "url": format!("{service_base}/{}-setup.exe", if path == "/tampered" { "tampered" } else { "good" }),
                    "signature": if path == "/legacy" { &legacy } else { &signature }}).to_string().into_bytes()
            };
            write!(stream, "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", body.len()).unwrap();
            stream.write_all(&body).unwrap();
        }
    });
    let mut context = tauri::test::mock_context(tauri::test::noop_assets());
    context.config_mut().plugins.0.insert("updater".into(), json!({"pubkey": public.trim(), "dangerousInsecureTransportProtocol": true, "requireSignedVersion": true}));
    let app = tauri::test::mock_builder()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .build(context)
        .unwrap();
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        tauri::async_runtime::block_on(async {
            for scenario in ["good", "tampered", "wrong-version", "legacy", "old"] {
                let checked = app
                    .updater_builder()
                    .no_proxy()
                    .timeout(Duration::from_secs(5))
                    .endpoints(vec![format!("{base}/{scenario}").parse().unwrap()])
                    .unwrap()
                    .build()
                    .unwrap()
                    .check()
                    .await
                    .unwrap();
                if scenario == "old" {
                    assert!(checked.is_none());
                    continue;
                }
                let update = checked.unwrap();
                let downloaded = update.download(|_, _| {}, || {}).await;
                if scenario == "good" {
                    assert_eq!(downloaded.as_ref().unwrap(), payload);
                    assert!(
                        update.install(downloaded.unwrap()).is_err(),
                        "Signed noninstaller fixture must not launch"
                    );
                } else {
                    assert!(
                        downloaded.is_err(),
                        "Untrusted update must be rejected: {scenario}"
                    );
                }
            }
        })
    }));
    stopped.store(true, Ordering::Release);
    service.join().unwrap();
    if let Err(error) = result {
        std::panic::resume_unwind(error);
    }
}
