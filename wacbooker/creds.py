"""Club passwords in Windows Credential Manager (via keyring). Never in a file or log."""
from __future__ import annotations

import keyring

from . import APP_NAME

SERVICE = APP_NAME


def _key(username: str) -> str:
    return username.strip().lower()


def set_password(username: str, password: str) -> None:
    keyring.set_password(SERVICE, _key(username), password)


def get_password(username: str) -> str:
    pw = keyring.get_password(SERVICE, _key(username))
    if not pw:
        raise LookupError(f"no saved password for '{username}'. Add the login again in the menu (7).")
    return pw


def has_password(username: str) -> bool:
    try:
        return bool(keyring.get_password(SERVICE, _key(username)))
    except Exception:  # noqa: BLE001 -- vault unreachable (e.g. no user profile loaded)
        return False


def delete_password(username: str) -> None:
    try:
        keyring.delete_password(SERVICE, _key(username))
    except keyring.errors.PasswordDeleteError:
        pass
