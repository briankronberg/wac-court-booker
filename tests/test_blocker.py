"""Blocker: a short guard slot right before the main part — booked a week ahead on the
main's court, and cancelled in the same session as soon as the main's outcome is known.
The old system's plan_blocker rule: earliest of main−60 / main−30 that is free."""
import asyncio
from datetime import date, datetime, timedelta

import wacbooker.creds as creds
from wacbooker import clubtime, config, runner, scheduler
from fakes import FakeClock, FakeSite
from wacbooker.engine import SiteError


def booking(play="singles", day="Friday", time="3:00 PM", length=90, **kw):
    raw = {"name": "b", "login": "me", "play": play,
           "partners": ["Pat Lee"] if play == "singles" else ["A B", "C D", "E F"],
           "day": day, "time": time, "length": length, "courts": [5, 4, "any"]}
    raw.update(kw)
    errs = []
    b = config.parse_booking(raw, 1, errs)
    assert not errs, errs
    return b


# ---------------------------------------------------------------- config


def test_blocker_field():
    assert booking(blocker=True).blocker is True
    assert booking().blocker is False


def test_blocker_is_a_part_before_the_main():
    b = booking(blocker=True)  # Friday 3:00–4:30 PM
    assert [(p.key, p.time, p.length, p.prime) for p in b.parts] == \
        [("blocker", 840, 60, False), ("main", 900, 90, False)]
    assert b.for_part("blocker").time == 840 and b.for_part("blocker").length == 60
    assert b.part("blocker").lead == clubtime.OPEN_LEAD
    assert [p.key for p in booking(blocker=True, then=30).parts] == ["blocker", "main", "next"]
    # a split booking: the blocker guards the main part's start (4:30 PM), not the whole span
    s = booking(day="Tuesday", time="4:30 PM", length=90, blocker=True)
    assert [(p.key, p.time, p.length, p.prime) for p in s.parts] == \
        [("blocker", 930, 60, False), ("main", 990, 30, False), ("prime", 1020, 60, True)]


def test_blocker_is_not_a_reservation():
    # it is cancelled once the main part is known, so it must not count toward the 2-a-day cap
    assert booking(blocker=True).reservations == 1
    assert booking(blocker=True, then=60).reservations == 2


def test_blocker_refused_for_a_prime_time_main():
    # Friday 9:00–10:00 AM is entirely inside Prime Time: the main part books 24 h ahead
    errs = []
    b = config.parse_booking({"name": "b", "login": "me", "play": "singles", "partners": ["Pat Lee"],
                              "day": "Friday", "time": "9:00 AM", "length": 60, "courts": [5, "any"],
                              "blocker": True}, 1, errs)
    assert b is None and any("blocker" in e and "Prime Time" in e for e in errs), errs
    # a ball machine inside Prime Time is refused the same way
    errs = []
    b = config.parse_booking({"name": "b", "login": "me", "play": "machine", "day": "Wednesday",
                              "time": "9:00 AM", "length": 60, "courts": [8, "any"], "blocker": True},
                             1, errs)
    assert b is None and any("blocker" in e for e in errs), errs
    # a split booking is fine: its main part books a week ahead
    assert booking(day="Tuesday", time="4:30 PM", length=60, blocker=True).blocker is True


def test_template_documents_the_blocker():
    assert "blocker:" in config.TEMPLATE


def test_booking_to_map_writes_the_blocker():
    assert config.booking_to_map(booking(blocker=True))["blocker"] is True
    assert "blocker" not in config.booking_to_map(booking())


# ------------------------------------------------------------ scheduler


def test_plan_has_a_task_for_the_blocker():
    cfg = config.Config(logins=[config.Login("me", "x")], bookings=[booking(blocker=True)])
    plans = scheduler.plan(cfg, "InteractiveToken", now=clubtime.slot_start(date(2026, 12, 1), 0))
    assert [p.name for p in plans] == [scheduler.task_name("b", "blocker"), scheduler.task_name("b")]
    assert " (blocker)" in plans[0].name
    assert "--part blocker" in plans[0].xml and "--part" not in plans[1].xml
    # the blocker task fires exactly 60 minutes before the main task
    assert plans[0].next_run == plans[1].next_run - timedelta(minutes=60)


