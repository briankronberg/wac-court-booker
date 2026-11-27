"""What the menu and the scheduled tasks actually run."""
from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import msvcrt
import re
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Callable

from . import clock, clubtime, config, creds, mail, notify, paths, results
from .config import Booking, Config, Login
from .engine import CONFIRMED, NOT_READY, UNKNOWN, Engine, RealClock, SiteError, Slot, day_conflict
from . import site as site_mod
from .site import ClubSite

Say = Callable[[str], None]


def _log(prefix: str) -> Callable[[str], None]:
    lg = notify.logger()
    return lambda m: lg.info(f"[{prefix}] {m}")


def keep_awake(on: bool = True) -> None:
    """Stop Windows sleeping while a booking runs."""
    try:
        flags = 0x80000000 | (0x00000001 if on else 0)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:  # noqa: BLE001
        pass


@contextmanager
def run_lock(name: str):
    """One run per booking at a time (Task Scheduler also refuses a second copy)."""
    paths.ensure()
    p = paths.locks_dir() / (re.sub(r"[^A-Za-z0-9_-]", "_", name) + ".lock")
    f = open(p, "a+")
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        raise RuntimeError("another run of this booking is already going")
    try:
        yield
    finally:
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        f.close()


def make_site(cfg: Config, login: Login, log: Callable[[str], None], browser: str | None = None) -> ClubSite:
    return ClubSite(login.username, lambda: creds.get_password(login.username),
                    browser=browser or cfg.browser, show_window=cfg.show_window, log=log)


async def start_site(cfg: Config, login: Login, log: Callable[[str], None]) -> ClubSite:
    """Start the configured browser; if the app's own Chromium won't start, try Edge."""
    site = make_site(cfg, login, log)
    try:
        await site.start()
        return site
    except SiteError as e:
        if cfg.browser != "hidden":
            raise
        log(f"{e}; trying Microsoft Edge instead")
        site = make_site(cfg, login, log, browser="edge")
        await site.start()
        return site


# ---------------------------------------------------------------- scheduled run

def span(start: int, length: int) -> str:
    return f"{clubtime.fmt_time(start)} to {clubtime.fmt_time(start + length)}"


def main_part_court(name: str, day, login: str, own: str) -> int | None:
    """The court `login`'s regular part of a split booking got on `day`, or None if it
    wasn't booked. Records without a login predate coordinated logins: they are the
    booking's own, so they only count for `own`."""
    for r in reversed(results.recent(300)):
        if (r.get("kind") == "run" and r.get("booking") == name and r.get("part", "main") == "main"
                and r.get("day") == day.isoformat() and r.get("login", own) == login):
            return r.get("court") if r.get("status") == "booked" else None
    return None


def run_and_report(name: str, part: str = "main") -> int:
    """What the scheduled task runs: the booking run, then (when email is set up) one
    plain email with what its notifications said, and the engine's timing lines under a
    details divider. A guard-slot run emails only when its outcome is unknown: otherwise
    the booking's own run says what happened to the guard slot."""
    seen: list[tuple[str, str]] = []
    lines: list[str] = []
    lg = notify.logger()

    class _Grab(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())
    grab = _Grab()
    lg.addHandler(grab)
    real = notify.toast

    def tee(title: str, body: str):
        seen.append((title, body))
        return real(title, body)
    notify.toast = tee
    try:
        rc = run_booking(name, part)
    finally:
        notify.toast = real
        lg.removeHandler(grab)
    if not seen or (part == "blocker" and all(t != "Check your bookings" for t, _ in seen)):
        return rc
    _, cfg = config.load()
    if not cfg.ok or not mail.configured(cfg):
        return rc
    # Only the engine's timing lines (no names): "[booking] W+44.9s press -> CONFIRMED".
    details = [x for x in lines if re.search(r"\] W[+-]\d", x)
               and "signed in as" not in x and "run for" not in x]
    summary = "\n\n".join(f"{t}\n{b}" for t, b in seen)
    ok, why = mail.send(cfg, seen[-1][0], summary, details[-60:])
    lg.info(f"[{name}] email: {why}")
    return rc


