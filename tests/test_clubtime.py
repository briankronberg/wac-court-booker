from datetime import date, datetime, timedelta, timezone

import pytest

from wacbooker import clubtime as ct


def test_parse_and_format_time():
    assert ct.parse_time("6:00 PM") == 18 * 60
    assert ct.parse_time("6 pm") == 18 * 60
    assert ct.parse_time("12:30 AM") == 30
    assert ct.parse_time("12:00 PM") == 12 * 60
    assert ct.parse_time("18:30") == 18 * 60 + 30
    assert ct.fmt_time(18 * 60) == "6:00 PM"
    assert ct.fmt_time(30) == "12:30 AM"
    for bad in ("25:00", "13 PM", "soon", ""):
        with pytest.raises(ValueError):
            ct.parse_time(bad)


def test_parse_day():
    assert ct.parse_day("Tuesday") == 1
    assert ct.parse_day("tue") == 1
    with pytest.raises(ValueError):
        ct.parse_day("Funday")


def test_window_is_169_hours_before():
    st = ct.slot_start(date(2026, 12, 15), 18 * 60)
    w = ct.window_open(st)
    assert w.strftime("%Y-%m-%d %H:%M") == "2026-12-08 17:00"
    assert (st - w) == timedelta(hours=169)


def test_window_across_daylight_saving_is_absolute():
    # DST ends Sun 2026-11-01. A Wed 11/04 6 PM CST slot opens 169 real hours earlier.
    st = ct.slot_start(date(2026, 11, 4), 18 * 60)
    w = ct.window_open(st)
    assert st.astimezone(timezone.utc) - w.astimezone(timezone.utc) == timedelta(hours=169)
    assert w.strftime("%m/%d %H:%M") == "10/28 18:00"  # CDT wall clock, one hour later


def test_occurrences_weekly_and_one_off():
    after = ct.slot_start(date(2026, 12, 1), 0)
    occ = ct.occurrences(1, None, 18 * 60, after, count=3)
    assert [o.day for o in occ] == [date(2026, 12, 8), date(2026, 12, 15), date(2026, 12, 22)]
    assert ct.occurrences(None, date(2026, 12, 19), 600, after)[0].day == date(2026, 12, 19)
    assert ct.occurrences(None, date(2026, 12, 2), 600, after) == []  # window already passed


def test_due_occurrence_for_a_run():
    st = ct.slot_start(date(2026, 12, 15), 18 * 60)
    w = ct.window_open(st)
    assert ct.due_occurrence(1, None, 18 * 60, w - timedelta(minutes=75)).day == date(2026, 12, 15)
    assert ct.due_occurrence(1, None, 18 * 60, w + timedelta(minutes=2)).day == date(2026, 12, 15)
    assert ct.due_occurrence(1, None, 18 * 60, w + timedelta(minutes=30)) is None
    assert ct.due_occurrence(1, None, 18 * 60, w - timedelta(hours=5)) is None


def test_run_time_is_75_minutes_before_window():
    occ = ct.occurrences(1, None, 18 * 60, ct.slot_start(date(2026, 12, 1), 0))[0]
    assert occ.window - occ.run_at == timedelta(minutes=75)
