"""The page's HTML files must be installed with the package, and declared the way
setuptools expects (no 'absent from packages' warning when installing). The page
check looks where the wacbooker package loads from, so it works both in the repo
and in an installed copy."""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_web_files_are_a_declared_package():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]
    assert "wacbooker.web" in cfg["packages"]
    assert "*.html" in cfg["package-data"]["wacbooker.web"]
    import wacbooker
    pages = Path(wacbooker.__file__).resolve().parent / "web"
    for name in ("index.html", "calendar.html"):
        assert (pages / name).exists(), pages / name
