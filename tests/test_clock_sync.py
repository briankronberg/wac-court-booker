import asyncio
from email.utils import formatdate

import pytest

from wacbooker import clock as clock_mod
from wacbooker.engine import Engine, RealClock

from fakes import FakeClock, FakeSite, booking, occurrence


class FakeConn:
    """A club server whose clock is `skew` seconds ahead of the PC; each answer takes `rtt`."""

    def __init__(self, t, skew, rtt=0.04):
        self.t, self.skew, self.rtt = t, skew, rtt
        self.stamp = None

    def request(self, *a, **k):
        self.t[0] += self.rtt / 2
        self.stamp = self.t[0] + self.skew   # the server stamps the answer halfway
        self.t[0] += self.rtt / 2

    def getresponse(self):
        stamp = self.stamp

        class R:
            def read(self):
                return b""

            def getheader(self, name):
                return formatdate(int(stamp), usegmt=True)
        return R()

    def close(self):
        pass


@pytest.mark.parametrize("skew", [1.3, -0.7, 0.05, 12.6])
def test_server_offset_finds_the_tick(skew):
    t = [1_800_000_000.25]
    off, unc = clock_mod.server_offset(conn_factory=lambda: FakeConn(t, skew), now=lambda: t[0])
    assert unc < 0.1
    assert off == pytest.approx(skew, abs=unc + 0.01)


def test_server_offset_raises_when_unreachable():
    class Dead:
        def request(self, *a, **k):
            raise OSError("no route")

        def close(self):
            pass
    with pytest.raises(OSError):
        clock_mod.server_offset(conn_factory=Dead, budget=0.5)


def test_real_clock_resync_moves_once():
    calls = []

    def measure():
        calls.append(1)
        return 2.0, 0.05

    rc = RealClock(0.0, measure=measure)
    before = rc.now()
    lines = []
    asyncio.run(rc.resync(lines.append))
    assert rc.now() - before == pytest.approx(2.0, abs=0.2)
    asyncio.run(rc.resync(lines.append))
    assert len(calls) == 1            # a second call right after does nothing
    assert "club clock" in lines[0]


def test_real_clock_resync_failure_keeps_time():
    def measure():
        raise OSError("timeout")
    rc = RealClock(0.5, measure=measure)
    before = rc.now()
    lines = []
    asyncio.run(rc.resync(lines.append))
    assert rc.now() - before == pytest.approx(0.0, abs=0.2)
    assert "failed" in lines[0]


class SyncClock(FakeClock):
    def __init__(self, t):
        super().__init__(t)
        self.synced_at = None

    async def resync(self, log):
        self.synced_at = self.t


def test_engine_resyncs_before_the_window():
    occ = occurrence()
    W = occ.window.timestamp()
    clk = SyncClock(W - 75 * 60)
    site = FakeSite(clk, W)
    res = asyncio.run(Engine(booking(), occ, site, clk).run())
    assert res.booked
    assert clk.synced_at is not None
    assert W - 110 < clk.synced_at < W - 8


def test_late_start_still_books_whats_open():
    occ = occurrence()
    W = occ.window.timestamp()
    clk = FakeClock(W + 10 * 60)          # the PC woke 10 minutes after the window
    site = FakeSite(clk, W, gate_s=0)
    res = asyncio.run(Engine(booking(), occ, site, clk).run())
    assert res.booked
    # presses start from now, one a second: no burst of catch-up presses
    assert site.press_times[0] > 10 * 60


def test_too_late_start_gives_up():
    occ = occurrence()
    W = occ.window.timestamp()
    clk = FakeClock(W + 25 * 60)
    site = FakeSite(clk, W)
    res = asyncio.run(Engine(booking(), occ, site, clk).run())
    assert res.status == "not_booked"
    assert "too late" in res.message
    assert site.presses == 0