def run_booking(name: str, part: str = "main") -> int:
    label ={"prime": " (Prime Time part)", "next": " (second session)", "blocker": " (guard slot)"}.get(part, "")
    log = _log(name + label)
    doc, cfg = config.load()
    if not cfg.ok:
        msg = "Not booked: bookings.yaml has a mistake. Open WAC Court Booker to fix it."
        log(msg + " " + " | ".join(cfg.errors))
        results.record("run", name, "not_booked", msg)
        notify.toast("Not booked", msg)
        return 2
    b = cfg.booking(name)
    if b is None:
        log("no booking with this name in bookings.yaml (old task?); nothing to do")
        return 2
    if not b.active:
        log("paused; nothing to do")
        return 0
    if part not in {p.key for p in b.parts}:
        log(f"this booking has no {part} part any more (old task?); nothing to do")
        return 0
    now = clubtime.now_central()
    occ = b.due(now, part)
    if occ is None:
        past = [o for o in b.occurrences(now - timedelta(hours=12), 2, part) if o.window < now]
        if past and past[0].day not in b.skip:
            msg = (f"Not booked: the PC was off or asleep when {clubtime.fmt_when(past[0].start)} "
                   f"opened. Book on the club site.")
            log(msg)
            results.record("run", name, "missed", msg)
            notify.toast("Not booked", msg)
            return 1
        log("no booking window due now; nothing to do")
        return 0
    if occ.day in b.skip:
        msg = f"Skipped {clubtime.fmt_when(occ.start)} as asked."
        log(msg)
        results.record("run", name, "skipped", msg, part=part, day=occ.day.isoformat())
        return 0
    pb = b.for_part(part)
    first_courts = None
    if part in ("prime", "next"):
        # Only makes sense next to the first part: same court if it can. A second session
        # (unlike Prime Time) still books on its own when the first part wasn't booked.
        if b.also:
            # coordinated logins: each login's own court from the first part goes first for it
            first_courts = {m.login: main_part_court(name, occ.day, m.login, b.login) for m in b.members}
            if part == "prime" and all(c is None for c in first_courts.values()):
                msg = (f"Didn't book the Prime Time part ({span(pb.time, pb.length)} "
                       f"{occ.day:%a %m/%d}): the first part wasn't booked.")
                log(msg)
                results.record("run", name, "skipped", msg, part=part, day=occ.day.isoformat())
                return 0
            first_courts = {l: c for l, c in first_courts.items() if c is not None}
            if first_courts:
                log(f"second part; each login's first part went first: {first_courts}")
        else:
            got = main_part_court(name, occ.day, b.login, b.login)
            if got is None:
                if part == "prime":
                    msg = (f"Didn't book the Prime Time part ({span(pb.time, pb.length)} "
                           f"{occ.day:%a %m/%d}): the first part wasn't booked.")
                    log(msg)
                    results.record("run", name, "skipped", msg, part=part, day=occ.day.isoformat())
                    return 0
            else:
                pb.courts = [got] + [c for c in b.courts if c != got]
                if "any" not in pb.courts:
                    pb.courts.append("any")
                which = "second session" if part == "next" else "Prime Time part"
                log(f"{which}; the first part got court {got}, so it goes first")
    login = cfg.login(b.login)
    missing = [m.login for m in b.members if not creds.has_password(cfg.login(m.login).username)]
    if missing:
        who = " and ".join(f"'{n}'" for n in missing)
        msg = (f"Not booked: no saved password for login{'s' if len(missing) > 1 else ''} {who} "
               f"(or Windows Credential Manager wasn't reachable). Book on the club site.")
        log(msg)
        results.record("run", name, "not_booked", msg)
        notify.toast("Not booked", msg)
        return 1
    if part == "blocker":
        # The guard run has its own lock: the main task starts while this one still runs.
        try:
            with run_lock(name + " (blocker)"):
                keep_awake(True)
                try:
                    out = asyncio.run(_guard_async(cfg, b, occ, log))
                finally:
                    keep_awake(False)
        except RuntimeError as e:
            log(f"not started: {e}")
            return 1
        return _finish_guard(b, occ, out, log)
    guards = None
    if part == "main" and b.blocker:
        # Looked up after the wait: the guard run may still be going when this task starts.
        def guards():
            return {m.login: guard_slot(name, occ.day, m.login, b.login) for m in b.members}
    try:
        with run_lock(name):
            keep_awake(True)
            try:
                extra = (guards,) if guards else ()  # only a main part with a guard passes it on
                res = asyncio.run(_run_async(cfg, pb, occ, login, log, first_courts, *extra))
            finally:
                keep_awake(False)
    except RuntimeError as e:
        log(f"not started: {e}")
        return 1
    if b.also:
        # one result per member, one toast for the group
        return _finish_group(b, part, occ, res, log)
    title = {"booked": "Booked", "unsure": "Check your bookings"}.get(res.status, "Not booked")
    pp = next((p for p in b.parts if p.key == "prime"), None)
    if pp is not None and part == "main" and res.booked:
        po = clubtime.window_open(clubtime.slot_start(occ.day, pp.time), pp.lead)
        res.message += (f" The Prime Time part ({span(pp.time, pp.length)}) books 24 hours ahead, "
                        f"{clubtime.fmt_when(po)}.")
    elif part == "prime":
        title += " (Prime Time part)"
    elif part == "next":
        title += " (second session)"
    results.record("run", name, res.status, res.message, part=part, day=occ.day.isoformat(),
                   court=res.slot.court if res.slot else None,
                   slot=res.slot.describe() if res.slot else "", attempts=len(res.attempts),
                   accepted_at=next((a["t"] for a in res.attempts if a["outcome"] == CONFIRMED), None))
    notify.toast(title, res.message)
    log(f"done: {res.status}: {res.message}")
    return 0 if res.booked else 1


async def _run_async(cfg: Config, b: Booking, occ: clubtime.Occurrence, login: Login, log,
                     first_courts: dict | None = None, guards=None):
    offset, src = clock.measure()
    offset = offset or 0.0
    log(f"target {clubtime.fmt_when(occ.start)}, window {occ.window:%m/%d %H:%M:%S} Central; "
        f"PC clock correction {offset:+.2f}s ({src})")
    rc = RealClock(offset, measure=clock.server_offset)
    wait = occ.window.timestamp() - clubtime.STAGE_LEAD.total_seconds() - rc.now()
    if wait > 0:
        log(f"waiting {wait / 60:.0f} min until 15 minutes before the window")
        await asyncio.sleep(wait)
    found = {k: v for k, v in (guards() if guards else {}).items() if v is not None}
    if found:
        log("guard slots, cancelled once the booking is settled: "
            + ", ".join(f"{k} {v.describe()}" for k, v in found.items()))
        first_courts = {**{k: v.court for k, v in found.items()}, **(first_courts or {})}
    if b.also:
        # coordinated logins: one site per login, all sharing this clock
        return await run_group(cfg, b, occ, rc, log, first_courts, found)
    try:
        site = await start_site(cfg, login, log)
    except SiteError as e:
        from .engine import RunResult
        return RunResult("not_booked", f"Not booked: {e}. Book on the club site.")
    try:
        guard = found.get(login.nickname)
        res = await Engine(b, occ, site, rc, log=log,
                           first_court=guard.court if guard else None).run()
        await settle_guard(site, guard, res, b.name, occ.day, login.nickname, log)
        if res.status == "not_booked":
            await site.release()
        return res
    finally:
        keep_family(login, site)
        await site.close()


async def run_group(cfg: Config, b: Booking, occ: clubtime.Occurrence, clock, log,
                    first_courts: dict | None = None, guards: dict | None = None) -> dict:
    """Book one occurrence with every login of the booking at the same time: one site per
    login, all sharing `clock`, and a Group so the courts end up different, side by side
    when the sheet allows. Returns {login nickname: RunResult}."""
    from .engine import RunResult
    from .group import Group
    group = Group(len(b.members))

    async def one(i: int):
        member = b.members[i]
        lg = cfg.login(member.login)
        try:
            site = await start_site(cfg, lg, log)
        except SiteError as e:
            return RunResult("unsure", f"couldn't open {member.login}'s page: {e}")
        eng = Engine(b.for_member(member), occ, site, clock, log=log, chooser=group.chooser(i),
                     first_court=first_courts.get(member.login) if first_courts else None)
        try:
            res = await eng.run()
            await settle_guard(site, (guards or {}).get(member.login), res, b.name, occ.day,
                               member.login, log)
        except SiteError as e:
            res = RunResult("unsure", f"{member.login}: {e}")
        finally:
            if res.status == "not_booked":
                await site.release()
            keep_family(lg, site)
            await site.close()
        return res

    out = await asyncio.gather(*[one(i) for i in range(len(b.members))])
    return {m.login: r for m, r in zip(b.members, out)}


