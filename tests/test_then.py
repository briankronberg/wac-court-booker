"""Back-to-back: `then` adds a second session right after the first — one more reservation,
one more task, the first part's court first, and it still books if the first part failed."""
import asyncio
from datetime import date, datetime, timedelta

from wacbooker import clubtime, config, runner, scheduler, web
from fakes import FakeClock, FakeSite
from test_web import add_login, call, srv  # noqa: F401  (fixture)
from test_web import booking as form_booking


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


def test_then_field():
    assert booking(then=60).then == 60
    assert booking().then == 0
    assert booking(then=0).then == 0
    for bad in (45, 120, "abc", -30):
        errs = []
        b = config.parse_booking({"name": "b", "login": "me", "play": "singles", "partners": ["Pat Lee"],
                                  "day": "Tuesday", "time": "3:00 PM", "length": 90, "courts": [5, "any"],
                                  "then": bad}, 1, errs)
        assert b is None and any("then" in e for e in errs), (bad, b, errs)


def test_parts_span_reservations():
    b = booking(then=30)  # Friday 3:00–4:30 PM, second session 4:30–5:00 PM
    assert [(p.key, p.time, p.length, p.prime) for p in b.parts] == [("main", 900, 90, False), ("next", 990, 30, False)]
    assert b.for_part("next").time == 990 and b.for_part("next").length == 30
    assert b.span_end == 1020 and b.reservations == 2
    d = booking(play="doubles", day="Tuesday", time="6:00 PM", length=90, then=60)
    assert d.span_end == 1230 and d.reservations == 2


def test_next_prime_when_inside_prime_time():
    b = booking(time="9:00 AM", length=60, then=30)  # 9:00–10:00 AM prime; second session 10:00–10:30 AM prime
    assert [(p.key, p.prime) for p in b.parts] == [("main", True), ("next", True)]
    assert b.part("next").lead == timedelta(hours=24)
    b2 = booking(time="10:00 AM", length=30, then=30)  # main prime; second session 10:30–11:00 AM regular
    assert [(p.key, p.prime) for p in b2.parts] == [("main", True), ("next", False)]


def test_then_refuses_prime_edges():
    # the first session runs into Prime Time (Tuesday evening prime is 5:00–8:00 PM)
    errs = []
    b = config.parse_booking({"name": "b", "login": "me", "play": "singles", "partners": ["Pat Lee"],
                              "day": "Tuesday", "time": "4:30 PM", "length": 60, "courts": [5, "any"], "then": 30}, 1, errs)
    assert b is None and any("first session" in e and "Prime Time" in e for e in errs), errs
    # the second session would run into Prime Time (first 7:00–7:30 PM, second 7:30–8:30 PM)
    errs = []
    b = config.parse_booking({"name": "b", "login": "me", "play": "singles", "partners": ["Pat Lee"],
                              "day": "Tuesday", "time": "7:00 PM", "length": 30, "courts": [5, "any"], "then": 60}, 1, errs)
    assert b is None and any("second session" in e and "Prime Time" in e for e in errs), errs
    # a ball machine crossing an edge is refused the same way
    errs = []
    b = config.parse_booking({"name": "b", "login": "me", "play": "machine",
                              "day": "Tuesday", "time": "4:30 PM", "length": 60, "courts": [8, "any"], "then": 30}, 1, errs)
    assert b is None and any("Prime Time" in e for e in errs), errs


def test_then_refuses_past_midnight():
    errs = []
    b = config.parse_booking({"name": "b", "login": "me", "play": "doubles", "partners": ["A B", "C D", "E F"],
                              "day": "Tuesday", "time": "10:30 PM", "length": 60, "courts": [5, "any"], "then": 30}, 1, errs)
    assert b is None and any("midnight" in e for e in errs), errs


def test_template_documents_then():
    assert "then:" in config.TEMPLATE


# ------------------------------------------------------------ scheduler


def test_plan_has_a_task_for_the_second_session():
    cfg = config.Config(logins=[config.Login("me", "x")], bookings=[booking(then=30)])
    plans = scheduler.plan(cfg, "InteractiveToken", now=clubtime.slot_start(date(2026, 12, 1), 0))
    assert [p.name for p in plans] == [scheduler.task_name("b"), scheduler.task_name("b", "next")]
    assert " (second session)" in plans[1].name
    assert "--part next" in plans[1].xml and "--part" not in plans[0].xml


# ------------------------------------------------------------- runner


