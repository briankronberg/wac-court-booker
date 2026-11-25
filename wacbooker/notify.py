"""The log file and Windows toasts.

Toasts use an app ID registered under HKCU so they show as "WAC Court Booker".
When nobody is signed in there's no desktop to show them on; the log and
results file are always written.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys

from . import APP_NAME, paths

AUMID = "WACCourtBooker"
_log: logging.Logger | None = None


def logger() -> logging.Logger:
    global _log
    if _log is None:
        paths.ensure()
        _log = logging.getLogger("wacbooker")
        _log.setLevel(logging.INFO)
        h = logging.handlers.RotatingFileHandler(paths.log_file(), maxBytes=2_000_000, backupCount=5,
                                                 encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        _log.addHandler(h)
    return _log


def register_app_id() -> None:
    """Toast sender name. HKCU only, no admin rights needed."""
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              rf"Software\Classes\AppUserModelId\{AUMID}") as k:
            winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(k, "ShowInSettings", 0, winreg.REG_DWORD, 1)
    except OSError:
        pass


def toast(title: str, body: str) -> bool:
    """Show a toast. Returns False (and logs why) if Windows wouldn't show one."""
    if sys.platform != "win32":
        return False
    try:
        register_app_id()
        from windows_toasts import InteractableWindowsToaster, Toast
        t = Toast()
        t.text_fields = [title, body]
        InteractableWindowsToaster(APP_NAME, notifierAUMID=AUMID).show_toast(t)
        return True
    except Exception as e:  # noqa: BLE001 -- no interactive session, notifications off, etc.
        logger().info(f"toast not shown ({type(e).__name__}: {str(e)[:120]})")
        return False
