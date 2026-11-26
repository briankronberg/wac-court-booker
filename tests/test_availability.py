"""Court availability for one-off dates: the whole-day read, the check and the calendar jobs (offline)."""
import asyncio
import time
from datetime import date

from wacbooker import runner, site as S, web

from test_web import add_login, call, srv  # noqa: F401  (fixture)


def fake_grid(rows_by_start, page=15):
    """A load_grid stand-in: the day's open 30-minute slots, 15 rows a page from `start`."""
    rows = sorted(({"st": st, "et": st + 30, "r": str(c), "row": "", "court": c}
                   for st, cs in rows_by_start.items() for c in cs), key=lambda r: (r["st"], r["court"]))
    calls = []

    async def load_grid(svc, d, length, start):
        calls.append(start)
        frm = [r for r in rows if start is None or r["st"] >= start]
        return frm[:page]
    return load_grid, calls


def test_day_open_steps_through_the_whole_day():
    day = {390 + 30 * i: [2, 3, 4, 5, 6, 8, 9, 10] if i % 3 else [5] for i in range(30)}
    site = S.ClubSite("u", lambda: "", log=lambda m: None)
    site.load_grid, calls = fake_grid(day)
    slots = asyncio.run(site.day_open("12/05/2026"))
    want = {(st, c) for st, cs in day.items() for c in cs}
    assert {(s.start, s.court) for s in slots} == want
    assert len(calls) < 40 and calls[0] is None


def wait_job(srv, job_id):
    for _ in range(100):
        _, j = call(srv, f"/api/job?id={job_id}")
        if j["job"]["done"]:
            return j["job"]
        time.sleep(0.05)
    raise AssertionError("job didn't finish")


def test_court_check_and_calendar_jobs(srv, monkeypatch):
    add_login(srv)
    monkeypatch.setattr(web.WebApp, "_job_work", REAL_JOB_WORK)  # the fixture stubs it; use the real one
    seen = {}

    async def check(cfg, login, day, start, lengths, courts, say):
        seen["check"] = (day, start, lengths, courts)
        say("Yes.")
        return {"open": {lengths[0]: [3, 5]}}

    async def cal(cfg, login, day, say):
        seen["cal"] = day
        return {"date": day.isoformat(), "courts": [2, 3], "open": {"2": [480], "3": []}, "read_at": "1:00 PM"}
    monkeypatch.setattr(runner, "court_check", check)
    monkeypatch.setattr(runner, "calendar_day", cal)

    _, r = call(srv, "/api/job", {"kind": "court-check", "date": "2026-12-05", "time": 600, "length": 90,
                                  "shorter_ok": True, "courts": [5, "any"]})
    assert r["ok"], r
    j = wait_job(srv, r["job"]["id"])
    assert j["ok"] and j["data"]["open"]["90"] == [3, 5] and j["lines"] == ["Yes."]
    assert seen["check"] == (date(2026, 12, 5), 600, [90, 60, 30], [5, "any"])

    _, r = call(srv, "/api/job", {"kind": "calendar", "date": "2026-12-05"})
    j = wait_job(srv, r["job"]["id"])
    assert j["ok"] and j["data"]["open"]["2"] == [480] and seen["cal"] == date(2026, 12, 5)

    _, r = call(srv, "/api/job", {"kind": "calendar"})
    assert not r["ok"] and "date" in r["errors"][0]


def test_calendar_page_is_served(srv):
    st, body = call(srv, "/calendar", token=False)
    assert st == 200 and b"Court calendar" in body


REAL_JOB_WORK = web.WebApp._job_work
