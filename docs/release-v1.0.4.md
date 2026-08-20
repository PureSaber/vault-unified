# Vault Unified v1.0.4

This security release removes fixed-port desktop sidecar reuse. Each desktop launch now owns a fresh sidecar on an OS-assigned loopback port, and every API request requires a per-launch bootstrap secret. Tauri verifies the sidecar instance identity before exposing its runtime configuration, while renderer bearer tokens remain in memory only.

On Windows, the desktop process also owns the complete PyInstaller sidecar process tree through a kill-on-close Job Object.

This release does not migrate or otherwise change the encrypted vault format.