# ------------------------------------------------------------ plan rule


def _avail(taken: dict, courts=(3, 4, 5)):
    """A day grid: the club's hours open, minus the (start, length) windows in `taken`."""
    out = {}
    for c in courts:
        sheet = [False] * 1440
        for i in range(5 * 60, 22 * 60):
            sheet[i] = True
        for (s, L) in taken.get(c, []):
            for i in range(s, s + L):
                sheet[i] = False
        out[c] = sheet
    return {"courts": out, "booked": {}, "machines": {}}


def test_plan_blocker_earliest_free_before_play():
    day = date(2026, 12, 18)
    now = clubtime.now_central()
    main = 18 * 60  # play at 6:00 PM
    # the top court has the full hour free: the guard is the hour before play, there
    assert runner.plan_blocker(_avail({}), day, now, main, [5, 4, 3]) == (5, main - 60, 60)
    # the top court has only half the hour free: the next court still has the full hour,
    # and the earlier start wins (the old rule: earliest of main−60 / main−30 that is free)
    assert runner.plan_blocker(_avail({5: [(main - 60, 30)]}), day, now, main, [5, 4, 3]) == (4, main - 60, 60)


def test_plan_blocker_falls_back_to_30_when_only_30_is_left():
    day = date(2026, 12, 18)
    now = clubtime.now_central()
    main = 18 * 60
    # every court is taken at main−60; the top court frees at main−30
    assert runner.plan_blocker(
        _avail({5: [(main - 60, 30)], 4: [(main - 60, 60)], 3: [(main - 60, 60)]}),
        day, now, main, [5, 4, 3]) == (5, main - 30, 30)


def test_plan_blocker_none_when_nothing_is_free():
    day = date(2026, 12, 18)
    now = clubtime.now_central()
    main = 18 * 60
    assert runner.plan_blocker(
        _avail({5: [(main - 60, 60)], 4: [(main - 60, 60)], 3: [(main - 30, 30)]}),
        day, now, main, [5, 4, 3]) is None
    # play at 5:00 AM: an hour before is before the club opens — no guard
    assert runner.plan_blocker(_avail({}), day, now, 5 * 60, [5, 4, 3]) is None


def test_plan_blocker_only_guards_a_court_free_for_play():
    day = date(2026, 12, 18)
    now = clubtime.now_central()
    main = 18 * 60
    # court 5 is taken when play starts: guarding it would protect nothing, so court 4
    assert runner.plan_blocker(_avail({5: [(main, 30)]}), day, now, main, [5, 4, 3], 60) == (4, main - 60, 60)


def test_plan_blocker_avoids_prime_time_for_singles():
    now = clubtime.now_central()
    # Tuesday 8:00 PM: the guard would be 7:00-8:00 or 7:30-8:00 PM, both Prime Time for singles
    tue = date(2026, 12, 15)
    assert runner.plan_blocker(_avail({}), tue, now, 20 * 60, [5, 4, 3], prime_weekday=1) is None
    assert runner.plan_blocker(_avail({}), tue, now, 20 * 60, [5, 4, 3]) == (5, 19 * 60, 60)
    # Friday 10:30 AM: the guard would be 9:30-10:30 AM, inside Friday's Prime Time
    fri = date(2026, 12, 18)
    assert runner.plan_blocker(_avail({}), fri, now, 10 * 60 + 30, [5, 4, 3], prime_weekday=4) is None


def _fake_sleep(monkeypatch, clock):
    async def fake_sleep(sec):
        await clock.sleep(sec)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)


async def _no_backstop(*a, **k):
    return None


