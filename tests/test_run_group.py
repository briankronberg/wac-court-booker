"""Coordinated logins, end to end: every login in a booking books at the same time."""
import asyncio
from datetime import date, timedelta

from fakes import FakeClock, FakeSite, booking as fake_booking, occurrence
from wacbooker import clubtime, config, creds, results, runner
from wacbooker.config import Member
from wacbooker.engine import RunResult, Slot

CFG = """\
browser: hidden
logins:
  - nickname: me
    username: jsmith
  - nickname: partner
    username: asmith
bookings:
  - name: Tuesday together
    login: me
    also:
      - login: partner
        partners: [Andrea Kronberg, Dan Ford, Eli Grant]
    play: doubles
    partners: [Pat Lee, Sam Ortiz, Kim Park]
    day: Tuesday
    time: "6:00 PM"
    length: 90
    courts: [any]
    active: true
"""


def cfg_from(tmp_path, text):
    p = tmp_path / "bookings.yaml"
    p.write_text(text, encoding="utf-8")
    _, cfg = config.load(p)
    assert cfg.ok, cfg.errors
    return cfg


def test_run_group_books_different_side_by_side_courts(tmp_path, monkeypatch):
    cfg = cfg_from(tmp_path, CFG)
    b = cfg.booking("Tuesday together")
    occ = occurrence()
    clock = FakeClock(occ.window.timestamp() - 75 * 60)
    sites = []

    async def start(c, lg, log):
        s = FakeSite(clock, clock.now(), gate_s=0, open_courts={90: [3, 4, 5]})
        sites.append(s)
        return s

    monkeypatch.setattr(runner, "start_site", start)
    monkeypatch.setattr(runner, "keep_family", lambda lg, s: None)

    out = asyncio.run(runner.run_group(cfg, b, occ, clock, lambda m: None))

    assert [r.status for r in out.values()] == ["booked", "booked"]
    assert sorted(out[m.login].slot.court for m in b.members) == [3, 4]
    assert [len(s.booked) for s in sites] == [1, 1]


def test_main_part_court_belongs_to_a_login(tmp_path, monkeypatch):
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    d = date(2026, 12, 15)
    results.record("run", "g", "booked", "x", part="main", day=d.isoformat(), login="me", court=3)
    results.record("run", "g", "booked", "x", part="main", day=d.isoformat(), login="partner", court=4)
    assert runner.main_part_court("g", d, "me", "me") == 3
    assert runner.main_part_court("g", d, "partner", "me") == 4
    # records written before coordinated logins existed have no login: they are the booking's own
    results.record("run", "old", "booked", "x", part="main", day=d.isoformat(), court=5)
    assert runner.main_part_court("old", d, "me", "me") == 5
    assert runner.main_part_court("old", d, "partner", "me") is None


def test_finish_group_records_each_member_and_toasts_once(monkeypatch):
    recs, toasts = [], []
    monkeypatch.setattr("wacbooker.results.record", lambda *a, **k: recs.append((a, k)))
    monkeypatch.setattr("wacbooker.notify.toast", lambda t, m: toasts.append((t, m)))
    b = fake_booking(also=[Member("partner", ["Andrea Kronberg", "Dan Ford", "Eli Grant"])])
    occ = occurrence()
    out = {
        "me": RunResult("booked", "Booked: Ct 3, Tue 12/15 6:00 PM, 90 min", Slot("12/15/2026", 18 * 60, 90, 3)),
        "partner": RunResult("booked", "Booked: Ct 4, Tue 12/15 6:00 PM, 90 min", Slot("12/15/2026", 18 * 60, 90, 4)),
    }
    rc = runner._finish_group(b, "main", occ, out, lambda m: None)
    assert rc == 0
    assert [(a[0], a[1], k.get("login"), k.get("part")) for a, k in recs] == [
        ("run", "Tue doubles", "me", "main"), ("run", "Tue doubles", "partner", "main")]
    assert toasts == [("Booked", "Ct 3 for me \u00b7 Ct 4 for partner")]


def test_run_booking_group_needs_every_members_password(tmp_path, monkeypatch):
    cfg = cfg_from(tmp_path, CFG)
    b = cfg.booking("Tuesday together")
    b.due = lambda now, part="main": occurrence()
    recs, toasts = [], []
    monkeypatch.setattr("wacbooker.results.record", lambda *a, **k: recs.append((a, k)))
    monkeypatch.setattr("wacbooker.notify.toast", lambda t, m: toasts.append((t, m)))
    monkeypatch.setattr(creds, "has_password", lambda u: False)
    monkeypatch.setattr("wacbooker.config.load", lambda *a, **k: (None, cfg))
    rc = runner.run_booking("Tuesday together")
    assert rc == 1
    assert any("partner" in m and "no saved password" in m for _, m in toasts)
    assert recs and recs[0][0][2] == "not_booked"


def test_book_now_books_a_group(tmp_path, monkeypatch):
    day = clubtime.now_central().date() + timedelta(days=3)
    cfg = cfg_from(tmp_path, CFG.replace("day: Tuesday", f"date: {day.isoformat()}"))
    b = cfg.booking("Tuesday together")
    clock = FakeClock(0.0)
    sites, recs, toasts, said = [], [], [], []
    monkeypatch.setattr("wacbooker.results.record", lambda *a, **k: recs.append((a, k)))
    monkeypatch.setattr("wacbooker.notify.toast", lambda t, m: toasts.append((t, m)))

    async def start(c, lg, log):
        s = FakeSite(clock, clock.now(), gate_s=0, open_courts={90: [3, 4, 5]})
        sites.append(s)
        return s

    monkeypatch.setattr(runner, "start_site", start)
    monkeypatch.setattr(runner, "keep_family", lambda lg, s: None)
    out = asyncio.run(runner.book_now(cfg, b, cfg.login("me"), said.append, clock=clock))
    assert out == "booked"
    bn = [(k.get("login"), k.get("court")) for a, k in recs if a[0] == "book-now"]
    assert sorted(bn) == [("me", 3), ("partner", 4)]
    assert [m for m in said if m.startswith("Booked:")]  # one plain message per member
    assert toasts and toasts[0][0] == "Booked"
