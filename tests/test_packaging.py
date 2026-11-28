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


def test_the_app_icon_is_a_packaged_ico():
    import struct
    import wacbooker
    ico = Path(wacbooker.__file__).resolve().parent / "web" / "app.ico"
    data = ico.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1) and count >= 5
    sizes = {data[6 + 16 * i] or 256 for i in range(count)}
    assert {16, 32, 48, 256} <= sizes
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]
    assert "*.ico" in cfg["package-data"]["wacbooker.web"]


def test_setup_gives_the_shortcuts_the_icon():
    text = (ROOT / "setup.ps1").read_text(encoding="utf-8")
    start = text.index("function Save-Shortcut")
    assert "IconLocation" in text[start:start + 800]