def _run_setup(monkeypatch, W, backstop=False, **site_kw):
    """A scheduled run at window W (a datetime): fake site, fake clock, toasts captured.
    Real asyncio.sleep is redirected to the fake clock, so the staging wait is instant.
    The guard backstop is patched out unless backstop=True (in real life it runs after the main)."""
    from wacbooker import clock as clockmod
    Wf = W.timestamp()
    clock = FakeClock(Wf - 75 * 60)
    site = FakeSite(clock, Wf, **site_kw)
    _fake_sleep(monkeypatch, clock)

    async def start(c, lg, log):
        return site
    monkeypatch.setattr(runner, "start_site", start)
    monkeypatch.setattr(runner, "keep_family", lambda *a: None)
    monkeypatch.setattr(runner, "RealClock", lambda *a, **k: clock)
    monkeypatch.setattr(clockmod, "measure", lambda: (0.0, "test"))
    if not backstop:
        monkeypatch.setattr(runner, "_guard_backstop", _no_backstop)
    toasts = []
    monkeypatch.setattr(runner.notify, "toast", lambda t, m: toasts.append((t, m)))
    return site, toasts


def _guard_booking(monkeypatch, tmp_path, **kw):
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    b = booking(day="Friday", time="6:00 PM", length=60, blocker=True, **kw)
    assert b is not None
    cfg = config.Config(logins=[config.Login("me", "x")], bookings=[b])
    monkeypatch.setattr(config, "load", lambda *a: (None, cfg))
    monkeypatch.setattr(creds, "has_password", lambda u: True)
    return b, cfg


def test_guard_run_books_the_hour_before_play(tmp_path, monkeypatch):
    import wacbooker.creds as creds
    _guard_booking(monkeypatch, tmp_path)
    day = date(2026, 12, 18)
    W = clubtime.window_open(clubtime.slot_start(day, 17 * 60))
    site, toasts = _run_setup(monkeypatch, W, open_courts={60: [5, 4, 3], 30: [5, 4, 3]})
    monkeypatch.setattr(clubtime, "now_central", lambda: W - timedelta(minutes=75))
    assert runner.run_booking("b", "blocker") == 0
    assert [(s.start, s.length, s.court) for s in site.booked] == [(17 * 60, 60, 5)]
    assert "day-availability" in site.calls
    assert toasts[-1][0] == "Guard slot booked"
    assert "guard" in toasts[-1][1].lower()


def test_guard_run_falls_back_to_30(tmp_path, monkeypatch):
    import wacbooker.creds as creds
    _guard_booking(monkeypatch, tmp_path)
    day = date(2026, 12, 18)
    W = clubtime.window_open(clubtime.slot_start(day, 17 * 60))
    site, _ = _run_setup(monkeypatch, W, open_courts={60: [5, 4, 3], 30: [5, 4, 3]},
                         grid={5: [(17 * 60, 30)], 4: [(17 * 60, 60)], 3: [(17 * 60, 60)]})
    monkeypatch.setattr(clubtime, "now_central", lambda: W - timedelta(minutes=75))
    assert runner.run_booking("b", "blocker") == 0
    assert [(s.start, s.length, s.court) for s in site.booked] == [(17 * 60 + 30, 30, 5)]


def test_guard_run_without_a_free_slot(tmp_path, monkeypatch):
    import wacbooker.creds as creds
    _guard_booking(monkeypatch, tmp_path)
    day = date(2026, 12, 18)
    W = clubtime.window_open(clubtime.slot_start(day, 17 * 60))
    site, toasts = _run_setup(monkeypatch, W, open_courts={60: [5, 4, 3], 30: [5, 4, 3]},
                              grid={5: [(17 * 60, 60)], 4: [(17 * 60, 60)], 3: [(17 * 60, 60)]})
    monkeypatch.setattr(clubtime, "now_central", lambda: W - timedelta(minutes=75))
    assert runner.run_booking("b", "blocker") == 1
    assert site.booked == []
    assert "guard" in toasts[-1][1].lower()