def test_next_part_runs_on_the_main_court(tmp_path, monkeypatch):
    from wacbooker import creds
    from wacbooker.engine import RunResult, Slot
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    b = booking(then=30)  # Friday 3:00–4:30 PM, second session 4:30–5:00 PM
    cfg = config.Config(logins=[config.Login("me", "x")], bookings=[b])
    monkeypatch.setattr(config, "load", lambda *a: (None, cfg))
    monkeypatch.setattr(creds, "has_password", lambda u: True)
    ran, toasts = [], []

    async def fake_run(cfg_, pb, occ, login, log, first_courts=None):
        fc = first_courts() if callable(first_courts) else (first_courts or {})
        court = 4 if pb.time == 900 else fc.get("me", pb.courts[0])  # the first part takes court 4
        ran.append((pb.time, list(pb.courts), occ.day, court, fc))
        return RunResult("booked", "Booked: Ct " + str(court),
                         slot=Slot(occ.day.strftime("%m/%d/%Y"), pb.time, pb.length, court))
    monkeypatch.setattr(runner, "_run_async", fake_run)
    monkeypatch.setattr(runner.notify, "toast", lambda t, m: toasts.append((t, m)))
    day = date(2026, 12, 18)
    main_w = clubtime.window_open(clubtime.slot_start(day, 15 * 60))
    next_w = clubtime.window_open(clubtime.slot_start(day, 16 * 60 + 30))

    monkeypatch.setattr(clubtime, "now_central", lambda: main_w - timedelta(minutes=75))
    assert runner.run_booking("b") == 0
    assert ran[-1] == (900, [5, 4, "any"], day, 4, {})

    # The second session: the first part's court goes first.
    monkeypatch.setattr(clubtime, "now_central", lambda: next_w - timedelta(minutes=75))
    assert runner.run_booking("b", "next") == 0
    assert ran[-1] == (990, [5, 4, "any"], day, 4, {"me": 4})
    assert toasts[-1][0] == "Booked (second session)"


def test_next_books_even_when_the_main_part_didnt(tmp_path, monkeypatch):
    from wacbooker import creds
    from wacbooker.engine import RunResult, Slot
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    b = booking(then=30)
    cfg = config.Config(logins=[config.Login("me", "x")], bookings=[b])
    monkeypatch.setattr(config, "load", lambda *a: (None, cfg))
    monkeypatch.setattr(creds, "has_password", lambda u: True)
    monkeypatch.setattr(runner.notify, "toast", lambda t, m: None)
    ran = []

    async def fake_run(cfg_, pb, occ, login, log, first_courts=None):
        fc = first_courts() if callable(first_courts) else (first_courts or {})
        ran.append((pb.time, list(pb.courts), fc))
        if pb.time == 990:
            return RunResult("booked", "Booked: Ct 5",
                             slot=Slot(occ.day.strftime("%m/%d/%Y"), pb.time, pb.length, 5))
        return RunResult("not_booked", "No court free.")
    monkeypatch.setattr(runner, "_run_async", fake_run)
    day = date(2026, 12, 18)
    main_w = clubtime.window_open(clubtime.slot_start(day, 15 * 60))
    next_w = clubtime.window_open(clubtime.slot_start(day, 16 * 60 + 30))

    monkeypatch.setattr(clubtime, "now_central", lambda: main_w - timedelta(minutes=75))
    assert runner.run_booking("b") == 1  # the first part lost its court
    monkeypatch.setattr(clubtime, "now_central", lambda: next_w - timedelta(minutes=75))
    assert runner.run_booking("b", "next") == 0  # the second session plays on its own
    assert ran[-1] == (990, [5, 4, "any"], {})  # no anchor: courts as configured


def test_group_next_uses_each_members_main_court(tmp_path, monkeypatch):
    from wacbooker import creds
    from wacbooker.engine import RunResult, Slot
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    raw = {"name": "b", "login": "me", "play": "singles", "partners": ["Pat Lee"], "day": "Tuesday",
           "time": "3:00 PM", "length": 90, "courts": [4, 5, "any"], "then": 30,
           "also": [{"login": "other", "partners": ["Sam Ortiz"]}]}
    errs = []
    b = config.parse_booking(raw, 1, errs)
    assert not errs, errs
    cfg = config.Config(logins=[config.Login("me", "x"), config.Login("other", "y")], bookings=[b])
    monkeypatch.setattr(config, "load", lambda *a: (None, cfg))
    monkeypatch.setattr(creds, "has_password", lambda u: True)
    monkeypatch.setattr(runner.notify, "toast", lambda t, m: None)
    day = date(2026, 12, 15)
    main_w = clubtime.window_open(clubtime.slot_start(day, 15 * 60))
    next_w = clubtime.window_open(clubtime.slot_start(day, 16 * 60 + 30))
    got = []

    async def fake_run(cfg_, pb, occ, login, log, first_courts=None):
        # a coordinated run: one result per member, its own court
        fc = first_courts() if callable(first_courts) else (first_courts or {})
        got.append((pb.time, fc))
        return {m.login: RunResult("booked", "Booked",
                                   slot=Slot(occ.day.strftime("%m/%d/%Y"), pb.time, pb.length,
                                             4 if m.login == "me" else 3))
                for m in b.members}
    monkeypatch.setattr(runner, "_run_async", fake_run)

    monkeypatch.setattr(clubtime, "now_central", lambda: main_w - timedelta(minutes=75))
    assert runner.run_booking("b") == 0
    assert got[-1] == (900, {})

    monkeypatch.setattr(clubtime, "now_central", lambda: next_w - timedelta(minutes=75))
    assert runner.run_booking("b", "next") == 0
    assert got[-1] == (990, {"me": 4, "other": 3})


