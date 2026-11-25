"""Check the PC clock against internet time (SNTP, with an HTTP Date fallback)."""
from __future__ import annotations

import socket
import struct
import time
import urllib.request
from email.utils import parsedate_to_datetime

NTP_SERVERS = ("time.windows.com", "pool.ntp.org", "time.google.com")
NTP_EPOCH = 2208988800


def sntp_offset(server: str, timeout: float = 3.0) -> tuple[float, float]:
    """(offset, round trip) in seconds; offset = internet time - PC time."""
    pkt = b"\x1b" + 47 * b"\0"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        t1 = time.time()
        s.sendto(pkt, (server, 123))
        data, _ = s.recvfrom(512)
        t4 = time.time()
    if len(data) < 48:
        raise OSError("short NTP reply")

    def ts(off: int) -> float:
        sec, frac = struct.unpack("!II", data[off:off + 8])
        return sec - NTP_EPOCH + frac / 2 ** 32

    t2, t3 = ts(32), ts(40)
    return ((t2 - t1) + (t3 - t4)) / 2, (t4 - t1) - (t3 - t2)


def http_offset(url: str = "https://hnd-p-ols.spectrumng.net/LCRAC/Login.aspx") -> float:
    """Coarse (about +-0.5 s): the club server's own Date header."""
    t1 = time.time()
    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=10) as r:
        date = r.headers.get("Date")
    t2 = time.time()
    return parsedate_to_datetime(date).timestamp() + 0.5 - (t1 + t2) / 2


def measure() -> tuple[float | None, str]:
    """(offset seconds or None, where it came from). Best of a few SNTP replies."""
    best: tuple[float, float, str] | None = None
    for server in NTP_SERVERS:
        for _ in range(2):
            try:
                off, rtt = sntp_offset(server)
            except OSError:
                break
            if best is None or rtt < best[1]:
                best = (off, rtt, server)
        if best and best[1] < 0.2:
            break
    if best:
        return best[0], best[2]
    try:
        return http_offset(), "the club site's clock"
    except Exception:  # noqa: BLE001
        return None, "nothing (no internet time reachable)"


def report(limit: float = 2.0) -> tuple[bool, str]:
    off, src = measure()
    if off is None:
        return False, "Couldn't reach internet time. Check the internet connection."
    ahead = "ahead" if off < 0 else "behind"
    msg = f"The PC clock is {abs(off):.2f} s {ahead} of internet time ({src})."
    if abs(off) > limit:
        return False, msg + (" That's more than 2 seconds. Bookings correct for it, but turn on "
                             "'Set time automatically' in Windows Settings > Time & language.")
    return True, msg + " That's fine."