def test_guard_run_skips_when_the_day_already_has_a_reservation(tmp_path, monkeypatch):
    # guard + the booking itself would be 3 with the one already there: the club allows 2
    _guard_booking(monkeypatch, tmp_path)
    day = date(2026, 12, 18)
    W = clubtime.window_open(clubtime.slot_start(day, 17 * 60))
    site, toasts = _run_setup(monkeypatch, W, open_courts={60: [5, 4, 3], 30: [5, 4, 3]},
                              mine=[{"date": "12/18/2026", "start": 8 * 60, "end": 9 * 60, "court": 2}])
    monkeypatch.setattr(clubtime, "now_central", lambda: W - timedelta(minutes=75))
    assert runner.run_booking("b", "blocker") == 1
    assert site.booked == []
    msg = toasts[-1][1].lower()
    assert "guard" in msg and "2" in msg


def test_guard_is_cancelled_when_the_main_part_books(tmp_path, monkeypatch):
    import wacbooker.creds as creds
    _guard_booking(monkeypatch, tmp_path)
    day = date(2026, 12, 18)
    W_blk = clubtime.window_open(clubtime.slot_start(day, 17 * 60))
    W_main = clubtime.window_open(clubtime.slot_start(day, 18 * 60))

    site, toasts = _run_setup(monkeypatch, W_blk, open_courts={60: [5, 4, 3], 30: [5, 4, 3]})
    monkeypatch.setattr(clubtime, "now_central", lambda: W_blk - timedelta(minutes=75))
    assert runner.run_booking("b", "blocker") == 0
    assert [(s.start, s.length, s.court) for s in site.booked] == [(17 * 60, 60, 5)]

    site2, toasts2 = _run_setup(monkeypatch, W_main, open_courts={60: [5, 4, 3], 30: [5, 4, 3]})
    monkeypatch.setattr(clubtime, "now_central", lambda: W_main - timedelta(minutes=75))
    assert runner.run_booking("b") == 0
    assert [(s.start, s.length, s.court) for s in site2.booked] == [(18 * 60, 60, 5)]
    assert [(s.start, s.length, s.court) for s in site2.cancelled] == [(17 * 60, 60, 5)]
    assert "guard" in toasts2[-1][1].lower() and "cancel" in toasts2[-1][1].lower()


def test_guard_is_cancelled_when_the_main_part_loses(tmp_path, monkeypatch):
    import wacbooker.creds as creds
    _guard_booking(monkeypatch, tmp_path)
    day = date(2026, 12, 18)
    W_blk = clubtime.window_open(clubtime.slot_start(day, 17 * 60))
    W_main = clubtime.window_open(clubtime.slot_start(day, 18 * 60))

    site, _ = _run_setup(monkeypatch, W_blk, open_courts={60: [5, 4, 3], 30: [5, 4, 3]})
    monkeypatch.setattr(clubtime, "now_central", lambda: W_blk - timedelta(minutes=75))
    assert runner.run_booking("b", "blocker") == 0

    site2, _ = _run_setup(monkeypatch, W_main, open_courts={60: [], 30: []})
    monkeypatch.setattr(clubtime, "now_central", lambda: W_main - timedelta(minutes=75))
    assert runner.run_booking("b") == 1
    assert site2.booked == []
    assert [(s.start, s.length, s.court) for s in site2.cancelled] == [(17 * 60, 60, 5)]