# ----------------------------------------------------------- book now


def _book_now_setup(monkeypatch, open_courts=None):
    clock = FakeClock(clubtime.now_central().timestamp())
    kw = {"gate_s": 0}
    if open_courts is not None:
        kw["open_courts"] = open_courts
    site = FakeSite(clock, clock.now(), **kw)

    async def close():
        site.calls.append("close")
    site.close = close

    async def start(cfg, login, log):
        return site
    monkeypatch.setattr(runner, "start_site", start)
    monkeypatch.setattr(runner, "keep_family", lambda *a: None)
    monkeypatch.setattr(runner.results, "record", lambda *a, **k: None)
    monkeypatch.setattr(runner.notify, "toast", lambda *a, **k: None)
    return clock, site


def test_book_now_books_the_second_on_the_same_court(monkeypatch):
    clock, site = _book_now_setup(monkeypatch)
    now = clubtime.now_central()
    d = (now + timedelta(days=3)).date()
    while d.weekday() > 3:
        d += timedelta(days=1)
    errs = []
    b = config.parse_booking({"name": "n", "login": "me", "play": "doubles", "partners": ["A B", "C D", "E F"],
                              "date": d.isoformat(), "time": "3:00 PM", "length": 90, "courts": [5, "any"],
                              "then": 30}, 1, errs)
    assert not errs, errs
    said = []
    out = asyncio.run(runner.book_now(None, b, None, said.append, clock))
    assert out == "booked"
    assert [(s.length, s.court) for s in site.booked] == [(90, 5), (30, 5)]
    assert "close" in site.calls


def test_book_now_books_the_second_when_the_first_failed(monkeypatch):
    # no 90-minute court is free that day, but 30-minute ones are: the first part fails,
    # the second session still books.
    clock, site = _book_now_setup(monkeypatch, open_courts={90: [], 60: [5], 30: [5, 4, 3]})
    now = clubtime.now_central()
    d = (now + timedelta(days=3)).date()
    while d.weekday() > 3:
        d += timedelta(days=1)
    errs = []
    b = config.parse_booking({"name": "n", "login": "me", "play": "doubles", "partners": ["A B", "C D", "E F"],
                              "date": d.isoformat(), "time": "3:00 PM", "length": 90, "courts": [5, "any"],
                              "then": 30}, 1, errs)
    assert not errs, errs
    out = asyncio.run(runner.book_now(None, b, None, lambda s: None, clock))
    assert out == "not_booked"
    assert [(s.length, s.court) for s in site.booked] == [(30, 5)]


