fn main() {
    if std::env::args().nth(1).as_deref() == Some("--unregister-browser-host") {
        std::process::exit(if vault_unified_desktop_lib::native_host::unregister() { 0 } else { 1 });
    }
    if vault_unified_desktop_lib::native_host::run_if_requested() {
        return;
    }
    vault_unified_desktop_lib::run()
}