def test_guard_stays_when_the_main_result_is_unknown(tmp_path, monkeypatch):
    import wacbooker.creds as creds
    _guard_booking(monkeypatch, tmp_path)
    day = date(2026, 12, 18)
    W_blk = clubtime.window_open(clubtime.slot_start(day, 17 * 60))
    W_main = clubtime.window_open(clubtime.slot_start(day, 18 * 60))

    site, _ = _run_setup(monkeypatch, W_blk, open_courts={60: [5, 4, 3], 30: [5, 4, 3]})
    monkeypatch.setattr(clubtime, "now_central", lambda: W_blk - timedelta(minutes=75))
    assert runner.run_booking("b", "blocker") == 0

    site2, toasts = _run_setup(monkeypatch, W_main, open_courts={60: [5, 4, 3], 30: [5, 4, 3]},
                               unknown_on={2}, report=None, grid_after_unknown=False,
                               forced_only=True)
    monkeypatch.setattr(clubtime, "now_central", lambda: W_main - timedelta(minutes=75))
    assert runner.run_booking("b") == 1
    assert site2.cancelled == []  # the guard stays in case the booking went through
    assert "guard" in toasts[-1][1].lower() and "club site" in toasts[-1][1]


def test_guard_cancel_failure_says_to_cancel_it_on_the_club_site(tmp_path, monkeypatch):
    _guard_booking(monkeypatch, tmp_path)
    day = date(2026, 12, 18)
    W_blk = clubtime.window_open(clubtime.slot_start(day, 17 * 60))
    W_main = clubtime.window_open(clubtime.slot_start(day, 18 * 60))

    site, _ = _run_setup(monkeypatch, W_blk, open_courts={60: [5, 4, 3], 30: [5, 4, 3]})
    monkeypatch.setattr(clubtime, "now_central", lambda: W_blk - timedelta(minutes=75))
    assert runner.run_booking("b", "blocker") == 0

    site2, toasts2 = _run_setup(monkeypatch, W_main, open_courts={60: [5, 4, 3], 30: [5, 4, 3]})

    async def bad_cancel(slot, tries=3):
        raise SiteError("cancel: row not found")
    site2.cancel = bad_cancel
    monkeypatch.setattr(clubtime, "now_central", lambda: W_main - timedelta(minutes=75))
    assert runner.run_booking("b") == 0  # the booking itself went through
    msg = toasts2[-1][1]
    assert "guard" in msg.lower() and "club site" in msg


def test_group_guard_books_per_login_and_the_main_run_cancels_each(tmp_path, monkeypatch):
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    raw = {"name": "b", "login": "me", "play": "singles", "partners": ["Pat Lee"], "day": "Friday",
           "time": "6:00 PM", "length": 60, "courts": [5, 4, "any"], "blocker": True,
           "also": [{"login": "other", "partners": ["Sam Ortiz"]}]}
    errs = []
    b = config.parse_booking(raw, 1, errs)
    assert not errs, errs
    assert b is not None
    cfg = config.Config(logins=[config.Login("me", "x"), config.Login("other", "y")], bookings=[b])
    monkeypatch.setattr(config, "load", lambda *a: (None, cfg))
    monkeypatch.setattr(creds, "has_password", lambda u: True)
    day = date(2026, 12, 18)
    W_blk = clubtime.window_open(clubtime.slot_start(day, 17 * 60))
    W_main = clubtime.window_open(clubtime.slot_start(day, 18 * 60))

    def sites_for(W):
        from wacbooker import clock as clockmod
        clock = FakeClock(W.timestamp() - 75 * 60)
        sites = {}

        async def start(c, lg, log):
            s = FakeSite(clock, W.timestamp(), open_courts={60: [5, 4, 3], 30: [5, 4, 3]})
            sites[lg.nickname] = s
            return s
        _fake_sleep(monkeypatch, clock)
        monkeypatch.setattr(runner, "start_site", start)
        monkeypatch.setattr(runner, "RealClock", lambda *a, **k: clock)
        monkeypatch.setattr(clockmod, "measure", lambda: (0.0, "test"))
        monkeypatch.setattr(runner, "_guard_backstop", _no_backstop)
        return sites

    sites = sites_for(W_blk)
    toasts = []
    monkeypatch.setattr(runner.notify, "toast", lambda t, m: toasts.append((t, m)))
    monkeypatch.setattr(clubtime, "now_central", lambda: W_blk - timedelta(minutes=75))
    assert runner.run_booking("b", "blocker") == 0
    guards = {nick: s.booked[0] for nick, s in sites.items()}
    assert len(guards) == 2 and {v.start for v in guards.values()} == {17 * 60}
    assert len({v.court for v in guards.values()}) == 2  # coordinated: different courts

    sites2 = sites_for(W_main)
    monkeypatch.setattr(clubtime, "now_central", lambda: W_main - timedelta(minutes=75))
    assert runner.run_booking("b") == 0
    mains = {nick: s.booked[0] for nick, s in sites2.items()}
    assert {v.start for v in mains.values()} == {18 * 60}
    assert len({v.court for v in mains.values()}) == 2
    for nick, s in sites2.items():
        g = guards[nick]
        assert [(x.start, x.length, x.court) for x in s.cancelled] == [(17 * 60, g.length, g.court)]