def _finish_group(b: Booking, part: str, occ: clubtime.Occurrence, out: dict, log) -> int:
    """Record one result per member of a coordinated run and toast the group once."""
    lines = []
    for m in b.members:
        r = out[m.login]
        results.record("run", b.name, r.status, r.message, part=part, day=occ.day.isoformat(),
                       login=m.login, court=r.slot.court if r.slot else None,
                       slot=r.slot.describe() if r.slot else "", attempts=len(r.attempts),
                       accepted_at=next((a["t"] for a in r.attempts if a["outcome"] == CONFIRMED), None))
        if r.status == "booked":
            lines.append(f"Ct {r.slot.court} for {m.login}" + getattr(r, "guard_note", ""))
        else:
            lines.append(f"{m.login}: {r.message}")
    all_booked = all(r.status == "booked" for r in out.values())
    title = ("Booked" if all_booked else
             "Check your bookings" if any(r.status == "unsure" for r in out.values()) else "Not booked")
    msg = " \u00b7 ".join(lines)
    notify.toast(title, msg)
    log(f"done: {msg}")
    return 0 if all_booked else 1


# ---------------------------------------------------------------- blockers (guard slots)

def plan_blocker(avail: dict, day, now: datetime, main_start: int, court_order: list,
                 main_length: int = 30) -> tuple[int, int, int] | None:
    """Where the guard slot goes: (court, start, length), or None. The old system's rule:
    the earliest of main - 60 and main - 30 that is free right up to the main start, on a
    court that is also free when play starts. Courts in preference order: the named
    courts, then (with 'any') the rest by number."""
    named = [c for c in court_order if c != "any"]
    order = named + (sorted(c for c in avail["courts"] if c not in named) if "any" in court_order else [])
    for length in (60, 30):
        start = main_start - length
        if start < site_mod.FIRST_START:
            continue
        for c in order:
            sheet = past_cut(avail["courts"].get(c) or [False] * site_mod.DAY_MINUTES, day, now)
            if site_mod.free_for(sheet, start, length) and site_mod.free_for(sheet, main_start, main_length):
                return c, start, length
    return None


def guard_slot(name: str, day, login: str, own: str) -> Slot | None:
    """The guard slot `login` booked for `day`, if it's still there (not cancelled).
    Records without a login are the booking's own login's (`own`)."""
    for r in reversed(results.recent(300)):
        if (r.get("kind") == "run" and r.get("booking") == name and r.get("day") == day.isoformat()
                and r.get("login", own) == login):
            if r.get("part") == "blocker-cancel" and r.get("status") == "cancelled":
                return None
            if r.get("part") == "blocker":
                if r.get("status") != "booked" or r.get("start") is None:
                    return None
                return Slot(day.strftime("%m/%d/%Y"), int(r["start"]), int(r["length"]), int(r["court"]))
    return None


async def settle_guard(site, guard: Slot | None, res, name: str, day, login: str, log) -> None:
    """After the booking's outcome, in the same session: cancel the guard slot (a week
    ahead, so it's free). If the outcome is unknown, keep it, in case the booking went
    through. What happened goes on the end of res.message (and res.guard_note)."""
    if guard is None:
        return
    what = f"the guard slot ({span(guard.start, guard.length)} on Ct {guard.court})"
    if res.status == "unsure":
        note = (f" Kept {what} in case this booking went through: check the club site and "
                f"cancel it there if you don't need it.")
    else:
        try:
            await site.cancel(guard)
        except SiteError as e:
            log(f"couldn't cancel the guard slot: {e}")
            note = f" Couldn't cancel {what}: cancel it on the club site."
            results.record("run", name, "failed", str(e)[:200], part="blocker-cancel",
                           day=day.isoformat(), login=login)
        else:
            note = f" Cancelled {what}."
            results.record("run", name, "cancelled", note.strip(), part="blocker-cancel",
                           day=day.isoformat(), login=login)
    res.guard_note = note
    res.message += note


async def _guard_async(cfg: Config, b: Booking, occ: clubtime.Occurrence, log) -> dict:
    """The guard run: for each login, sign in, read the day's court sheet, plan the guard
    slot and book it with the usual engine. Coordinated logins plan one at a time on a
    shared list, next to a guard already planned when they can. Returns {login: RunResult}."""
    from .engine import RunResult
    offset, src = clock.measure()
    rc = RealClock(offset or 0.0, measure=clock.server_offset)
    log(f"guard slot for {clubtime.fmt_when(occ.start)}; PC clock correction {(offset or 0.0):+.2f}s ({src})")
    wait = occ.window.timestamp() - clubtime.STAGE_LEAD.total_seconds() - rc.now()
    if wait > 0:
        log(f"waiting {wait / 60:.0f} min until 15 minutes before the window")
        await asyncio.sleep(wait)
    main = b.part("main")
    main_length = min(b.for_part("main").lengths)
    date_s = occ.day.strftime("%m/%d/%Y")
    claimed: list[int] = []

    async def one(m):
        lg = cfg.login(m.login)
        try:
            site = await start_site(cfg, lg, log)
        except SiteError as e:
            return RunResult("not_booked", f"No guard slot: {e}.")
        res = None
        try:
            await site.login()
            try:
                rows = [r for r in await site.reservations(date_s, date_s, False) if r.get("date") == date_s]
            except SiteError as e:
                log(f"couldn't read {m.login}'s reservations ({e}); going ahead")
                rows = []
            if rows:
                res = RunResult("not_booked",
                                f"No guard slot for {occ.day:%a %m/%d}: {m.login} already has a reservation "
                                f"that day, and the club allows 2, so the room is kept for the booking itself.")
                return res
            avail = await site.day_availability(date_s)
            named = [c for c in b.courts if c != "any"]
            order = named + ([c for c in config.COURTS if c not in named] if "any" in b.courts else [])
            order = [c for c in order if c not in claimed]
            if claimed:  # coordinated logins: next to a guard slot already planned
                order.sort(key=lambda c: not any(abs(c - o) == 1 for o in claimed))
            plan = plan_blocker(avail, occ.day, clubtime.now_central(), main.time, order, main_length)
            if plan is None:
                res = RunResult("not_booked", f"No guard slot: no court is free in the hour before "
                                              f"{clubtime.fmt_time(main.time)} {occ.day:%a %m/%d}.")
                return res
            court, start, length = plan
            claimed.append(court)
            gb = replace(b.for_member(m).for_part("main"), time=start, length=length, courts=[court],
                         shorter_ok=False, then=0, blocker=False)
            st = clubtime.slot_start(occ.day, start)
            gocc = clubtime.Occurrence(occ.day, st, clubtime.window_open(st))
            log(f"{m.login}: guard slot {span(start, length)} on Ct {court}")
            res = await Engine(gb, gocc, site, rc, log=log).run()
            if not res.booked:
                res.message = "Guard slot: " + res.message
            return res
        except SiteError as e:
            res = RunResult("unsure", f"Guard slot: {e}")
            return res
        finally:
            if res is not None and res.status == "not_booked":
                await site.release()
            keep_family(lg, site)
            await site.close()

    out = await asyncio.gather(*[one(m) for m in b.members])
    return {m.login: r for m, r in zip(b.members, out)}


