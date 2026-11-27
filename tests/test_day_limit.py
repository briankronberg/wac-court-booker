"""The club's daily limit and clashes with the login's own reservations (offline)."""
import asyncio
from datetime import date

from wacbooker import engine, runner
from wacbooker.engine import Engine, day_conflict

from fakes import FakeClock, FakeSite, booking, occurrence
from test_availability import FakeApi, table

D = "12/15/2026"  # a Tuesday


def res(start, end, d=D):
    return {"guid": "g", "date": d, "start": start, "end": end, "court": 5, "machine": None}


def test_day_conflict():
    assert day_conflict([], D, 1080, 1170) is None
    assert day_conflict([res(420, 510)], D, 1080, 1170) is None
    assert day_conflict([res(420, 510), res(1170, 1260, "12/16/2026")], D, 1080, 1170) is None
    assert "2 reservations on Tue 12/15" in day_conflict([res(420, 510), res(510, 600)], D, 1080, 1170)
    assert "from 6:30 PM to 8:00 PM on Tue 12/15" in day_conflict([res(1110, 1200)], D, 1080, 1170)
    assert day_conflict([res(1170, 1260)], D, 1080, 1170) is None  # back to back is fine


def run(mine):
    occ = occurrence()
    W = occ.window.timestamp()
    clock = FakeClock(W - 75 * 60)
    site = FakeSite(clock, W, mine=mine)
    return asyncio.run(Engine(booking(), occ, site, clock).run()), site


def test_full_day_stops_before_staging():
    r, site = run([res(420, 510), res(510, 600)])
    assert r.status == "not_booked" and "the club's limit" in r.message and "Cancel one" in r.message
    assert not [c for c in site.calls if c.startswith("stage")] and site.presses == 0


def test_clash_stops_before_staging():
    r, site = run([res(1080, 1170)])
    assert r.status == "not_booked" and "already have a reservation from 6:00 PM" in r.message


def test_one_other_reservation_still_books():
    r, _ = run([res(420, 510)])
    assert r.status == "booked"


def test_unreadable_report_still_books():
    r, site = run(None)
    assert r.status == "booked" and "my-reservations" in site.calls


def test_validate_booking_warns_about_a_full_day():
    lines = []
    t = {**table(), "mine": [res(420, 510, "12/04/2026"), res(510, 600, "12/04/2026")]}
    out = asyncio.run(runner.court_check_on(FakeApi(t), date(2026, 12, 4), 1080, [60], ["any"], lines.append))
    assert "club's limit" in out["conflict"] and lines[-1].startswith("But you already have 2 reservations")
    lines.clear()
    out = asyncio.run(runner.court_check_on(FakeApi(table()), date(2026, 12, 4), 1080, [60], ["any"], lines.append))
    assert out["conflict"] is None and not lines[-1].startswith("But")


def test_test_booking_skips_a_full_day(monkeypatch):
    from datetime import datetime, timedelta
    from wacbooker import clubtime
    from wacbooker.engine import Attempt, Slot
    now = clubtime.now_central()
    d2, d3 = [(now + timedelta(days=n)).strftime("%m/%d/%Y") for n in (2, 3)]

    class Site:
        staged = None

        async def login(self):
            return "Test Member"

        async def reservations(self, frm, to, family=False):
            return [res(420, 510, d2), res(510, 600, d2)]

        async def list_open(self, d, length, play):
            return [Slot(d, 600, 30, 5)]

        async def stage(self, slot):
            self.staged = slot

        async def attempt(self, partners, force=False):
            return Attempt(engine.CONFIRMED, "guid")

        async def reservation_exists(self, slot):
            return True

        async def close(self):
            pass
    site = Site()

    async def start(cfg, login, log):
        return site
    monkeypatch.setattr(runner, "start_site", start)
    monkeypatch.setattr(runner, "keep_family", lambda *a: None)
    monkeypatch.setattr(runner.results, "record", lambda *a, **k: None)
    out = asyncio.run(runner.test_booking(None, None, "singles", [], ["any"], lambda m: None, lambda q: False))
    assert out == "kept" and site.staged.date == d3


def test_day_conflict_reads_the_reports_unpadded_dates():
    from wacbooker.engine import day_conflict
    rows = [{"date": "12/4/2026", "start": 13 * 60 + 30, "end": 14 * 60 + 30}]
    assert day_conflict(rows, "12/04/2026", 14 * 60, 15 * 60)  # overlaps 1:30-2:30 PM
    two = rows + [{"date": "12/4/2026", "start": 8 * 60, "end": 9 * 60}]
    assert "2 reservations" in day_conflict(two, "12/04/2026", 18 * 60, 19 * 60)