def test_book_now_skips_the_guard(tmp_path, monkeypatch):
    # Ruling: Book Now books only the play itself. Once its window is open, every slot that
    # starts earlier is open too, so a guard booked seconds before would protect nothing.
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    now = clubtime.now_central()
    d = now.date()
    # the first Friday whose 6:00 PM is more than an hour away: its window (169 h ahead) is
    # open, and Friday 6:00 PM is outside Prime Time
    while d.weekday() != 4 or clubtime.slot_start(d, 18 * 60) <= now + timedelta(hours=1):
        d += timedelta(days=1)
    assert clubtime.window_open(clubtime.slot_start(d, 18 * 60)) <= now
    errs = []
    b = config.parse_booking({"name": "n", "login": "me", "play": "singles", "partners": ["Pat Lee"],
                              "date": d.isoformat(), "time": "6:00 PM", "length": 60,
                              "courts": [5, 4, "any"], "blocker": True}, 1, errs)
    assert not errs, errs
    assert b is not None
    cfg = config.Config(logins=[config.Login("me", "x")], bookings=[b])
    clock = FakeClock(clubtime.now_central().timestamp())
    site = FakeSite(clock, clock.now(), gate_s=0, open_courts={60: [5, 4, 3], 30: [5, 4, 3]})

    async def start(c, lg, log):
        return site
    monkeypatch.setattr(runner, "start_site", start)
    monkeypatch.setattr(runner, "keep_family", lambda *a: None)
    monkeypatch.setattr(runner.notify, "toast", lambda *a, **k: None)
    lg = cfg.login("me")
    assert lg is not None
    out = asyncio.run(runner.book_now(cfg, b, lg, lambda s: None, clock))
    assert out == "booked"
    assert [(s.start, s.length, s.court) for s in site.booked] == [(18 * 60, 60, 5)]
    assert site.cancelled == []