def _finish_guard(b: Booking, occ: clubtime.Occurrence, out: dict, log) -> int:
    """Record each login's guard slot (its start and length, for the main run to cancel)
    and toast once."""
    lines = []
    for m in b.members:
        r = out[m.login]
        results.record("run", b.name, r.status, r.message, part="blocker", day=occ.day.isoformat(),
                       login=m.login, court=r.slot.court if r.slot else None,
                       start=r.slot.start if r.slot else None, length=r.slot.length if r.slot else None,
                       slot=r.slot.describe() if r.slot else "")
        if r.booked:
            lines.append(f"Guard slot booked: {r.slot.describe()}" + (f" for {m.login}" if b.also else ""))
        else:
            lines.append((f"{m.login}: " if b.also else "") + r.message)
    all_booked = all(r.booked for r in out.values())
    title = ("Guard slot booked" if all_booked else
             "Check your bookings" if any(r.status == "unsure" for r in out.values()) else "Not booked")
    msg = " · ".join(lines)
    if all_booked:
        msg += ". It's cancelled as soon as the booking itself is settled."
    notify.toast(title, msg)
    log(f"done: {msg}")
    return 0 if all_booked else 1


# ---------------------------------------------------------------- book now

def book_now_block(b: Booking, now: datetime) -> str | None:
    """Why a one-off booking can't be booked right now, or None: every part's booking
    window must be open and the time still ahead."""
    for p in b.parts:
        if p.key == "next":
            continue  # the second session defers instead of blocking: its window is checked at booking
        if p.key == "blocker":
            continue  # Book Now doesn't book the guard slot: once play opens, it protects nothing
        st = clubtime.slot_start(b.date, p.time)
        when = f"{span(p.time, p.length)} on {b.date:%a} {b.date.month}/{b.date.day}"
        if st <= now:
            return f"{when} has already started"
        w = clubtime.window_open(st, p.lead)
        if w > now:
            return f"the club opens {when} for booking {clubtime.fmt_when(w)}"
    return None


async def book_now(cfg: Config, b: Booking, login: Login, say: Say, clock=None) -> str:
    """Book a one-off booking straight away, its window already open: the same engine a
    scheduled run uses, with W = now. A Prime Time part goes second, same court first,
    and only if the first part was booked. A second session books right after, if its
    window is open (it defers otherwise) and even if the first part didn't book.
    Returns 'booked', 'not_booked' or 'unsure'."""
    log = _log(f"book now {b.name}")
    clk = clock or RealClock()
    why = book_now_block(b, clubtime.now_central())
    if why:
        say(f"Not booked: {why}.")
        return "not_booked"
    if b.also:
        return await _book_now_group(cfg, b, say, clk, log)
    try:
        site = await start_site(cfg, login, log)
    except SiteError as e:
        say(f"Not booked: {e}.")
        return "not_booked"
    statuses: list[str] = []
    try:
        got = None
        deferred = 0
        # Book Now books only the play itself: once its window is open, every slot that
        # starts earlier is open too, so a guard slot would protect nothing.
        parts = [p for p in b.parts if p.key != "blocker"]
        for p in parts:
            pb = b.for_part(p.key)
            st = clubtime.slot_start(b.date, p.time)
            w = datetime.fromtimestamp(clk.now(), clubtime.CENTRAL)  # W = now: the window is open
            if p.key == "prime":
                if got is None:
                    break
                pb.courts = [got] + [c for c in b.courts if c != got]
                if "any" not in pb.courts:
                    pb.courts.append("any")
            elif p.key == "next":
                wo = clubtime.window_open(st, p.lead)
                if wo > w:
                    say(f"second session {span(p.time, p.length)} on {b.date:%a %b} {b.date.day}: the club "
                        f"opens booking {clubtime.fmt_when(wo)} — left to its own task")
                    deferred += 1
                    continue
                if got is not None:
                    pb.courts = [got] + [c for c in b.courts if c != got]
                    if "any" not in pb.courts:
                        pb.courts.append("any")
            say(f"Booking {span(p.time, p.length)} on {b.date:%a %b} {b.date.day}…")
            occ = clubtime.Occurrence(b.date, st, w)
            res = await Engine(pb, occ, site, clk, log=log).run()
            if res.status == "not_booked":
                await site.release()
            say(res.message)
            results.record("book-now", b.name, res.status, res.message, part=p.key, day=b.date.isoformat(),
                           court=res.slot.court if res.slot else None, slot=res.slot.describe() if res.slot else "",
                           attempts=len(res.attempts))
            notify.toast({"booked": "Booked", "unsure": "Check your bookings"}.get(res.status, "Not booked"), res.message)
            statuses.append(res.status)
            if not res.booked:
                if p.key == "next" or not any(q.key == "next" for q in parts):
                    break
                # a first part that didn't book doesn't stop the second session:
                # playing it alone is still play
            got = res.slot.court if res.slot else None
    finally:
        keep_family(login, site)
        await site.close()
    if statuses and all(s == "booked" for s in statuses) and len(statuses) + deferred == len(parts):
        return "booked"
    return "unsure" if "unsure" in statuses else "not_booked"


