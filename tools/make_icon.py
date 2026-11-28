"""Makes wacbooker/web/app.ico from the tennis ball on the app's page. Run once when the picture changes."""
import os
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "wacbooker" / "web" / "app.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]
BALL = ('<circle cx="16" cy="16" r="14" fill="#c8dc3c"/>'
        '<path d="M5 9c6 3 6 11 0 14M27 9c-6 3-6 11 0 14" stroke="#fff" stroke-width="2" fill="none"/>')


def svg(size):
    return f'<svg width="{size}" height="{size}" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">{BALL}</svg>'


def render_pngs():
    """Render the ball at each size as a PNG with a transparent background."""
    browsers = Path(os.environ.get("LOCALAPPDATA", "")) / "WAC Court Booker" / "browsers"
    if browsers.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)
    from playwright.sync_api import sync_playwright

    pngs = {}
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception:
            browser = p.chromium.launch(channel="msedge", headless=True)
        try:
            page = browser.new_page()
            for size in SIZES:
                page.set_content(
                    "<!doctype html><html><head><style>html,body{margin:0;background:transparent}</style>"
                    f"</head><body>{svg(size)}</body></html>")
                pngs[size] = page.locator("svg").screenshot(omit_background=True)
        finally:
            browser.close()
    return pngs


def write_ico(pngs, path):
    """An ICO file that embeds PNG images directly (valid on Windows Vista and later)."""
    items = sorted(pngs.items())
    data = struct.pack("<HHH", 0, 1, len(items))
    offset = 6 + 16 * len(items)
    entries = b""
    images = b""
    for size, png in items:
        dim = size if size < 256 else 0
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        images += png
        offset += len(png)
    path.write_bytes(data + entries + images)


if __name__ == "__main__":
    write_ico(render_pngs(), OUT)
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")
