# External integration credential storage

Vault Unified separates secret credentials from ordinary integration configuration.

## Storage locations

Secret fields are stored through the Python `keyring` package under the service
`vault-unified.integrations`. On the supported Windows desktop this resolves to Windows
Credential Manager. Examples include:

- Bitwarden client secret and master password;
- KeePassXC database master password;
- Proton Pass personal access token.

The API never returns those values. It reports only whether a value is present and whether it
came from the OS keyring or an explicit environment fallback.

Non-secret values such as database paths, server URLs, groups, share IDs, and vault names are
stored at:

```text
%LOCALAPPDATA%\VaultUnified\config\integrations.json
```

The file uses the same atomic writer and recovery boundary as other managed local metadata.
Its validator rejects unknown sources, unknown fields, non-text values, and every field marked
secret by the reviewed integration schema.

## Desktop workflow

After unlocking the local vault, open **Settings → External password-manager connections**.
For each source you can:

1. enter or replace fields;
2. save secrets to the OS credential manager;
3. test the official CLI connection;
4. clear all Keyring and local configuration for that source.

A blank secret input preserves the currently stored secret. The UI never fills the secret
input with its actual value.

## Environment compatibility

Environment variables and `.env` remain a read-only compatibility fallback for deliberate
headless development or automation. Keyring/config values take precedence. Clearing a desktop
connection does not mutate the parent process environment; if a field still reports origin
`environment`, remove that variable or `.env` entry yourself.

`configure-integrations.ps1` no longer asks for secrets or writes `.env`; it opens the desktop
connection manager. Existing `.env` files are not deleted automatically because doing so could
break a reviewed headless workflow.

## Subprocess boundary

Adapters construct a per-source subprocess environment at call time. Secrets are not written
back into global process environment variables. Failed CLI output is redacted by the common
adapter runner, and Proton Pass no longer falls back to putting a password directly in process
arguments when an old CLI lacks password-file support.
