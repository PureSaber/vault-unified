from __future__ import annotations

SERVICE_NAME = "vault-unified"
ACCOUNT_NAME = "master-password"


def save_master_password(password: str) -> None:
    import keyring

    keyring.set_password(SERVICE_NAME, ACCOUNT_NAME, password)


def get_master_password() -> str | None:
    import keyring

    return keyring.get_password(SERVICE_NAME, ACCOUNT_NAME)


def clear_master_password() -> None:
    import keyring

    try:
        keyring.delete_password(SERVICE_NAME, ACCOUNT_NAME)
    except keyring.errors.PasswordDeleteError:
        pass


def is_remember_enabled() -> bool:
    return get_master_password() is not None
