"""What the menu and the scheduled tasks actually run."""
from __future__ import annotations

import asyncio
import ctypes
import json
import msvcrt
import re
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Callable

from . import clock, clubtime, config, creds, notify, paths, results
from .config import Booking, Config, Login
from .engine import CONFIRMED, NOT_READY, UNKNOWN, Engine, RealClock, SiteError, Slot
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


def main_part_court(name: str, day) -> int | None:
    """The court the regular part of a split booking got on `day`, or None if it wasn't booked."""
    for r in reversed(results.recent(300)):
        if (r.get("kind") == "run" and r.get("booking") == name and r.get("part", "main") == "main"
                and r.get("day") == day.isoformat()):
            return r.get("court") if r.get("status") == "booked" else None
    return None


def run_booking(name: str, part: str = "main") -> int:
    log = _log(name if part == "main" else f"{name} (Prime Time part)")
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
    if part == "prime":
        # The Prime Time part only makes sense next to the regular part: same court if it can.
        got = main_part_court(name, occ.day)
        if got is None:
            msg = (f"Didn't book the Prime Time part ({span(pb.time, pb.length)} "
                   f"{occ.day:%a %m/%d}): the first part wasn't booked.")
            log(msg)
            results.record("run", name, "skipped", msg, part=part, day=occ.day.isoformat())
            return 0
        pb.courts = [got] + [c for c in b.courts if c != got]
        if "any" not in pb.courts:
            pb.courts.append("any")
        log(f"Prime Time part; the first part got court {got}, so it goes first")
    login = cfg.login(b.login)
    if not creds.has_password(login.username):
        msg = (f"Not booked: no saved password for login '{login.nickname}' "
               f"(or Windows Credential Manager wasn't reachable). Book on the club site.")
        log(msg)
        results.record("run", name, "not_booked", msg)
        notify.toast("Not booked", msg)
        return 1
    try:
        with run_lock(name):
            keep_awake(True)
            try:
                res = asyncio.run(_run_async(cfg, pb, occ, login, log))
            finally:
                keep_awake(False)
    except RuntimeError as e:
        log(f"not started: {e}")
        return 1
    title = {"booked": "Booked", "unsure": "Check your bookings"}.get(res.status, "Not booked")
    if b.prime_kind == "split" and part == "main" and res.booked:
        pp = b.part("prime")
        po = clubtime.window_open(clubtime.slot_start(occ.day, pp.time), pp.lead)
        res.message += (f" The Prime Time part ({span(pp.time, pp.length)}) books 24 hours ahead, "
                        f"{clubtime.fmt_when(po)}.")
    elif part == "prime":
        title += " (Prime Time part)"
    results.record("run", name, res.status, res.message, part=part, day=occ.day.isoformat(),
                   court=res.slot.court if res.slot else None,
                   slot=res.slot.describe() if res.slot else "", attempts=len(res.attempts),
                   accepted_at=next((a["t"] for a in res.attempts if a["outcome"] == CONFIRMED), None))
    notify.toast(title, res.message)
    log(f"done: {res.status}: {res.message}")
    return 0 if res.booked else 1


async def _run_async(cfg: Config, b: Booking, occ: clubtime.Occurrence, login: Login, log):
    offset, src = clock.measure()
    offset = offset or 0.0
    log(f"target {clubtime.fmt_when(occ.start)}, window {occ.window:%m/%d %H:%M:%S} Central; "
        f"PC clock correction {offset:+.2f}s ({src})")
    rc = RealClock(offset)
    wait = occ.window.timestamp() - clubtime.STAGE_LEAD.total_seconds() - rc.now()
    if wait > 0:
        log(f"waiting {wait / 60:.0f} min until 15 minutes before the window")
        await asyncio.sleep(wait)
    try:
        site = await start_site(cfg, login, log)
    except SiteError as e:
        from .engine import RunResult
        return RunResult("not_booked", f"Not booked: {e}. Book on the club site.")
    try:
        res = await Engine(b, occ, site, rc, log=log).run()
        if res.status == "not_booked":
            await site.release()
        return res
    finally:
        keep_family(login, site)
        await site.close()


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
        p = b.part("prime")
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


def calendar_cells(avail: dict, day, now: datetime) -> dict:
    """The calendar window's data: for each court and half hour, 'open', 'booked'
    (a member's reservation), 'closed' (a lesson, a block or the club's hours) or
    'past'; and the half hours each ball machine is free."""
    starts = list(range(site_mod.FIRST_START, site_mod.LAST_END, 30))
    today_cut = now.hour * 60 + now.minute if day == now.date() else -1
    cells = {}
    for c in config.COURTS:
        free = avail["courts"].get(c, [False] * site_mod.DAY_MINUTES)
        booked = avail["booked"].get(c, [])
        row = {}
        for m in starts:
            if m + 30 <= today_cut:
                row[m] = "past"
            elif site_mod.free_for(past_cut(free, day, now), m, 30):
                row[m] = "open"
            elif any(a < m + 30 and m < b for a, b in booked):
                row[m] = "booked"
            else:
                row[m] = "closed"
        cells[str(c)] = row
    machines = {k: site_mod.open_starts(past_cut(v, day, now)) for k, v in avail.get("machines", {}).items()}
    return {"date": day.isoformat(), "courts": list(config.COURTS), "starts": starts, "cells": cells,
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
    return {"open": out}


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
    return calendar_cells(avail, day, clubtime.now_central())


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
        for days in range(2, 7):
            d = (now + timedelta(days=days)).strftime("%m/%d/%Y")
            slot = pick_quiet_slot(await site.list_open(d, 30, play), courts, now)
            if slot:
                break
        if not slot:
            say("  No quiet 30-minute slot is open on your courts in the next few days. Nothing booked.")
            return "not_booked"
        say(f"  Booking {slot.describe()} ...")
        await site.stage(slot)
        outcome = None
        for _ in range(10):
            a = await site.attempt(partners)
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
