from datetime import date, datetime

from wacbooker.clubtime import CENTRAL
from wacbooker.config import Booking
from wacbooker.menu import booking_lines

NOW = datetime(2026, 11, 25, 12, 40, tzinfo=CENTRAL)


def weekly(**kw):
    base = dict(name="Tue 6:00 AM singles with Andrea", login="me", play="singles",
                partners=["Andrea Kronberg"], time=6 * 60, length=30, courts=[2, 3, "any"],
                day=1, date=None, shorter_ok=False, skip=[], active=True)
    base.update(kw)
    return Booking(**base)


def test_layout_matches_the_agreed_example():
    lines = booking_lines(weekly(), NOW, {"state": "Ready", "logon": "InteractiveToken"})
    assert lines == [
        "Tue 6:00 AM singles with Andrea",
        "  Every Tuesday, 6:00 to 6:30 AM, singles with Andrea Kronberg",
        "  Courts: 2, then 3, then any.  Login: me",
        "  Next runs, every week until you remove or pause it (courts open 1 week + 1 hour ahead):",
        "    Tue 12/1 at 5:00 AM  books Tue 12/8, 6:00 AM   (PC on by 3:45 AM)",
        "    Tue 12/8 at 5:00 AM  books Tue 12/15, 6:00 AM  (PC on by 3:45 AM)",
        "  Scheduled task: ready (runs while you're signed in to Windows)",
    ]


def test_one_off_noon_crossing_and_shorter_ok():
    b = weekly(day=None, date=date(2026, 12, 19), time=11 * 60 + 30, length=90, shorter_ok=True,
               courts=[5], active=False)
    lines = booking_lines(b, NOW, None)
    assert lines[0].endswith("(PAUSED)")
    assert lines[1] == ("  Once, Sat 12/19, 11:30 AM to 1:00 PM, singles with Andrea Kronberg"
                        " (or shorter if no court has that long)")
    assert lines[2] == "  Courts: 5.  Login: me"
    assert "Warning" not in "\n".join(lines)  # paused: no task expected


def test_pc_on_by_shows_the_day_when_it_is_the_day_before():
    # A 1:00 AM slot opens at 12:00 AM; the task starts 75 min earlier, the evening before.
    b = weekly(time=60)
    run = booking_lines(b, NOW, None)[4]
    assert "at 12:00 AM" in run and "(PC on by Mon 11/30 10:45 PM)" in run


def test_missing_task_warns_and_signed_out_task_says_so():
    assert any("Warning: no scheduled task" in x for x in booking_lines(weekly(), NOW, None))
    lines = booking_lines(weekly(), NOW, {"state": "Ready", "logon": "Password"})
    assert lines[-1] == "  Scheduled task: ready (runs even when you're signed out)"


def test_one_off_heading_says_it_runs_once():
    b = weekly(day=None, date=date(2026, 12, 19))
    assert "  Runs once (courts open 1 week + 1 hour ahead):" in booking_lines(b, NOW, None)
