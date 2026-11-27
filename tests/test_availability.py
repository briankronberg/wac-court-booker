"""Court availability from the club's web service: the merge, the calendar cells,
court checks with and without a ball machine, and the jobs (offline)."""
import asyncio
import json
import time
from datetime import date, datetime

from wacbooker import runner, site as S, web

from test_web import add_login, call, srv  # noqa: F401  (fixture)

DAY = date(2026, 12, 4)
EARLY = datetime(2026, 11, 26, 9, 0)  # "now", well before DAY


def day_of(*ranges):
    """The web service's 1440 {TimeId, IsAvailable} list, free in [a, b) ranges."""
    return [{"TimeId": t, "IsAvailable": any(a <= t < b for a, b in ranges)} for t in range(1440)]


class FakeApi(S.ClubSite):
    """ClubSite whose web service answers from a table."""

    def __init__(self, table):
        super().__init__("u", lambda: "", log=lambda m: None)
        self.table, self.calls = table, []

    async def api(self, method, payload, timeout=60, strict=False):
        self.calls.append((method, payload))
        v = self.table[method]
        return v(payload) if callable(v) else v

    async def reservations(self, frm, to, family=False):
        return [r for r in self.table.get("mine", []) if frm <= r["date"] <= to]


def table():
    res = []
    for rid, c in S.RESOURCE_TO_COURT.items():
        free = [(300, 1380)] if c != 3 else [(300, 480), (600, 1380)]
        books = [{"FromMinutes": 480, "ToMinutes": 540, "HostName": "Not Shown", "HostId": 1}] if c == 3 else []
        res.append({"Id": int(rid), "Availability": day_of(*free), "BookingDetails": books})
    return {
        "GetSiteAvailability": day_of((300, 1320)),
        "GetServiceAvailability": lambda p: day_of((540, 630), (1020, 1200)) if p["serviceUniqueId"] in (
            S.MACHINES["genie"]["services"][1][1], S.MACHINES["regular"]["services"][1][1]) else (
            day_of((300, 540), (630, 1020), (1200, 1380)) if p["serviceUniqueId"] in (
                S.MACHINES["genie"]["services"][0][1], S.MACHINES["regular"]["services"][0][1]) else day_of((300, 1380))),
        "GetSchedulerResourceAvailability": res,
        "GetSchedulerProviderAvailability": [{"Id": 442, "Availability": day_of((300, 420), (510, 1380))},
                                             {"Id": 121, "Availability": day_of((300, 1380))}],
    }


def test_minutes_and_merge():
    a = S.minutes(day_of((300, 360)))
    b = S.minutes(day_of((330, 400)))
    m = S.both(a, b)
    assert S.free_for(m, 330, 30) and not S.free_for(m, 300, 30) and not S.free_for(m, 345, 30)
    assert S.open_starts(m) == [330]
    assert S.minutes(None) == [False] * 1440


def test_day_availability_combines_court_service_and_club_hours():
    site = FakeApi(table())
    av = asyncio.run(site.day_availability("12/04/2026", machines=True))
    assert set(av["courts"]) == {2, 3, 4, 5, 6, 8, 9, 10}
    assert S.free_for(av["courts"][8], 1290, 30) and not S.free_for(av["courts"][8], 1320, 30)  # club closes at 10
    assert not S.free_for(av["courts"][3], 480, 30) and av["booked"][3] == [(480, 540, "Not Shown", 1)]
    # The Genie is free outside its own bookings, in either its regular or Prime Time service.
    assert S.free_for(av["machines"]["genie"], 540, 60) and not S.free_for(av["machines"]["genie"], 420, 30)
    sent = [p for m, p in site.calls if m == "GetSchedulerResourceAvailability"][0]
    assert sorted(sent["resourceIds"]) == sorted(S.RESOURCE_TO_COURT)  # every court, not just 2-6


def test_calendar_cells_say_why_a_court_is_taken():
    av = asyncio.run(FakeApi(table()).day_availability("12/04/2026", machines=True))
    data = runner.calendar_cells(av, DAY, EARLY)
    c3 = data["cells"]["3"]
    assert c3[480] == "booked" and c3[540] == "closed" and c3[600] == "open"
    assert data["starts"][0] == 300 and data["starts"][-1] == 1290
    assert 420 not in data["machines"]["genie"] and 540 in data["machines"]["genie"]
    assert data["machine_courts"] == [2, 3, 8, 9, 10]
    json.dumps(data)  # goes to the page as it is


def test_today_marks_past_times():
    av = asyncio.run(FakeApi(table()).day_availability("12/04/2026"))
    now = datetime(2026, 12, 4, 10, 10)
    data = runner.calendar_cells(av, DAY, now)
    assert data["cells"]["2"][570] == "past" and data["cells"]["2"][600] != "open" and data["cells"]["2"][630] == "open"