def test_book_now_defers_the_second_when_its_window_is_closed(monkeypatch):
    # booked the moment the first window opens: the second session's window (it opens
    # `length` minutes later) is still closed — it is left to its own scheduled task.
    now = clubtime.now_central()
    t = datetime.fromtimestamp(
        ((now + timedelta(hours=168)).timestamp() // 1800 + 1) * 1800, clubtime.CENTRAL)
    st = clubtime.slot_start(t.date(), t.hour * 60 + t.minute)
    main_w = clubtime.window_open(st)
    next_w = clubtime.window_open(clubtime.slot_start(st.date(), st.hour * 60 + st.minute + 90))
    assert main_w < now < next_w, (main_w, now, next_w)
    clock, site = _book_now_setup(monkeypatch)
    errs = []
    b = config.parse_booking({"name": "n", "login": "me", "play": "doubles", "partners": ["A B", "C D", "E F"],
                              "date": st.date().isoformat(), "time": clubtime.fmt_time(st.hour * 60 + st.minute),
                              "length": 90, "courts": [5, "any"], "then": 60}, 1, errs)
    assert not errs, errs
    said = []
    out = asyncio.run(runner.book_now(None, b, None, said.append, clock))
    assert out == "booked"
    assert [(s.length, s.court) for s in site.booked] == [(90, 5)]
    assert any("second session" in x for x in said)


def test_book_now_group_books_the_second_per_login(monkeypatch):
    # a coordinated one-off at the moment the window opens: each login's second session
    # goes first on the court that login's first part got.
    from wacbooker.engine import RunResult, Slot
    clock, site = _book_now_setup(monkeypatch)
    d = (clubtime.now_central() + timedelta(days=3)).date()
    while d.weekday() > 3:
        d += timedelta(days=1)
    raw = dict(name="g", login="me", play="doubles", partners=["A B", "C D", "E F"], date=d.isoformat(),
               time="3:00 PM", length=90, courts=[4, 5, "any"], then=30,
               also=[{"login": "other", "partners": ["G H", "I J", "K L"]}])
    errs = []
    b = config.parse_booking(raw, 1, errs)
    assert not errs, errs
    cfg = config.Config(logins=[config.Login("me", "x"), config.Login("other", "y")], bookings=[b])
    got = []

    async def fake_group(cfg_, pb, occ, clk, log, first_courts=None):
        got.append((pb.time, first_courts))
        return {m.login: RunResult("booked", "Booked",
                                   slot=Slot(occ.day.strftime("%m/%d/%Y"), pb.time, pb.length,
                                             4 if pb.time == 900 and m.login == "me"
                                             else 5 if pb.time == 900
                                             else first_courts[m.login]))
                for m in pb.members}

    monkeypatch.setattr(runner, "run_group", fake_group)
    out = asyncio.run(runner.book_now(cfg, b, None, lambda s: None))
    assert out == "booked"
    assert got[0] == (900, None)
    assert got[1] == (990, {"me": 4, "other": 5})


def test_book_now_group_defers_the_second_when_its_window_is_closed(monkeypatch):
    # the coordinated version of the same: the second session's window is still closed
    # while the first part books, so the second is left to its own task.
    from wacbooker.engine import RunResult, Slot
    clock, site = _book_now_setup(monkeypatch)
    now = clubtime.now_central()
    t = datetime.fromtimestamp(
        ((now + timedelta(hours=168)).timestamp() // 1800 + 1) * 1800, clubtime.CENTRAL)
    raw = dict(name="g", login="me", play="doubles", partners=["A B", "C D", "E F"], date=t.date().isoformat(),
               time=clubtime.fmt_time(t.hour * 60 + t.minute), length=90,
               courts=[5, "any"], then=60, also=[{"login": "other", "partners": ["G H", "I J", "K L"]}])
    errs = []
    b = config.parse_booking(raw, 1, errs)
    assert not errs, errs
    cfg = config.Config(logins=[config.Login("me", "x"), config.Login("other", "y")], bookings=[b])
    got = []

    async def fake_group(cfg_, pb, occ, clk, log, first_courts=None):
        got.append((pb.time, first_courts))
        return {m.login: RunResult("booked", "Booked",
                                   slot=Slot(occ.day.strftime("%m/%d/%Y"), pb.time, pb.length, 5))
                for m in pb.members}

    monkeypatch.setattr(runner, "run_group", fake_group)
    said = []
    out = asyncio.run(runner.book_now(cfg, b, None, said.append))
    assert out == "booked"
    assert [g[0] for g in got] == [t.hour * 60 + t.minute]
    assert any("second session" in x for x in said)


def test_book_now_group_books_the_second_when_the_first_failed(monkeypatch):
    # the coordinated version of the single-login rule: the second session is still
    # booked when the first part didn't — playing it alone is still play.
    from wacbooker.engine import RunResult, Slot
    clock, site = _book_now_setup(monkeypatch)
    d = (clubtime.now_central() + timedelta(days=3)).date()
    while d.weekday() > 3:
        d += timedelta(days=1)
    raw = dict(name="g", login="me", play="doubles", partners=["A B", "C D", "E F"], date=d.isoformat(),
               time="3:00 PM", length=90, courts=[5, "any"], then=30,
               also=[{"login": "other", "partners": ["G H", "I J", "K L"]}])
    errs = []
    b = config.parse_booking(raw, 1, errs)
    assert not errs, errs
    cfg = config.Config(logins=[config.Login("me", "x"), config.Login("other", "y")], bookings=[b])
    got = []

    async def fake_group(cfg_, pb, occ, clk, log, first_courts=None):
        got.append((pb.time, first_courts))
        if pb.length == 90:
            return {m.login: RunResult("not_booked", "no open court") for m in pb.members}
        return {m.login: RunResult("booked", "Booked",
                                   slot=Slot(occ.day.strftime("%m/%d/%Y"), pb.time, pb.length, 5))
                for m in pb.members}

    monkeypatch.setattr(runner, "run_group", fake_group)
    said = []
    out = asyncio.run(runner.book_now(cfg, b, None, said.append))
    assert out == "not_booked"
    assert [g[0] for g in got] == [900, 990]


# ------------------------------------------------------------------ web


def test_form_then_round_trips(srv):
    add_login(srv)
    _, r = call(srv, "/api/booking", {**form_booking(), "then": 30})
    assert r["ok"], r
    _, state = call(srv, "/api/state")
    b = state["bookings"][0]
    assert b["then"] == 30
    assert "second session 30 min right after" in b["title"]


def test_book_now_job_sends_then(srv, monkeypatch):
    add_login(srv)
    from conftest import REAL_JOB_WORK
    from test_availability import wait_job
    monkeypatch.setattr(web.WebApp, "_job_work", REAL_JOB_WORK)
    d3 = (clubtime.now_central() + timedelta(days=3)).date().isoformat()
    body = {"kind": "book-now", "play": "doubles", "partners": ["A B", "C D", "E F"], "date": d3,
            "time": 15 * 60, "length": 90, "courts": [5, "any"], "then": 30}
    ran = []

    async def fake(cfg, b, login, say, clock=None):
        ran.append(b.then)
        return "booked"
    monkeypatch.setattr(runner, "book_now", fake)
    _, r = call(srv, "/api/job", {**body, "confirmed": True})
    assert r.get("job"), r
    j = wait_job(srv, r["job"]["id"])
    assert j["ok"] and ran == [30]


# ------------------------------------------------- own lock per part


def test_next_runs_while_the_main_run_holds_its_lock(tmp_path, monkeypatch):
    from wacbooker import creds
    from wacbooker.engine import RunResult, Slot
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    b = booking(then=30)
    cfg = config.Config(logins=[config.Login("me", "x")], bookings=[b])
    monkeypatch.setattr(config, "load", lambda *a: (None, cfg))
    monkeypatch.setattr(creds, "has_password", lambda u: True)
    monkeypatch.setattr(runner.notify, "toast", lambda t, m: None)
    ran = []

    async def fake_run(cfg_, pb, occ, login, log, first_courts=None):
        ran.append(pb.time)
        return RunResult("booked", "Booked: Ct 5", slot=Slot(occ.day.strftime("%m/%d/%Y"), pb.time, pb.length, 5))
    monkeypatch.setattr(runner, "_run_async", fake_run)
    day = date(2026, 12, 18)
    next_w = clubtime.window_open(clubtime.slot_start(day, 16 * 60 + 30))
    monkeypatch.setattr(clubtime, "now_central", lambda: next_w - timedelta(minutes=75))

    # the main run still holds its lock while the second session starts
    with runner.run_lock("b"):
        assert runner.run_booking("b", "next") == 0
    assert ran == [990]


def test_a_run_that_cannot_start_says_so(tmp_path, monkeypatch):
    from wacbooker import creds
    from wacbooker.engine import RunResult, Slot
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    b = booking(then=30)
    cfg = config.Config(logins=[config.Login("me", "x")], bookings=[b])
    monkeypatch.setattr(config, "load", lambda *a: (None, cfg))
    monkeypatch.setattr(creds, "has_password", lambda u: True)
    toasts, ran = [], []
    monkeypatch.setattr(runner.notify, "toast", lambda t, m: toasts.append((t, m)))

    async def fake_run(cfg_, pb, occ, login, log, first_courts=None):
        ran.append(pb.time)
        return RunResult("booked", "Booked: Ct 5", slot=Slot(occ.day.strftime("%m/%d/%Y"), pb.time, pb.length, 5))
    monkeypatch.setattr(runner, "_run_async", fake_run)
    day = date(2026, 12, 18)
    next_w = clubtime.window_open(clubtime.slot_start(day, 16 * 60 + 30))
    monkeypatch.setattr(clubtime, "now_central", lambda: next_w - timedelta(minutes=75))

    # another run of the second session is already going
    with runner.run_lock("b (second session)"):
        assert runner.run_booking("b", "next") == 1
    assert ran == []
    assert toasts[-1][0] == "Not booked" and "already" in toasts[-1][1], toasts
    last = runner.results.recent(5)[-1]
    assert last["part"] == "next" and last["status"] == "not_booked", last
