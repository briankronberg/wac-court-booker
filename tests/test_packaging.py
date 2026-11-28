"""The page's HTML files must be part of the installed package, declared the way
setuptools expects (no 'absent from packages' warning when installing)."""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_web_files_are_a_declared_package():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]
    assert "wacbooker.web" in cfg["packages"]
    assert "*.html" in cfg["package-data"]["wacbooker.web"]
    for name in ("index.html", "calendar.html"):
        assert (ROOT / "wacbooker" / "web" / name).exists()
