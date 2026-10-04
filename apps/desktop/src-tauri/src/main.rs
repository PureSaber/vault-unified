fn main() {
    if vault_unified_desktop_lib::native_host::run_if_requested() {
        return;
    }
    vault_unified_desktop_lib::run()
}