async def _book_now_group(cfg: Config, b: Booking, say, clk, log) -> str:
    """Book a coordinated one-off: one site per login per part, each login's own court
    first for the second part, which goes only if every login got the first one. A
    second session (then) still books when the first part didn't, and defers when
    its window isn't open yet."""
    statuses: list[str] = []
    first_courts = None
    deferred = 0
    parts = [p for p in b.parts if p.key != "blocker"]  # no guard slot for Book Now
    for p in parts:
        pb = b.for_part(p.key)
        st = clubtime.slot_start(b.date, p.time)
        w = datetime.fromtimestamp(clk.now(), clubtime.CENTRAL)  # W = now: the window is open
        if p.key == "prime" and not first_courts:
            say("Not booked: the Prime Time part needs every login's first part booked.")
            break
        if p.key == "next":
            wo = clubtime.window_open(st, p.lead)
            if wo > w:
                say(f"second session {span(p.time, p.length)} on {b.date:%a %b} {b.date.day}: the club "
                    f"opens booking {clubtime.fmt_when(wo)} — left to its own task")
                deferred += 1
                continue
        say(f"Booking {span(p.time, p.length)} on {b.date:%a %b} {b.date.day}…")
        occ = clubtime.Occurrence(b.date, st, w)
        out = await run_group(cfg, pb, occ, clk, log, first_courts)
        for m in b.members:
            r = out[m.login]
            say(r.message)
            results.record("book-now", b.name, r.status, r.message, part=p.key, day=b.date.isoformat(),
                           login=m.login, court=r.slot.court if r.slot else None,
                           slot=r.slot.describe() if r.slot else "", attempts=len(r.attempts))
        statuses.extend(r.status for r in out.values())
        if all(r.status == "booked" for r in out.values()):
            first_courts = {m.login: out[m.login].slot.court for m in b.members}
            notify.toast("Booked", " \u00b7 ".join(f"Ct {out[m.login].slot.court} for {m.login}" for m in b.members))
        else:
            notify.toast("Not booked", " \u00b7 ".join(f"{m.login}: {out[m.login].message}" for m in b.members))
            if p.key == "next" or not any(q.key == "next" for q in parts):
                break
    if statuses and all(s == "booked" for s in statuses) and len(statuses) + deferred * len(b.members) == len(parts) * len(b.members):
        return "booked"
    return "unsure" if "unsure" in statuses else "not_booked"


# ---------------------------------------------------------------- tests (menu 8)

async def login_test(cfg: Config, login: Login, say: Say) -> str | None:
    log = _log(f"test {login.nickname}")
    try:
        site = await start_site(cfg, login, log)
    except SiteError as e:
        say(f"  The browser didn't start: {e}")
        return None
    try:
        name = await site.login()
        say(f"  Signed in to the club site as {name}.")
        return name
    except SiteError as e:
        say(f"  Sign-in failed: {e}.")
    except LookupError as e:
        say(f"  {e}")
    finally:
        await site.close()
    return None


