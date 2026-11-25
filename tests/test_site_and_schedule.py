"""Pure helpers in site.py, scheduler.py and runner.py (no browser, no Task Scheduler)."""
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

from wacbooker import clubtime, scheduler
from wacbooker.engine import Slot
from wacbooker.runner import pick_quiet_slot
from wacbooker.site import court_from, match_rows, report_has, row_matches, rows_enabled

from fakes import booking

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def test_row_matching_needs_whole_name():
    assert row_matches("Ed Kass Member", "Ed Kass")
    assert row_matches("ed  kass", "Ed Kass")
    assert not row_matches("Ed Kassel", "Ed Kass")
    assert not row_matches("Fred Kass", "Ed Kass")


def test_match_rows_and_enabled():
    rows = [
        {"t": "Test Member", "cb": {"id": "c0", "dis": False}, "rd": {"id": "r0", "dis": False}},
        {"t": "Test Membership Spouse", "cb": {"id": "c1", "dis": False}, "rd": {"id": "r1", "dis": False}},
        {"t": "Pat Lee", "cb": {"id": "c2", "dis": False}, "rd": None},
        {"t": "Pat Leeson", "cb": {"id": "c3", "dis": False}, "rd": None},
    ]
    m = match_rows(rows, "Test Member", ["Pat Lee"])
    assert m["host"]["cb"]["id"] == "c0"
    assert m["partners"]["Pat Lee"]["cb"]["id"] == "c2"
    assert rows_enabled(m)
    rows[2]["cb"]["dis"] = True
    assert not rows_enabled(match_rows(rows, "Test Member", ["Pat Lee"]))
    assert not rows_enabled(match_rows(rows, "Test Member", ["Pat Lee", "Nobody Here"]))


def test_court_from_resource_or_text():
    assert court_from("94", "") == 5
    assert court_from("", "09:00 PM 10:00 PM Tennis court ten Add to Cart") == 10
    assert court_from("", "Tennis court 3") == 3
    assert court_from("", "Ball machine") is None


def test_report_match_is_strict():
    slot = Slot("12/15/2026", 18 * 60, 90, 5)
    rows = ["Tennis court 5 12/15/2026 6:00 PM to 7:30 PM Doubles"]
    assert report_has(rows, slot)
    assert not report_has(rows, Slot("12/15/2026", 18 * 60, 60, 5))
    assert not report_has(["Tennis court 50 12/15/2026 6:00 PM to 7:30 PM"], slot)
    assert report_has(["Tennis court ten 12/15/2026 6:00 PM to 7:30 PM"], Slot("12/15/2026", 1080, 90, 10))


def test_weekly_task_xml():
    b = booking()
    occ = b.next_runs(clubtime.slot_start(date(2026, 12, 1), 0), 1)[0]
    xml = scheduler.build_xml(b, occ.run_at, "InteractiveToken", command="py.exe", arguments="-m wacbooker")
    root = ET.fromstring(xml.split("\n", 1)[1])
    s = root.find("t:Settings", NS)
    assert s.find("t:WakeToRun", NS).text == "true"
    assert s.find("t:StartWhenAvailable", NS).text == "true"
    assert s.find("t:MultipleInstancesPolicy", NS).text == "IgnoreNew"
    trig = root.find("t:Triggers/t:CalendarTrigger", NS)
    start = datetime.fromisoformat(trig.find("t:StartBoundary", NS).text)
    assert start == occ.run_at.astimezone().replace(tzinfo=None)
    day = trig.find("t:ScheduleByWeek/t:DaysOfWeek", NS)[0].tag.split("}")[1]
    assert day == scheduler.DAY_TAGS[occ.run_at.astimezone().weekday()]
    assert root.find("t:Principals/t:Principal/t:LogonType", NS).text == "InteractiveToken"


def test_one_off_and_paused_task_xml():
    b = booking(day=None, date=date(2026, 12, 19), active=False)
    occ = b.next_runs(clubtime.slot_start(date(2026, 12, 1), 0), 1)[0]
    xml = scheduler.build_xml(b, occ.run_at, "Password", command="py.exe", arguments="x")
    root = ET.fromstring(xml.split("\n", 1)[1])
    assert root.find("t:Triggers/t:TimeTrigger", NS) is not None
    assert root.find("t:Settings/t:Enabled", NS).text == "false"
    assert root.find("t:Principals/t:Principal/t:LogonType", NS).text == "Password"


def test_task_names_are_safe():
    assert scheduler.task_name('Tue: "doubles"/A') == 'Booking - Tue- -doubles--A'


def test_quiet_slot_picks_preferred_court_more_than_25h_away():
    now = clubtime.slot_start(date(2026, 12, 1), 12 * 60)
    s = lambda d, st, c: Slot(d, st, 30, c)
    slots = [s("12/02/2026", 300, 5), s("12/03/2026", 330, 4), s("12/03/2026", 300, 6), s("12/03/2026", 360, 4)]
    assert pick_quiet_slot(slots, [4, "any"], now) == slots[1]          # 12/02 is under 25 h away
    assert pick_quiet_slot(slots, [9, "any"], now) == slots[2]          # earliest, then lowest court
    assert pick_quiet_slot(slots, [9], now) is None