def test_courts_free_with_a_ball_machine():
    av = asyncio.run(FakeApi(table()).day_availability("12/04/2026", machines=True))
    assert runner.courts_free(av, DAY, EARLY, 600, 60) == [2, 3, 4, 5, 6, 8, 9, 10]
    assert runner.courts_free(av, DAY, EARLY, 600, 60, "genie") == [2, 3, 8, 9, 10]
    assert runner.courts_free(av, DAY, EARLY, 420, 30, "genie") == []      # the Genie is out
    assert runner.courts_free(av, DAY, EARLY, 420, 30, "regular") == [2, 3, 8, 9, 10]


def test_court_check_messages():
    lines = []
    out = asyncio.run(runner.court_check_on(FakeApi(table()), DAY, 420, [60, 30], [4, "any"], lines.append, "genie"))
    assert out["open"][60] == [] and "Genie ball machine is taken" in lines[0] and "regular ball machine is free" in lines[1]
    lines.clear()
    out = asyncio.run(runner.court_check_on(FakeApi(table()), DAY, 480, [60], [3, 8], lines.append))
    assert 3 not in out["open"][60] and "court 8" in lines[1]


def wait_job(srv, job_id):
    for _ in range(100):
        _, j = call(srv, f"/api/job?id={job_id}")
        if j["job"]["done"]:
            return j["job"]
        time.sleep(0.05)
    raise AssertionError("job didn't finish")


class FakeLive:
    def __init__(self):
        self.site = FakeApi(table())

    def run(self, cfg, login, fn, say, timeout=600, retry=True):
        return asyncio.run(fn(self.site))

    def close(self):
        pass


def test_court_check_and_calendar_jobs(srv, monkeypatch):
    add_login(srv)
    monkeypatch.setattr(web.WebApp, "_job_work", REAL_JOB_WORK)  # the fixture stubs it; use the real one
    srv.app._live = FakeLive()

    _, r = call(srv, "/api/job", {"kind": "court-check", "date": "2026-12-04", "time": 600, "length": 90,
                                  "shorter_ok": True, "courts": [5, "any"]})
    assert r["ok"], r
    j = wait_job(srv, r["job"]["id"])
    assert j["ok"] and j["title"] == "Validate booking" and j["data"]["open"]["90"] == [2, 3, 4, 5, 6, 8, 9, 10]

    _, r = call(srv, "/api/job", {"kind": "court-check", "date": "2026-12-04", "time": 420, "length": 30,
                                  "courts": ["any"], "machine": "genie"})
    j = wait_job(srv, r["job"]["id"])
    assert j["ok"] and j["data"]["open"]["30"] == []

    _, r = call(srv, "/api/job", {"kind": "calendar", "date": "2026-12-04"})
    j = wait_job(srv, r["job"]["id"])
    assert j["ok"] and j["data"]["cells"]["3"]["480"] == "booked" and j["data"]["date"] == "2026-12-04"

    _, r = call(srv, "/api/job", {"kind": "calendar"})
    assert not r["ok"] and "date" in r["errors"][0]
    _, r = call(srv, "/api/job", {"kind": "court-check", "date": "2026-12-04", "time": 600, "machine": "x"})
    assert not r["ok"]


def test_calendar_page_is_served(srv):
    st, body = call(srv, "/calendar", token=False)
    assert st == 200 and b"Available courts" in body and b"hashchange" in body


REAL_JOB_WORK = web.WebApp._job_work


def test_short_name():
    known = ["Pat Leeds", "Sam Ortiz Jr.", "Kim Ortman", "Pat Lee"]
    assert runner.short_name("Ort, S.", known) == "S. Ortiz"          # one fit; the suffix ignored
    assert runner.short_name("Ort, K.", known) == "K. Ortman"
    assert runner.short_name("Lee, P.", known) == "P. Lee…"           # two people fit: don't guess
    assert runner.short_name("Kro, B.", []) == "B. Kro…"
    assert runner.short_name("Ng, A.", []) == "A. Ng"                 # under 3 letters: the whole name
    assert runner.short_name("Not Shown", known) == "Not Shown"


def test_calendar_names_booked_cells():
    t = table()
    for r in t["GetSchedulerResourceAvailability"]:
        for b in r["BookingDetails"]:
            b["HostName"] = "Ort, S."
    site = FakeApi(t)
    site.member_name = "Sam Ortiz"
    import wacbooker.runner as R
    real = R.load_buddies
    R.load_buddies = lambda: {}
    try:
        out = asyncio.run(R.calendar_on(site, DAY, lambda m: None))
    finally:
        R.load_buddies = real
    assert out["cells"]["3"][480] == "booked" and out["who"]["3"][480] == "S. Ortiz"
    assert out["who"]["3"].get(600) is None and out["who"]["4"] == {}
