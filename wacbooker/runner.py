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

def run_booking(name: str) -> int:
    log = _log(name)
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
    now = clubtime.now_central()
    occ = clubtime.due_occurrence(b.day, b.date, b.time, now)
    if occ is None:
        past = [o for o in b.occurrences(now - timedelta(hours=12), 2) if o.window < now]
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
        results.record("run", name, "skipped", msg)
        return 0
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
                res = asyncio.run(_run_async(cfg, b, occ, login, log))
            finally:
                keep_awake(False)
    except RuntimeError as e:
        log(f"not started: {e}")
        return 1
    title = {"booked": "Booked", "unsure": "Check your bookings"}.get(res.status, "Not booked")
    results.record("run", name, res.status, res.message,
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


def save_buddies(nickname: str, names: list[str]) -> None:
    data = load_buddies()
    data[nickname] = {"updated": datetime.now().isoformat(timespec="seconds"), "names": names}
    paths.ensure()
    paths.buddies_file().write_text(json.dumps(data, indent=1), encoding="utf-8")


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
        open_by_len = await site.find_open(occ.day.strftime("%m/%d/%Y"), b.time, b.lengths, b.play)
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
        await site.close()
