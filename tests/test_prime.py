"""Prime Time: singles in those hours open 24 hours ahead; a booking that straddles it books in two parts."""
from datetime import date, timedelta

from wacbooker import clubtime, config, results, runner, scheduler


def booking(play="singles", day="Monday", time="8:00 AM", length=90, **kw):
    raw = {"name": "b", "login": "me", "play": play,
           "partners": ["Pat Lee"] if play == "singles" else ["A B", "C D", "E F"],
           "day": day, "time": time, "length": length, "courts": [5, 4, "any"]}
    raw.update(kw)
    errs = []
    b = config.parse_booking(raw, 1, errs)
    assert not errs, errs
    return b


def test_split_prime_pieces():
    P = clubtime.Piece
    assert clubtime.split_prime(0, 8 * 60, 90) == [P(480, 60, False), P(540, 30, True)]
    assert clubtime.split_prime(1, 10 * 60, 90) == [P(600, 30, True), P(630, 60, False)]
    assert clubtime.split_prime(0, 16 * 60 + 30, 90) == [P(990, 30, False), P(1020, 60, True)]
    assert clubtime.split_prime(5, 9 * 60, 90) == [P(540, 90, False)]        # Saturday: no Prime Time
    assert clubtime.split_prime(4, 17 * 60, 90) == [P(1020, 90, False)]      # Friday evening isn't Prime Time
    assert clubtime.split_prime(3, 18 * 60, 90) == [P(1080, 90, True)]


def test_parts_and_leads():
    b = booking(day="Tuesday", time="6:00 PM")
    assert b.prime_kind == "all" and b.part().lead == timedelta(hours=24)
    assert booking(play="doubles", day="Tuesday", time="6:00 PM").prime_kind == "none"
    b = booking()  # Monday 8:00-9:30 AM
    assert b.prime_kind == "split"
    assert [(p.key, p.time, p.length, p.prime) for p in b.parts] == [("main", 480, 60, False), ("prime", 540, 30, True)]
    assert b.for_part("prime").time == 540 and b.for_part("prime").length == 30
    assert booking(day="Saturday").prime_kind == "none"


def test_windows_follow_the_part():
    b = booking()
    after = clubtime.slot_start(date(2026, 12, 1), 0)
    main = b.next_runs(after, 1)[0]
    # The Prime Time part's window is only a day ahead, so its next run can be an
    # earlier play date (the run then skips it: no first part was booked that day).
    prime = next(o for o in b.next_runs(after, 3, "prime") if o.day == main.day)
    assert main.start - main.window == timedelta(hours=169)
    assert prime.start - prime.window == timedelta(hours=24)
    assert prime.start == clubtime.slot_start(prime.day, 9 * 60)


def test_plan_has_a_task_per_part():
    cfg = config.Config(logins=[config.Login("me", "x")], bookings=[booking()])
    plans = scheduler.plan(cfg, "InteractiveToken", now=clubtime.slot_start(date(2026, 12, 1), 0))
    assert [p.name for p in plans] == [scheduler.task_name("b"), scheduler.task_name("b", "prime")]
    assert "--part prime" in plans[1].xml and "--part" not in plans[0].xml


def test_split_counts_as_two_reservations():
    cfg = config.Config(logins=[config.Login("me", "x")],
                        bookings=[booking(), booking(name="c", time="6:00 AM", length=60)])
    config.check(cfg, now=clubtime.slot_start(date(2026, 12, 1), 0))
    assert any("3 reservations" in w for w in cfg.warnings)


def test_one_off_prime_singles_can_be_tomorrow(tmp_path, monkeypatch):
    now = clubtime.now_central()
    d = (now + timedelta(days=2)).date()
    while d.weekday() > 3:
        d += timedelta(days=1)
    if (clubtime.slot_start(d, 18 * 60) - now) < timedelta(hours=25):
        d += timedelta(days=7)
    raw = {"name": "o", "login": "me", "play": "singles", "partners": ["Pat Lee"], "date": d.isoformat(),
           "time": "6:00 PM", "length": 60, "courts": ["any"]}
    cfg = config.from_doc({"logins": [{"nickname": "me", "username": "x"}], "bookings": [raw]})
    assert cfg.ok and not cfg.warnings, cfg.warnings
    assert cfg.bookings[0].next_runs(now, 1)


def test_split_booking_runs_both_parts(tmp_path, monkeypatch):
    """Monday 8:00-9:30: 8-9 runs 169 h ahead, 9-9:30 runs 24 h ahead on the court the first part got."""
    from wacbooker import creds, notify
    from wacbooker.engine import RunResult, Slot
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    b = booking()
    cfg = config.Config(logins=[config.Login("me", "x")], bookings=[b])
    monkeypatch.setattr(config, "load", lambda *a: (None, cfg))
    monkeypatch.setattr(creds, "has_password", lambda u: True)
    toasts, ran = [], []
    monkeypatch.setattr(notify, "toast", lambda t, m: toasts.append((t, m)))

    async def fake_run(cfg_, pb, occ, login, log, first_courts=None):
        ran.append((pb.time, pb.length, list(pb.courts), occ.day))
        return RunResult("booked", f"Booked: Ct {pb.courts[0]}", slot=Slot(occ.day.strftime("%m/%d/%Y"), pb.time,
                                                                        pb.length, pb.courts[0]))
    monkeypatch.setattr(runner, "_run_async", fake_run)
    day = date(2026, 12, 14)
    main_w = clubtime.window_open(clubtime.slot_start(day, 8 * 60))
    prime_w = clubtime.window_open(clubtime.slot_start(day, 9 * 60), clubtime.PRIME_LEAD)

    # The Prime Time part alone (no first part booked that day) is skipped, quietly.
    monkeypatch.setattr(clubtime, "now_central", lambda: prime_w - timedelta(days=7, minutes=75))
    assert runner.run_booking("b", "prime") == 0 and not ran and not toasts

    monkeypatch.setattr(clubtime, "now_central", lambda: main_w - timedelta(minutes=75))
    b.courts = [4, 5, "any"]
    assert runner.run_booking("b") == 0
    assert ran[-1] == (480, 60, [4, 5, "any"], day)
    assert "Prime Time part (9:00 AM to 9:30 AM) books 24 hours ahead" in toasts[-1][1]

    b.courts = [5, 4, "any"]
    monkeypatch.setattr(clubtime, "now_central", lambda: prime_w - timedelta(minutes=75))
    assert runner.run_booking("b", "prime") == 0
    assert ran[-1] == (540, 30, [4, 5, "any"], day)   # the first part's court goes first
    assert toasts[-1][0] == "Booked (Prime Time part)"


def test_prime_part_follows_the_first_part(tmp_path, monkeypatch):
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    day = date(2026, 12, 7)
    assert runner.main_part_court("b", day, "me", "me") is None
    results.record("run", "b", "booked", "Booked", part="main", day=day.isoformat(), court=4)
    assert runner.main_part_court("b", day, "me", "me") == 4
    results.record("run", "b", "not_booked", "Not booked", part="main", day=(day + timedelta(days=7)).isoformat())
    assert runner.main_part_court("b", day + timedelta(days=7), "me", "me") is None
