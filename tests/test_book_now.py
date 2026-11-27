"""Book Now: when it's allowed, the run itself and the page's job (offline)."""
import asyncio
from datetime import timedelta

from wacbooker import clubtime, config, runner, web

from fakes import FakeClock, FakeSite
from test_web import add_login, call, srv  # noqa: F401  (fixture)


def one_off(days, minutes, play="doubles", partners=("Pat Lee", "Sam Ortiz", "Kim Park"), length=90):
    d = (clubtime.now_central() + timedelta(days=days)).date()
    errs = []
    b = config.parse_booking({"name": "n", "login": "me", "play": play, "partners": list(partners), "date": d.isoformat(),
                              "time": clubtime.fmt_time(minutes), "length": length, "courts": [5, "any"]}, 1, errs)
    assert not errs, errs
    return b


def test_block_reasons():
    now = clubtime.now_central()
    assert runner.book_now_block(one_off(3, 18 * 60), now) is None                   # inside 169 h
    assert "opens" in runner.book_now_block(one_off(9, 18 * 60), now)                # a week and more away
    past = one_off(0, 5 * 60)
    if clubtime.slot_start(past.date, past.time) <= now:
        assert "already started" in runner.book_now_block(past, now)
    # Prime Time singles open only 24 hours ahead: 3 days out isn't open yet.
    d = (now + timedelta(days=3)).date()
    while d.weekday() > 3:
        d += timedelta(days=1)
    errs = []
    b = config.parse_booking({"name": "n", "login": "me", "play": "singles", "partners": ["Pat Lee"], "date": d.isoformat(),
                              "time": "6:00 PM", "length": 60, "courts": ["any"]}, 1, errs)
    assert "opens" in runner.book_now_block(b, now)


def test_book_now_books_straight_away(monkeypatch):
    clock = FakeClock(clubtime.now_central().timestamp())
    site = FakeSite(clock, clock.now(), gate_s=0)

    async def close():
        site.calls.append("close")
    site.close = close

    async def start(cfg, login, log):
        return site
    monkeypatch.setattr(runner, "start_site", start)
    monkeypatch.setattr(runner, "keep_family", lambda *a: None)
    rec = []
    monkeypatch.setattr(runner.results, "record", lambda *a, **k: rec.append((a, k)))
    monkeypatch.setattr(runner.notify, "toast", lambda *a, **k: None)
    said = []
    out = asyncio.run(runner.book_now(None, one_off(3, 18 * 60), None, said.append, clock))
    assert out == "booked" and len(site.booked) == 1 and "close" in site.calls and site.booked[0].court == 5
    assert rec[0][0][0] == "book-now" and rec[0][0][2] == "booked"
    assert any(x.startswith("Booked") for x in said)
    assert clock.slept < 60  # no waiting for a window


def test_page_job_checks_first(srv, monkeypatch):  # noqa: F811
    add_login(srv)
    from test_availability import REAL_JOB_WORK, wait_job
    monkeypatch.setattr(web.WebApp, "_job_work", REAL_JOB_WORK)
    d3 = (clubtime.now_central() + timedelta(days=3)).date().isoformat()
    d10 = (clubtime.now_central() + timedelta(days=10)).date().isoformat()
    body = {"kind": "book-now", "play": "doubles", "partners": ["Pat Lee", "Sam Ortiz", "Kim Park"], "date": d3,
            "time": 18 * 60, "length": 90, "courts": [5, "any"]}
    _, r = call(srv, "/api/job", body)
    assert not r["ok"] and "Confirm" in r["errors"][0]
    _, r = call(srv, "/api/job", {**body, "date": d10, "confirmed": True})
    assert not r["ok"] and "isn't open yet" in r["errors"][0]
    _, r = call(srv, "/api/job", {**body, "partners": ["Pat Lee"], "confirmed": True})
    assert not r["ok"] and "3 partners" in r["errors"][0]
    ran = []

    async def fake(cfg, b, login, say, clock=None):
        ran.append((b.date.isoformat(), b.time, b.name))
        return "booked"
    monkeypatch.setattr(runner, "book_now", fake)
    _, r = call(srv, "/api/job", {**body, "confirmed": True})
    j = wait_job(srv, r["job"]["id"])
    assert j["ok"] and ran and ran[0][:2] == (d3, 18 * 60)