def load_buddies() -> dict:
    try:
        return json.loads(paths.buddies_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_buddies(nickname: str, names: list[str] | None = None, family: list[str] | None = None) -> None:
    """Store a login's buddy names and/or family members; what isn't given is kept."""
    data = load_buddies()
    entry = dict(data.get(nickname) or {})
    now = datetime.now().isoformat(timespec="seconds")
    if names is not None:
        entry["names"], entry["updated"] = names, now
    if family is not None:
        entry["family"], entry["family_updated"] = family, now
    data[nickname] = entry
    paths.ensure()
    paths.buddies_file().write_text(json.dumps(data, indent=1), encoding="utf-8")


def load_family(nickname: str) -> list[str] | None:
    """Family members seen on the participants page, or None if never read."""
    return (load_buddies().get(nickname) or {}).get("family")


def keep_family(login: Login, site) -> None:
    """Save the family members a site session saw on a participants page, if any."""
    fam = getattr(site, "family", None)
    if fam is not None:
        try:
            save_buddies(login.nickname, family=fam)
        except OSError:
            pass


async def read_family(cfg: Config, login: Login, say: Say) -> list[str] | None:
    """Family members are only listed on the participants page, which opens once a
    court is in the cart. Put a quiet 30-minute slot in the cart, read the list,
    press Back (which empties the cart again). Never presses Continue to Cart."""
    log = _log(f"family {login.nickname}")
    try:
        site = await start_site(cfg, login, log)
    except SiteError as e:
        say(f"  The browser didn't start: {e}")
        return None
    try:
        await site.login()
        now = clubtime.now_central()
        slot = None
        for days in range(2, 7):
            d = (now + timedelta(days=days)).strftime("%m/%d/%Y")
            slot = pick_quiet_slot(await site.list_open(d, 30, "singles"), ["any"], now)
            if slot:
                break
        if not slot:
            say("  No quiet court is open in the next few days to open the participants page with. Try later.")
            return None
        log(f"opening the participants page with {slot.describe()} (not booking it)")
        await site.stage(slot)
        if site.family is None:
            await site._note_family(15)
        try:
            await site.back_out()
            log("pressed Back; the cart is empty again")
        except SiteError as e:
            say(f"  Couldn't press Back ({e}). The court leaves your cart by itself after a few minutes.")
        if site.family is None:
            say("  The participants page didn't show its member list. Try again later.")
            return None
        save_buddies(login.nickname, family=site.family)
        return site.family
    except (SiteError, LookupError) as e:
        say(f"  Couldn't read family members: {e}")
        return None
    finally:
        await site.close()


async def buddy_list(cfg: Config, login: Login, say: Say) -> list[str] | None:
    log = _log(f"buddies {login.nickname}")
    try:
        site = await start_site(cfg, login, log)
    except SiteError as e:
        say(f"  The browser didn't start: {e}")
        return None
    try:
        await site.login()
        names = await site.buddies()
        save_buddies(login.nickname, names)
        return names
    except (SiteError, LookupError) as e:
        say(f"  Couldn't read the buddy list: {e}")
        return None
    finally:
        await site.close()


async def dry_run(cfg: Config, b: Booking, say: Say) -> bool:
    """Read-only: open the next target day's grid and say what would be booked."""
    log = _log(f"dry run {b.name}")
    if b.prime_kind == "split":
        p = next((x for x in b.parts if x.key == "prime"), None)
        if p is not None:
            say(f"  Checking the regular part. The Prime Time part ({span(p.time, p.length)}) books 24 hours ahead.")
    b = b.for_part("main")
    nxt = b.next_runs(clubtime.now_central(), 1)
    if not nxt:
        say("  This booking has no future date to check.")
        return False
    occ = nxt[0]
    say(f"  Next run: window opens {clubtime.fmt_when(occ.window)}, for {clubtime.fmt_when(occ.start)}.")
    login = cfg.login(b.login)
    try:
        site = await start_site(cfg, login, log)
    except SiteError as e:
        say(f"  The browser didn't start: {e}")
        return False
    try:
        await site.login()
        open_by_len = await site.find_open(occ.day.strftime("%m/%d/%Y"), b.time, b.lengths, b.site_play)
        for L in b.lengths:
            courts = sorted(open_by_len.get(L, {}))
            say(f"  {L} min at {clubtime.fmt_time(b.time)}: "
                f"{'courts ' + ', '.join(map(str, courts)) + ' show open' if courts else 'no court shows open'}")
        from .engine import pick
        choice = pick(open_by_len, b, set())
        if choice:
            say(f"  It would go for {choice.describe()}. Stopped before booking (dry run).")
        else:
            say("  None of your courts shows open at that time right now. "
                "(Courts free up and fill in all week; this is only a snapshot.)")
        return True
    except (SiteError, LookupError) as e:
        say(f"  Dry run failed: {e}")
        return False
    finally:
        await site.close()


# ---------------------------------------------------------------- availability (read-only)
# Free courts are read from the doubles list: it covers every hour, while singles in
# Prime Time only lists courts 24 hours ahead. A court free for doubles is free.

def _court_list(courts: list[int]) -> str:
    c = [str(x) for x in courts]
    return c[0] if len(c) == 1 else ", ".join(c[:-1]) + " and " + c[-1]


def past_cut(day_minutes: list[bool], day, now: datetime) -> list[bool]:
    """Today, times already gone can't be booked (the club page does the same)."""
    if day != now.date():
        return day_minutes
    cut = min(now.hour * 60 + now.minute + 1, len(day_minutes))
    return [False] * cut + day_minutes[cut:]


def read_at(now: datetime) -> str:
    return clubtime.fmt_time(now.hour * 60 + now.minute)


SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}


def _club_form(host: str):
    m = re.fullmatch(r"\s*([^,]+?)\s*,\s*([^\W\d_])\.?\s*", host or "")
    return (m.group(1), m.group(2).upper()) if m else None


def _first_last(name: str) -> list[str]:
    return [w for w in name.split() if w.lower() not in SUFFIXES]


def name_fits(host: str, name: str) -> bool:
    """Does a full name fit the club's short form ('Lee, P.' fits 'Pat Leeds')?"""
    form, words = _club_form(host), _first_last(name)
    return bool(form and len(words) >= 2 and words[0][0].upper() == form[1]
                and words[-1].lower().startswith(form[0].lower()))


def initial_last(name: str) -> str:
    words = _first_last(name)
    return f"{words[0][0].upper()}. {words[-1]}" if len(words) >= 2 else name.strip()


