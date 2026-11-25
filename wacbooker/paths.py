"""Where the app keeps its files.

Everything lives in one folder, by default ``%LOCALAPPDATA%\\WAC Court Booker``
(set WACB_HOME to use another folder, e.g. for tests). Setup creates it from a
normal process so Task Scheduler sees the same files as the person does.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import APP_NAME


def home() -> Path:
    override = os.environ.get("WACB_HOME")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME


def config_file() -> Path:
    return home() / "bookings.yaml"


def logs_dir() -> Path:
    return home() / "logs"


def log_file() -> Path:
    return logs_dir() / "wac-booker.log"


def results_file() -> Path:
    return home() / "results.jsonl"


def buddies_file() -> Path:
    return home() / "buddies.json"


def browsers_dir() -> Path:
    """Playwright's own Chromium, downloaded by setup."""
    return home() / "browsers"


def profile_dir(browser: str) -> Path:
    """Separate Edge/Chrome profile: never the person's everyday one."""
    return home() / f"profile-{browser}"


def locks_dir() -> Path:
    return home() / "locks"


def venv_dir() -> Path:
    return home() / "venv"


def ensure() -> Path:
    for d in (home(), logs_dir(), locks_dir()):
        d.mkdir(parents=True, exist_ok=True)
    return home()
