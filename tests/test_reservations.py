"""My reservations: reading the report, the 24-hour fee flag, and the list and cancel jobs (offline)."""
import asyncio
from datetime import datetime

from wacbooker import clubtime, runner, site as S, web

from test_availability import wait_job
from test_web import add_login, call, srv  # noqa: F401  (fixture)

G1, G2, G3 = ("68396bc9-f440-4dfb-8b80-25f84a76a5c8", "135ef417-d7c3-4931-880b-a5115408d511",
              "0e1f2a3b-4c5d-4e6f-8a9b-0c1d2e3f4a5b")


def row(guid, svc, when, court, provider=""):
    return {"href": f"https://x/lcrac/Members/Scheduler/CurrentScheduleDetail.aspx?ScheduleGuid={guid}&sourcePage=ReservationReport",
            "cells": [svc, "Wisconsin Athletic Club, LLC", when, provider, court]}


ROWS = [row(G1, "2 Singles", "11/28/2026; 8:30 AM to 10:00 AM", "Tennis court 5"),
        row(G2, "2 Singles", "11/28/2026; 7:00 AM to 8:30 AM", "Tennis court 5"),
        row(G3, "3.01 Genie Ball Machine", "12/02/2026; 6:00 PM to 7:00 PM", "Tennis court ten", "Genie M."),
        row(G1, "2 Singles", "11/28/2026; 8:30 AM to 10:00 AM", "Tennis court 5"),  # the page repeats rows
        {"href": "", "cells": ["Schedule", "Club", "Date", "Providers", "Resources"]}]


def test_parse_report():
    got = S.parse_report(ROWS)
    assert [r["guid"] for r in got] == [G2, G1, G3]  # sorted by date and time, no repeats
    assert got[0] == {"guid": G2, "service": "2 Singles", "date": "11/28/2026", "start": 420, "end": 510,
                      "court": 5, "machine": None}
    assert got[2]["court"] == 10 and got[2]["machine"] == "genie"


def test_reservation_view_flags_the_fee():
    r = S.parse_report(ROWS)[0]  # Sat 11/28 7:00 AM
    v = runner.reservation_view(r, clubtime.slot_start(datetime(2026, 11, 27).date(), 9 * 60))
    assert v["fee"] and not v["started"] and v["what"] == "Singles" and v["span"] == "7:00 AM to 8:30 AM"
    v = runner.reservation_view(r, clubtime.slot_start(datetime(2026, 11, 26).date(), 9 * 60))
    assert not v["fee"] and v["day"] == "2026-11-28"
    v = runner.reservation_view(r, clubtime.slot_start(datetime(2026, 11, 28).date(), 7 * 60 + 5))
    assert v["started"] and not v["fee"]
    g = runner.reservation_view(S.parse_report(ROWS)[2], clubtime.slot_start(datetime(2026, 11, 26).date(), 0))
    assert g["what"] == "Genie ball machine"


class FakeSite:
    def __init__(self):
        self.cancelled = []

    async def reservations(self, frm, to, family=False):
        rows = S.parse_report(ROWS)
        return rows if family else rows[:2]

    async def cancel_reservation(self, guid, expect):
        self.cancelled.append((guid, expect["date"], expect["start"]))
        return ""


class FakeLive:
    def __init__(self):
        self.site = FakeSite()

    def run(self, cfg, login, fn, say, timeout=600, retry=True):
        self.retry = retry
        return asyncio.run(fn(self.site))

    def close(self):
        pass


def test_list_and_cancel_jobs(srv, monkeypatch, tmp_path):
    add_login(srv)
    from test_availability import REAL_JOB_WORK
    monkeypatch.setattr(web.WebApp, "_job_work", REAL_JOB_WORK)
    monkeypatch.setattr(runner.notify, "toast", lambda *a, **k: None)
    srv.app._live = live = FakeLive()

    _, r = call(srv, "/api/job", {"kind": "reservations", "from": "2026-11-26", "to": "2026-12-25", "family": True})
    j = wait_job(srv, r["job"]["id"])
    assert j["ok"] and [x["mine"] for x in j["data"]["items"]] == [True, True, False]

    item = j["data"]["items"][1]
    _, r = call(srv, "/api/job", {"kind": "cancel", "reservation": item})
    assert not r["ok"] and "Confirm" in r["errors"][0]  # the page must confirm first
    _, r = call(srv, "/api/job", {"kind": "cancel", "reservation": item, "confirmed": True})
    j = wait_job(srv, r["job"]["id"])
    assert j["ok"] and live.site.cancelled == [(G1, "11/28/2026", 510)] and live.retry is False
    assert "Cancelled Sat Nov 28, 8:30 AM to 10:00 AM on court 5." in j["lines"]
    _, res = call(srv, "/api/results")
    assert res["results"][0]["status"] == "cancelled"

    _, r = call(srv, "/api/job", {"kind": "cancel", "reservation": {"guid": "x"}, "confirmed": True})
    assert not r["ok"]
    _, r = call(srv, "/api/job", {"kind": "reservations", "from": "2026-01-01", "to": "2028-01-01"})
    assert not r["ok"] and "year" in r["errors"][0]


def test_cancel_refuses_a_bad_id():
    site = S.ClubSite("u", lambda: "", log=lambda m: None)
    try:
        asyncio.run(site.cancel_reservation("not-a-guid", {}))
    except S.SiteError as e:
        assert "doesn't look right" in str(e)
    else:
        raise AssertionError("accepted a bad id")


def test_report_has_matches_the_reports_unpadded_date():
    from wacbooker.engine import Slot
    from wacbooker.site import report_has
    rows = ["2 Singles Wisconsin Athletic Club, LLC 12/4/2026; 1:30 PM to 2:30 PM Tennis court 5"]
    assert report_has(rows, Slot("12/04/2026", 13 * 60 + 30, 60, 5))
    assert not report_has(rows, Slot("12/04/2026", 13 * 60 + 30, 60, 4))
    assert not report_has(rows, Slot("12/14/2026", 13 * 60 + 30, 60, 5))


def test_report_has_does_not_match_a_longer_date():
    from wacbooker.engine import Slot
    from wacbooker.site import report_has
    rows = ["2 Singles Wisconsin Athletic Club, LLC 11/5/2027; 1:30 PM to 2:30 PM Tennis court 5"]
    assert not report_has(rows, Slot("01/05/2027", 13 * 60 + 30, 60, 5))
    assert report_has(rows, Slot("11/05/2027", 13 * 60 + 30, 60, 5))