def load_players() -> dict:
    """{club id: full name} you've named in the calendar. Kept on this PC only."""
    try:
        data = json.loads(paths.players_file().read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_player(host_id, club: str, name: str) -> str:
    """Remember (or, with an empty name, forget) who a booker is. Returns how the calendar
    will show them. The name must fit the club's short form, which catches typos."""
    key = str(int(host_id))
    name = " ".join((name or "").split())
    data = load_players()
    if not name:
        data.pop(key, None)
        shown = short_name(club, known_names())
    else:
        if len(name) > 60 or not name_fits(club, name):
            part, initial = _club_form(club) or ("?", "?")
            raise ValueError(f"\"{name}\" doesn't fit the club's \"{club}\": the first name should start with "
                             f"\"{initial}\" and the last name with \"{part}\".")
        data[key] = name
        shown = initial_last(name)
    paths.ensure()
    paths.players_file().write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    return shown


def short_name(host: str, known: list[str]) -> str:
    """The club's 'Kro, B.' as 'B. Kronberg' when exactly one person the app knows (you,
    your buddies, your family) fits it; otherwise 'B. Kro…'. Never anything longer
    than the club itself shows, except a known person's last name."""
    form = _club_form(host)
    if not form:
        return (host or "").strip()
    part, initial = form
    fits = set()
    for name in known:
        if name_fits(host, name):
            fits.add(_first_last(name)[-1])
    if len(fits) == 1:
        return f"{initial}. {fits.pop()}"
    return f"{initial}. {part}{'…' if len(part) >= 3 else ''}"


def known_names(member: str = "") -> list[str]:
    """Everyone the app knows by full name: buddies and family of every login, and you."""
    out = [member] if member else []
    for entry in load_buddies().values():
        out += list(entry.get("names") or []) + list(entry.get("family") or [])
    return out


def calendar_cells(avail: dict, day, now: datetime, known: list[str] | None = None,
                   players: dict | None = None) -> dict:
    """The calendar window's data: for each court and half hour, 'open', 'booked'
    (a member's reservation), 'closed' (a lesson, a block or the club's hours) or
    'past'; and the half hours each ball machine is free."""
    starts = list(range(site_mod.FIRST_START, site_mod.LAST_END, 30))
    today_cut = now.hour * 60 + now.minute if day == now.date() else -1
    cells, who, hosts = {}, {}, {}
    players = players or {}
    for c in config.COURTS:
        free = avail["courts"].get(c, [False] * site_mod.DAY_MINUTES)
        booked = avail["booked"].get(c, [])
        row, names, ids = {}, {}, {}
        for m in starts:
            if m + 30 <= today_cut:
                row[m] = "past"
            elif site_mod.free_for(past_cut(free, day, now), m, 30):
                row[m] = "open"
            elif hit := [x for x in booked if x[0] < m + 30 and m < x[1]]:
                row[m] = "booked"
                host = hit[0][2] if len(hit[0]) > 2 else ""
                hid = hit[0][3] if len(hit[0]) > 3 else 0
                if hid and str(hid) in players:
                    names[m] = initial_last(players[str(hid)])
                elif host:
                    names[m] = short_name(host, known or [])
                if hid and _club_form(host):
                    ids[m] = [hid, host]
            else:
                row[m] = "closed"
        cells[str(c)] = row
        who[str(c)] = names
        hosts[str(c)] = ids
    machines = {k: site_mod.open_starts(past_cut(v, day, now)) for k, v in avail.get("machines", {}).items()}
    return {"date": day.isoformat(), "courts": list(config.COURTS), "starts": starts, "cells": cells, "who": who, "hosts": hosts,
            "machines": machines, "machine_courts": list(site_mod.MACHINE_COURTS),
            "machine_labels": {k: m["label"] for k, m in site_mod.MACHINES.items()}, "read_at": read_at(now)}


def courts_free(avail: dict, day, now: datetime, start: int, length: int, machine: str | None = None) -> list[int]:
    """Courts free for the whole of start..start+length (with a ball machine: only the
    courts it goes on, and only if the machine is free too)."""
    if machine:
        m = avail.get("machines", {}).get(machine)
        if not m or not site_mod.free_for(past_cut(m, day, now), start, length):
            return []
    pool = site_mod.MACHINE_COURTS if machine else config.COURTS
    return [c for c in pool if site_mod.free_for(past_cut(avail["courts"].get(c, []) or [False] * 1440, day, now),
                                                 start, length)]


async def court_check_on(site: ClubSite, day, start: int, lengths: list[int], courts: list, say: Say,
                         machine: str | None = None) -> dict:
    """Which courts are free right now at `start` on `day`, for each length (read-only)."""
    avail = await site.day_availability(day.strftime("%m/%d/%Y"), machines=bool(machine))
    now = clubtime.now_central()
    if machine == "either":  # the Genie first, as a booking would
        machine = "genie" if courts_free(avail, day, now, start, lengths[0], "genie") or not courts_free(
            avail, day, now, start, lengths[0], "regular") else "regular"
    when = f"{clubtime.fmt_time(start)} on {day:%a %b} {day.day}"
    out = {L: courts_free(avail, day, now, start, L, machine) for L in lengths}
    named = [c for c in courts if c != "any"]
    main = out.get(lengths[0], [])
    what = f" with the {site_mod.MACHINES[machine]['label']}" if machine else ""
    if machine and not site_mod.free_for(past_cut(avail["machines"].get(machine, []), day, now), start, lengths[0]):
        say(f"The {site_mod.MACHINES[machine]['label']} is taken at {when} for {lengths[0]} minutes.")
        other = next((k for k in site_mod.MACHINES if k != machine), None)
        if other and courts_free(avail, day, now, start, lengths[0], other):
            say(f"The {site_mod.MACHINES[other]['label']} is free then.")
    elif main:
        say(f"Yes. At {when}, for {lengths[0]} minutes{what}, court{'s' if len(main) > 1 else ''} "
            f"{_court_list(main)} {'are' if len(main) > 1 else 'is'} open right now.")
        mine = [c for c in named if c in main]
        if named and mine:
            say(f"Your first choice that's open: court {mine[0]}.")
        elif named:
            say(f"None of your courts ({_court_list(named)}) is open, but the others are.")
    else:
        say(f"No court{' that takes a ball machine' if machine else ''} is open at {when} for {lengths[0]} minutes right now.")
    for L in lengths[1:]:
        if not main and out.get(L):
            say(f"For {L} minutes: court{'s' if len(out[L]) > 1 else ''} {_court_list(out[L])}.")
    say("Courts can still be taken (or freed) before the club opens booking for that time.")
    why = None
    try:
        ds = day.strftime("%m/%d/%Y")
        why = day_conflict(await site.reservations(ds, ds, False), ds, start, start + max(lengths))
    except SiteError:
        pass  # the court answer above still stands
    if why:
        say(f"But {why}, so the club would turn this booking away.")
    return {"open": out, "conflict": why}


# ---------------------------------------------------------------- reservations

def reservation_view(r: dict, now: datetime) -> dict:
    """A reservation from the report, for the page: its date (ISO), what it is, and
    whether cancelling costs a fee (less than 24 hours to go) or it has started."""
    d = datetime.strptime(r["date"], "%m/%d/%Y").date()
    start = clubtime.slot_start(d, r["start"])
    left = start - now
    machine = site_mod.MACHINES.get(r.get("machine") or "", {}).get("label")
    svc = re.sub(r"^[\d.]+\s*", "", r.get("service") or "").strip()
    what = machine[0].upper() + machine[1:] if machine else (svc or "Court")
    return {**r, "day": d.isoformat(), "what": what, "span": span(r["start"], r["end"] - r["start"]),
            "started": left.total_seconds() <= 0, "fee": 0 < left.total_seconds() < 24 * 3600}


async def reservations_on(site: ClubSite, frm, to, family: bool, say: Say) -> dict:
    """The login's reservations from `frm` to `to` (dates), read-only."""
    say("Reading your reservations…")
    a, z = frm.strftime("%m/%d/%Y"), to.strftime("%m/%d/%Y")
    rows = await site.reservations(a, z, False)
    mine = {r["guid"] for r in rows}
    if family:  # the report doesn't say whose; the ones not in your own list are family members'
        rows = await site.reservations(a, z, True)
    now = clubtime.now_central()
    return {"from": frm.isoformat(), "to": to.isoformat(), "family": family,
            "items": [{**reservation_view(r, now), "mine": r["guid"] in mine} for r in rows], "read_at": read_at(now)}


async def cancel_on(site: ClubSite, r: dict, say: Say) -> dict:
    """Cancel one reservation the person chose in the app, then read it back."""
    when = f"{datetime.strptime(r['date'], '%m/%d/%Y'):%a %b} {int(r['date'].split('/')[1])}, {span(r['start'], r['end'] - r['start'])}"
    where = f" on court {r['court']}" if r.get("court") else ""
    say(f"Cancelling {when}{where}…")
    note = await site.cancel_reservation(r["guid"], r)
    msg = f"Cancelled {when}{where}."
    results.record("cancel", r.get("what") or "Reservation", "cancelled", msg)
    notify.toast("Reservation cancelled", msg)
    say(msg)
    if note:
        say(f"The club site said: {note}")
    return {"cancelled": r["guid"]}


async def calendar_on(site: ClubSite, day, say: Say) -> dict:
    """Every court's half hours on `day`, and the ball machines', for the calendar window."""
    say("Reading the court sheet…")
    avail = await site.day_availability(day.strftime("%m/%d/%Y"), machines=True)
    return calendar_cells(avail, day, clubtime.now_central(), known_names(getattr(site, "member_name", "")),
                          load_players())


def pick_quiet_slot(slots: list[Slot], courts: list, now: datetime) -> Slot | None:
    """Earliest slot more than 25 h away (free to cancel), preferred court first."""
    named = [c for c in courts if c != "any"]
    ok = [s for s in slots if clubtime.slot_start(datetime.strptime(s.date, "%m/%d/%Y").date(), s.start)
          > now + timedelta(hours=25)]
    for c in named:
        hit = [s for s in ok if s.court == c]
        if hit:
            return min(hit, key=lambda s: s.start)
    if "any" in courts or not named:
        return min(ok, key=lambda s: (s.start, s.court)) if ok else None
    return None


async def test_booking(cfg: Config, login: Login, play: str, partners: list[str], courts: list,
                       say: Say, ask: Callable[[str], bool]) -> str:
    """Book a quiet 30-minute slot now (more than 24 h away), then offer to cancel it.
    Returns 'cancelled', 'kept', 'not_booked' or 'unsure'."""
    log = _log("test booking")
    shown = say

    def say(msg: str) -> None:  # everything the person sees goes in the log too
        shown(msg)
        log(msg.strip())

    log(f"partners: {', '.join(partners) or '(none)'}; courts: {', '.join(map(str, courts))}")
    now = clubtime.now_central()
    try:
        site = await start_site(cfg, login, log)
    except SiteError as e:
        say(f"  The browser didn't start: {e}")
        return "not_booked"
    try:
        await site.login()
        slot = None
        a, z = (now + timedelta(days=2)).strftime("%m/%d/%Y"), (now + timedelta(days=6)).strftime("%m/%d/%Y")
        try:  # skip days the club would refuse: at its daily limit, or a clash
            mine = await site.reservations(a, z, False)
        except SiteError as e:
            log(f"couldn't read your reservations ({e}); trying anyway")
            mine = []
        for days in range(2, 7):
            d = (now + timedelta(days=days)).strftime("%m/%d/%Y")
            ok = [s for s in await site.list_open(d, 30, play)
                  if not day_conflict(mine, d, s.start, s.end)]
            slot = pick_quiet_slot(ok, courts, now)
            if slot:
                break
        if not slot:
            say("  No quiet 30-minute slot is open on your courts in the next few days. Nothing booked.")
            return "not_booked"
        say(f"  Booking {slot.describe()} ...")
        await site.stage(slot)
        outcome = None
        for i in range(10):
            # The time is already open, so the rows should be on; from the fourth try
            # press anyway so the club says what's wrong.
            a = await site.attempt(partners, force=i >= 3)
            log(f"press -> {a.outcome} {a.detail}")
            outcome = a.outcome
            if a.outcome in (CONFIRMED, UNKNOWN):
                break
            if a.outcome != NOT_READY and "AddFamilyMembers" not in await site.url():
                await site.stage(slot)
            await asyncio.sleep(2)
        if outcome == UNKNOWN:
            exists = await site.reservation_exists(slot)
            if exists is None:
                say("  The club site didn't answer and its reservation list wouldn't load. "
                    "Check your reservations on the club site.")
                results.record("test", "test booking", "unsure", slot.describe())
                return "unsure"
            outcome = CONFIRMED if exists else None
        if outcome != CONFIRMED:
            say(f"  The club site didn't take the booking ({outcome}). Nothing booked.")
            try:
                if "AddFamilyMembers" in await site.url():
                    await site.back_out()
            except SiteError:
                pass
            results.record("test", "test booking", "not_booked", slot.describe())
            return "not_booked"
        exists = await site.reservation_exists(slot)
        say(f"  Booked {slot.describe()}." +
            (" It shows in your reservation report." if exists else ""))
        results.record("test", "test booking", "booked", slot.describe())
        ask("  Check it on the club site or app. Do you see it?")
        if not ask("  Cancel this test booking now? (It's more than 24 hours away, so it's free.)"):
            say("  Kept. Cancel it yourself on the club site if you change your mind.")
            return "kept"
        await site.cancel(slot)
        gone = await site.reservation_exists(slot)
        if gone is False:
            say("  Cancelled, and it's gone from your reservation report.")
            results.record("test", "test booking", "cancelled", slot.describe())
            return "cancelled"
        say("  The cancel went through, but I couldn't confirm it's gone. Check the club site.")
        return "unsure"
    except (SiteError, LookupError) as e:
        if not isinstance(e, SiteError):
            import traceback
            log("unexpected error:\n" + traceback.format_exc())
        say(f"  Test booking stopped: {e}. Check your reservations on the club site.")
        results.record("test", "test booking", "unsure", str(e))
        return "unsure"
    except Exception as e:  # noqa: BLE001 - never crash the wizard; keep the details
        import traceback
        log("unexpected error:\n" + traceback.format_exc())
        say(f"  Test booking stopped by an unexpected error ({type(e).__name__}: {str(e)[:200]}). "
            "Check your reservations on the club site; the log has the details.")
        results.record("test", "test booking", "unsure", f"{type(e).__name__}: {e}")
        return "unsure"
    finally:
        keep_family(login, site)
        await site.close()
