"""Check the PC clock against internet time (SNTP, with an HTTP Date fallback)."""
from __future__ import annotations

import http.client
import socket
import struct
import time
import urllib.request
from email.utils import parsedate_to_datetime

CLUB_HOST = "hnd-p-ols.spectrumng.net"
CLUB_PATH = "/LCRAC/Login.aspx"

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


def server_offset(host: str = CLUB_HOST, path: str = CLUB_PATH, budget: float = 4.0,
                  conn_factory=None, now=time.time) -> tuple[float, float]:
    """(offset, uncertainty) in seconds: the club server's clock - PC time, to a fraction
    of a second. The Date header only has whole seconds, so ask quickly over one kept-open
    connection until it ticks over: the server's next second started between the two
    answers either side of the tick. Raises OSError if it can't be measured."""
    conn = (conn_factory or (lambda: http.client.HTTPSConnection(host, timeout=5)))()
    best: tuple[float, float] | None = None
    prev: tuple[float, float, int] | None = None   # (sent, answered, server second)
    end = now() + budget
    try:
        while now() < end:
            t1 = now()
            conn.request("HEAD", path, headers={"Connection": "keep-alive"})
            r = conn.getresponse()
            r.read()
            t2 = now()
            sec = int(parsedate_to_datetime(r.getheader("Date")).timestamp())
            if prev and sec == prev[2] + 1:
                # The server's second `sec` began after it stamped the previous answer
                # (no earlier than that request was sent) and before it stamped this one
                # (no later than this answer arrived).
                lo, hi = prev[0], t2
                off, unc = sec - (lo + hi) / 2, (hi - lo) / 2
                if best is None or unc < best[1]:
                    best = (off, unc)
                if unc < 0.15:
                    break
            prev = (t1, t2, sec)
    except (OSError, http.client.HTTPException, TypeError, ValueError) as e:
        if best is None:
            raise OSError(f"club clock not readable: {e}") from e
    finally:
        conn.close()
    if best is None:
        raise OSError("the club clock didn't tick over in time")
    return best


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