def test_group_member_crash_still_settles_the_others(tmp_path, monkeypatch):
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    raw = {"name": "b", "login": "me", "play": "singles", "partners": ["Pat Lee"], "day": "Friday",
           "time": "6:00 PM", "length": 60, "courts": [5, 4, "any"], "blocker": True,
           "also": [{"login": "other", "partners": ["Sam Ortiz"]}]}
    errs = []
    b = config.parse_booking(raw, 1, errs)
    assert not errs, errs
    cfg = config.Config(logins=[config.Login("me", "x"), config.Login("other", "y")], bookings=[b])
    monkeypatch.setattr(config, "load", lambda *a: (None, cfg))
    monkeypatch.setattr(creds, "has_password", lambda u: True)
    day = date(2026, 12, 18)
    W_blk = clubtime.window_open(clubtime.slot_start(day, 17 * 60))
    W_main = clubtime.window_open(clubtime.slot_start(day, 18 * 60))

    def sites_for(W, crash=None):
        from wacbooker import clock as clockmod
        clock = FakeClock(W.timestamp() - 75 * 60)
        sites = {}

        async def start(c, lg, log):
            s = FakeSite(clock, W.timestamp(), open_courts={60: [5, 4, 3], 30: [5, 4, 3]})
            if lg.nickname == crash:
                async def boom(*a, **k):
                    raise RuntimeError("boom")
                s.attempt = boom
            sites[lg.nickname] = s
            return s
        _fake_sleep(monkeypatch, clock)
        monkeypatch.setattr(runner, "start_site", start)
        monkeypatch.setattr(runner, "RealClock", lambda *a, **k: clock)
        monkeypatch.setattr(clockmod, "measure", lambda: (0.0, "test"))
        monkeypatch.setattr(runner, "_guard_backstop", _no_backstop)
        return sites

    sites = sites_for(W_blk)
    toasts = []
    monkeypatch.setattr(runner.notify, "toast", lambda t, m: toasts.append((t, m)))
    monkeypatch.setattr(clubtime, "now_central", lambda: W_blk - timedelta(minutes=75))
    assert runner.run_booking("b", "blocker") == 0
    guards = {nick: s.booked[0] for nick, s in sites.items()}

    sites2 = sites_for(W_main, crash="other")
    monkeypatch.setattr(clubtime, "now_central", lambda: W_main - timedelta(minutes=75))
    assert runner.run_booking("b") == 1  # the other login's outcome is unknown, so not all booked
    g = guards["me"]
    assert [(x.start, x.length, x.court) for x in sites2["me"].cancelled] == [(17 * 60, g.length, g.court)]
    assert sites2["other"].cancelled == []  # its guard is kept: its outcome is unknown
    msg = toasts[-1][1]
    assert "other: other:" not in msg
    assert "boom" not in msg and "unexpected error" in msg and "club site" in msg


def test_backstop_cancels_a_guard_the_booking_never_settled(tmp_path, monkeypatch):
    _guard_booking(monkeypatch, tmp_path)
    day = date(2026, 12, 18)
    W_blk = clubtime.window_open(clubtime.slot_start(day, 17 * 60))

    site, toasts = _run_setup(monkeypatch, W_blk, backstop=True, open_courts={60: [5, 4, 3], 30: [5, 4, 3]})
    monkeypatch.setattr(clubtime, "now_central", lambda: W_blk - timedelta(minutes=75))
    assert runner.run_booking("b", "blocker") == 0
    # the main run never happens: the guard run's own backstop cancels the guard it booked
    assert [(s.start, s.length, s.court) for s in site.booked] == [(17 * 60, 60, 5)]
    assert [(s.start, s.length, s.court) for s in site.cancelled] == [(17 * 60, 60, 5)]
    assert toasts[-1][0] == "Guard slot cancelled"


def test_backstop_leaves_a_guard_the_booking_kept(tmp_path, monkeypatch):
    b, cfg = _guard_booking(monkeypatch, tmp_path)
    day = date(2026, 12, 18)
    W_blk = clubtime.window_open(clubtime.slot_start(day, 17 * 60))
    W_main = clubtime.window_open(clubtime.slot_start(day, 18 * 60))

    site, _ = _run_setup(monkeypatch, W_blk, open_courts={60: [5, 4, 3], 30: [5, 4, 3]})
    monkeypatch.setattr(clubtime, "now_central", lambda: W_blk - timedelta(minutes=75))
    assert runner.run_booking("b", "blocker") == 0

    site2, _ = _run_setup(monkeypatch, W_main, open_courts={60: [5, 4, 3], 30: [5, 4, 3]},
                          unknown_on={2}, report=None, grid_after_unknown=False, forced_only=True)
    monkeypatch.setattr(clubtime, "now_central", lambda: W_main - timedelta(minutes=75))
    assert runner.run_booking("b") == 1
    assert site2.cancelled == []  # kept on purpose: the main outcome was unknown

    occ = b.due(W_blk - timedelta(minutes=75), "blocker")
    assert occ is not None
    site3, _ = _run_setup(monkeypatch, W_main, backstop=True, open_courts={60: [5, 4, 3], 30: [5, 4, 3]})
    asyncio.run(runner._guard_backstop(cfg, b, occ, lambda m: None))
    assert site3.cancelled == []
