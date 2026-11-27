import asyncio

import pytest

from wacbooker import engine
from wacbooker.engine import Engine, Slot, pick

from fakes import FakeClock, FakeSite, booking, occurrence


def run(site_kw=None, booking_kw=None, chooser=None, first_court=None, start_rel=-75 * 60):
    occ = occurrence()
    W = occ.window.timestamp()
    clock = FakeClock(W + start_rel)
    site = FakeSite(clock, W, **(site_kw or {}))
    kw = {}
    if chooser is not None:
        kw["chooser"] = chooser
    if first_court is not None:
        kw["first_court"] = first_court
    eng = Engine(booking(**(booking_kw or {})), occ, site, clock, **kw)
    res = asyncio.run(eng.run())
    return res, site, clock, W


def test_books_first_choice_when_gate_opens():
    res, site, clock, W = run()
    assert res.status == "booked"
    assert (res.slot.court, res.slot.length) == (5, 90)
    assert len(site.booked) == 1
    # first press at W + 1 s, early refusals until the gate, accepted after it
    assert site.press_times[0] == pytest.approx(1.0, abs=0.01)
    # the server answers 2 s after a press; the gate opens at W + 44 s
    assert all(t + 2 < 44 for t in site.press_times[:-1])
    assert site.press_times[-1] + 2 >= 44
    assert "Booked: Ct 5" in res.message


def test_waits_until_stage_lead_and_keeps_page_alive():
    res, site, clock, W = run()
    assert site.calls[0] == "login"
    # keep-alives happened, none in the last 45 s before W
    assert site.calls.count("keepalive") >= 10
    assert res.booked


def test_stays_on_press_schedule_of_one_per_second():
    res, site, *_ = run(site_kw={"answer_s": 0.5})
    gaps = [b - a for a, b in zip(site.press_times, site.press_times[1:])]
    assert all(g == pytest.approx(1.0, abs=0.01) for g in gaps)


def test_moves_to_next_court_when_first_choice_taken_before_staging():
    res, site, *_ = run(site_kw={"open_courts": {90: [3, 4], 60: [3, 4, 5], 30: [5]}})
    assert (res.slot.court, res.slot.length) == (4, 90)


def test_any_picks_lowest_remaining_court():
    res, site, *_ = run(site_kw={"open_courts": {90: [8, 6], 60: [], 30: []}})
    assert (res.slot.court, res.slot.length) == (6, 90)


def test_no_any_means_no_other_courts():
    res, site, *_ = run(site_kw={"open_courts": {90: [8], 60: [8], 30: [8]}},
                        booking_kw={"courts": [5, 4]})
    assert res.status == "not_booked"
    assert "no court open" in res.message
    assert site.presses == 0


def test_falls_back_to_shorter_length():
    res, site, *_ = run(site_kw={"open_courts": {90: [], 60: [9], 30: [5]}})
    assert (res.slot.court, res.slot.length) == (9, 60)


def test_shorter_not_allowed_without_shorter_ok():
    res, site, *_ = run(site_kw={"open_courts": {90: [], 60: [5], 30: [5]}},
                        booking_kw={"shorter_ok": False})
    assert res.status == "not_booked"


def test_court_taken_at_gate_moves_to_next_choice():
    # someone else gets court 5 at W + 43 s, just before our accepted press
    res, site, *_ = run(site_kw={"taken_at": {(5, 90): 43.0}})
    assert res.booked
    assert res.slot.court == 4
    assert len(site.booked) == 1


def test_unanswered_commit_found_in_report_is_booked_without_repress():
    res, site, *_ = run(site_kw={"unknown_on": {1}, "report": True, "gate_s": 0})
    assert res.booked
    assert site.presses == 1
    assert "report" in site.calls
    assert len(site.booked) == 1


def test_unanswered_commit_not_in_report_presses_again():
    res, site, *_ = run(site_kw={"unknown_on": {3}, "report": False, "forced_only": True})
    assert res.booked
    assert "report" in site.calls
    assert site.presses > 3
    assert len(site.booked) == 1


def test_unanswered_commit_with_unreadable_report_stops_when_grid_says_taken():
    res, site, *_ = run(site_kw={"unknown_on": {2}, "report": None, "grid_after_unknown": False, "forced_only": True})
    assert res.status == "unsure"
    assert site.presses == 2
    assert "Check your reservations" in res.message


def test_unanswered_commit_with_unreadable_report_continues_when_slot_still_open():
    res, site, *_ = run(site_kw={"unknown_on": {2}, "report": None, "grid_after_unknown": True, "forced_only": True})
    assert res.booked
    assert site.presses > 2


def test_staging_glitches_are_retried():
    res, site, *_ = run(site_kw={"stage_glitches": 3})
    assert res.booked
    assert site.calls.count("login") >= 2  # a fresh sign-in from the second retry


def test_login_retries_then_succeeds():
    res, site, *_ = run(site_kw={"login_fails": 2})
    assert res.booked


def test_wrong_password_is_reported_plainly():
    res, site, *_ = run(site_kw={"bad_password": True})
    assert res.status == "not_booked"
    assert "couldn't sign in" in res.message
    assert site.calls.count("login") == 1


def test_gives_up_about_four_minutes_after_W():
    res, site, clock, W = run(site_kw={"gate_s": 10_000})
    assert res.status == "not_booked"
    assert clock.now() - W < 260
    assert "Book on the club site" in res.message


def test_started_late_still_tries():
    res, site, clock, W = run(start_rel=30)
    assert res.booked


def test_started_far_too_late_does_nothing():
    res, site, *_ = run(start_rel=25 * 60)
    assert res.status == "not_booked"
    assert site.calls == []


def test_pick_order():
    b = booking(courts=[5, 4, "any"], length=90, shorter_ok=True)
    s = lambda c, L: Slot("12/15/2026", 1080, L, c)
    open_ = {90: {9: s(9, 90)}, 60: {5: s(5, 60)}, 30: {}}
    assert pick(open_, b, set()).court == 9          # length beats court preference
    assert pick(open_, b, {(9, 90)}).court == 5       # then shorter on a preferred court
    assert pick({90: {}, 60: {}, 30: {}}, b, set()) is None


def test_early_rejection_markers():
    assert engine.is_early_rejection("None of the listed individuals are eligible for enrollment.")
    assert engine.is_early_rejection("Reservation cannot be made 169 Hour(s) in advance.")
    assert not engine.is_early_rejection("This time slot is no longer available.")


def test_presses_only_switched_on_pages_with_a_late_fallback():
    # the rows never switch on: no press is sent until W + 75 s, then one every 15 s
    res, site, *_ = run(site_kw={"gate_s": 1e9})
    assert res.status == "not_booked"
    assert site.forced and all(site.forced)
    assert 8 <= site.presses <= 13


def test_fresh_pages_until_the_gate_then_one_press():
    res, site, *_ = run()
    assert res.booked
    assert site.presses == 1   # nothing sent while the page's rows were still off


def test_chooser_picks_in_place_of_pick():
    def forced(open_by_len, b, tried):
        return open_by_len[90][3]
    res, site, *_ = run(chooser=forced)
    assert res.status == "booked"
    assert res.slot.court == 3
    assert len(site.booked) == 1


def test_first_court_goes_before_the_listed_courts():
    res, site, *_ = run(booking_kw={"courts": [3, "any"]}, first_court=5)
    assert res.status == "booked"
    assert res.slot.court == 5
