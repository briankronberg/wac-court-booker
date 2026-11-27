"""The app's web page: a small server on 127.0.0.1 that the Start-menu shortcut opens.

Only Python's standard library. The page (web/index.html) talks to /api/... with a
random token it gets through the URL's #fragment, and the server refuses any request
whose Host isn't its own 127.0.0.1 address, so other websites can't reach it.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from . import APP_NAME, __version__, clock, clubtime, config, creds, live, notify, paths, results, runner, scheduler
from . import site as site_mod
from .config import Booking, Login
from .engine import SiteError

REPO = "briankronberg/wac-court-booker"
RELEASES_URL = f"https://github.com/{REPO}/releases"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE = Path(__file__).with_name("web") / "index.html"
CALENDAR_PAGE = Path(__file__).with_name("web") / "calendar.html"
IDLE_STOP = 180          # seconds without a heartbeat (window closed) before the server stops
FIRST_LOAD_WAIT = 300    # how long to wait for the page to load the first time
QUESTION_WAIT = 20 * 60  # an unanswered question in a job takes its default after this


def _log(msg: str) -> None:
    notify.logger().info(f"[web] {msg}")


# ---------------------------------------------------------------- plain-words views

def md(d: date) -> str:
    return f"{d:%a} {d:%b} {d.day}"


def when_text(dt: datetime) -> str:
    c = dt.astimezone(clubtime.CENTRAL)
    return f"{md(c.date())}, {clubtime.fmt_time(c.hour * 60 + c.minute)}"


def names_text(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def span_text(start: int, length: int) -> str:
    a, z = clubtime.fmt_time(start), clubtime.fmt_time((start + length) % (24 * 60))
    return f"{a[:-3]} to {z}" if a[-2:] == z[-2:] else f"{a} to {z}"


def courts_text(courts: list) -> str:
    named = [str(c) for c in courts if c != "any"]
    if not named:
        return "Any court"
    out = "Court " + ", then ".join(named)
    return out + (", then any court" if "any" in courts else "")


def prime_note(b: Booking) -> dict | None:
    """How Prime Time changes this booking, in plain words (singles and ball machines)."""
    kind = b.prime_kind
    if kind == "none":
        return None
    what = "ball machines" if b.play == "machine" else "singles courts"
    if kind == "all":
        return {"kind": "all", "text": f"Prime Time: the club opens {what} only 24 hours "
                                       "ahead, so the app books it then, not a week ahead."}
    prime = next((p for p in b.parts if p.key == "prime"), None)
    if prime is None:  # a second session next to a Prime Time session: the session itself books 24 hours ahead
        return {"kind": "all", "text": f"Prime Time: the club opens {what} only 24 hours "
                                       "ahead, so the app books it then, not a week ahead."}
    main = b.part("main")
    return {"kind": "split", "text": (
        f"{span_text(prime.time, prime.length)} is Prime Time, when the club opens {what} only "
        f"24 hours ahead. So the app books this in two parts: {span_text(main.time, main.length)} a week "
        f"ahead, then {span_text(prime.time, prime.length)} 24 hours ahead, on the same court if it's free. "
        f"Prime Time is often taken by lessons. For the best chance, change the time so the booking is "
        f"all inside or all outside Prime Time.")}


def booking_view(b: Booking, now: datetime, task: dict | None, prime_task: dict | None = None,
                 next_task: dict | None = None) -> dict:
    weekly = b.day is not None
    when = f"Every {clubtime.DAYS[b.day]}" if weekly else f"{b.date:%A}, {b.date:%B} {b.date.day}"
    v: dict[str, Any] = {
        "name": b.name, "login": b.login, "play": b.play, "machine": b.machine, "partners": b.partners, "day": b.day,
        "date": b.date.isoformat() if b.date else None, "time": b.time, "length": b.length,
        "then": b.then,
        "shorter_ok": b.shorter_ok, "courts": b.courts, "active": b.active,
        "skip": [d.isoformat() for d in b.skip],
        "title": f"{when}, {span_text(b.time, b.length)}"
                 + (f", second session {b.then} min right after" if b.then else ""),
        "who": b.what + (f" with {names_text(b.partners)}" if b.partners else "")
              + "".join(f"; also {m.login} with {names_text(m.partners)}" for m in b.also),
        "also": [{"login": m.login, "partners": m.partners} for m in b.also],
        "courts_text": courts_text(b.courts) + (f". Shorter if no court has {b.length} minutes."
                                                if b.shorter_ok else "."),
        "weekly": weekly,
        "prime": prime_note(b),
    }
    runs = []
    prime = next((p for p in b.parts if p.key == "prime"), None)
    split = prime is not None
    for o in b.next_runs(now - clubtime.LATE_OK, 2):
        on = o.run_at
        pc = clubtime.fmt_time(on.hour * 60 + on.minute)
        if on.date() != o.window.date():
            pc = f"{md(on.date())}, {pc}"
        r = {"plays": when_text(clubtime.slot_start(o.day, b.time)), "books": when_text(o.window), "pc_on": pc}
        if split:
            main, prime = b.part("main"), b.part("prime")
            pw = clubtime.window_open(clubtime.slot_start(o.day, prime.time), prime.lead)
            r["books"] = f"{span_text(main.time, main.length)} on {when_text(o.window)}"
            r["books_prime"] = f"{span_text(prime.time, prime.length)} on {when_text(pw)}"
        runs.append(r)
    v["runs"] = runs
    if weekly:
        v["upcoming"] = [{"date": o.day.isoformat(), "label": md(o.day), "skipped": o.day in b.skip}
                         for o in b.occurrences(now - clubtime.LATE_OK, 8)]
        v["skipping"] = [md(d) for d in sorted(b.skip) if d >= now.date()]
    else:
        v["upcoming"], v["skipping"] = [], []
    if not runs:
        v["task"] = {"ok": True, "text": "This date has passed. Remove it when you like."}
    elif not b.active:
        v["task"] = {"ok": True, "text": "Paused: nothing books until you turn it back on."}
    elif not task or (split and not prime_task) or (b.then and not next_task):
        v["task"] = {"ok": False, "text": "Not scheduled yet. Open Settings and press \"Rebuild scheduled tasks\"."}
    else:
        how = ("even when you're signed out" if task.get("logon") == "Password"
               else "while you're signed in to Windows (the screen can be locked)")
        v["task"] = {"ok": True, "text": f"Scheduled: runs {how}."}
    return v


def parse_version(v: str) -> tuple[int, ...]:
    out = []
    for part in str(v).strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


# ---------------------------------------------------------------- background jobs

class Job:
    """One club-site task (test login, buddy list ...) running in its own thread."""

    def __init__(self, kind: str, title: str):
        self.id = secrets.token_hex(6)
        self.kind, self.title = kind, title
        self.lines: list[str] = []
        self.done = False
        self.ok: bool | None = None
        self.question: dict | None = None
        self.data: Any = None  # a job's result for the page (court check, calendar)
        self._answer: bool | None = None
        self._answered = threading.Event()

    def say(self, msg: str = "") -> None:
        msg = " ".join(str(msg).split())
        if msg:
            self.lines.append(msg)

    def ask(self, text: str, default: bool = True) -> bool:
        self._answered.clear()
        self.question = {"text": text.strip(), "default": default}
        got = self._answered.wait(QUESTION_WAIT)
        self.question = None
        return self._answer if got else default

    def answer(self, yes: bool) -> None:
        self._answer = bool(yes)
        self._answered.set()

    def view(self) -> dict:
        return {"id": self.id, "kind": self.kind, "title": self.title, "lines": self.lines,
                "done": self.done, "ok": self.ok, "question": self.question, "data": self.data}


# ---------------------------------------------------------------- the app

class WebApp:
    def __init__(self):
        self.lock = threading.RLock()
        self.windows_password: str | None = None
        self.job: Job | None = None
        self.update_cache: tuple[float, dict] | None = None
        self.last_beat: float | None = None
        self.stop_requested = False
        self._live: live.Live | None = None

    @property
    def live(self) -> live.Live:
        if self._live is None:  # its thread starts on first use
            self._live = live.Live()
        return self._live

    def close(self) -> None:
        if self._live is not None:
            self._live.close()

    # --------------------------------------------------- reading
    def state(self) -> dict:
        doc, cfg = config.load()
        now = clubtime.now_central()
        try:
            tasks = {t["name"]: t for t in scheduler.status()}
        except Exception:  # noqa: BLE001
            tasks = {}
        buddies = runner.load_buddies()
        logins = []
        for lg in cfg.logins:
            entry = buddies.get(lg.nickname) or {}
            fam = entry.get("family")
            names = entry.get("names") or []
            logins.append({"nickname": lg.nickname, "username": lg.username,
                           "has_password": creds.has_password(lg.username),
                           "family": fam or [], "family_read": fam is not None,
                           "buddies": [n for n in names if n.lower() not in {f.lower() for f in fam or []}],
                           "buddies_read": "names" in entry})
        local = datetime.now().astimezone()
        return {
            "app": APP_NAME, "version": __version__,
            "errors": cfg.errors, "warnings": cfg.warnings, "config_file": str(paths.config_file()),
            "logins": logins,
            "bookings": [booking_view(b, now, tasks.get(scheduler.task_name(b.name)),
                                      tasks.get(scheduler.task_name(b.name, "prime")),
                                      tasks.get(scheduler.task_name(b.name, "next"))) for b in cfg.bookings],
            "prime_time": {"text": clubtime.PRIME_TEXT,
                           "spans": [[list(days), a, z] for days, a, z in clubtime.PRIME_TIME]},
            "settings": {"browser": cfg.browser, "show_window": cfg.show_window,
                         "run_signed_out": cfg.run_signed_out, "wake_timers": scheduler.wake_timers_on(),
                         "windows_password_held": bool(self.windows_password),
                         "desktop_shortcut": desktop_shortcut_path().exists()},
            "other_timezone": local.utcoffset() != now.utcoffset(),
            "courts": list(config.COURTS),
            "job": self.job.view() if self.job else None,
        }

    def results(self) -> dict:
        rows = list(reversed(results.recent(40)))
        out = []
        for r in rows:
            try:
                at = datetime.fromisoformat(r["at"])
                when = f"{md(at.date())}, {clubtime.fmt_time(at.hour * 60 + at.minute)}"
            except (KeyError, ValueError):
                when = str(r.get("at", ""))[:16]
            msg = r.get("message", "")
            if r.get("kind") == "test":
                msg = {"booked": "Booked", "cancelled": "Booked, then cancelled", "not_booked": "Not booked",
                       "unsure": "Unsure, check the club site"}.get(r.get("status"), r.get("status", "")) + f": {msg}"
            out.append({"when": when, "booking": r.get("booking", ""), "status": r.get("status", ""),
                        "kind": r.get("kind", ""), "message": msg})
        return {"results": out, "log_file": str(paths.log_file())}

    # --------------------------------------------------- saving
    def _commit(self, doc: Any, what: str) -> dict:
        new = config.from_doc(doc)
        if not new.ok:
            return {"ok": False, "errors": new.errors}
        config.save(doc)
        _log(f"saved: {what}")
        return {"ok": True, "saved": what, "warnings": new.warnings, **self._sync(new)}

    def _sync(self, cfg: config.Config) -> dict:
        pw = self.windows_password if cfg.run_signed_out else None
        try:
            r = scheduler.sync(cfg, pw)
        except Exception as e:  # noqa: BLE001
            return {"task_problem": f"Couldn't update Task Scheduler: {e}"}
        if r.logon == "InteractiveToken" and pw:
            self.windows_password = None
        return {"task_note": r.note, "task_errors": r.errors,
                "need_windows_password": bool(cfg.run_signed_out and r.logon != "Password" and not pw)}

    def _load(self) -> tuple[Any, config.Config]:
        doc, cfg = config.load()
        if doc is None:
            raise UserError("bookings.yaml can't be read: " + " ".join(cfg.errors))
        return doc, cfg

    def save_booking(self, body: dict) -> dict:
        with self.lock:
            doc, cfg = self._load()
            old_name = body.get("old_name")
            old = cfg.booking(old_name) if old_name else None
            if old_name and not old:
                raise UserError("That booking was changed somewhere else. Close this and try again.")
            b, errs = self._form_booking(cfg, body, old)
            if errs:
                return {"ok": False, "errors": errs}
            others = [x.name for x in cfg.bookings if not old or x.name != old.name]
            b.name = config.auto_name(b.play, b.partners, b.day, b.date, b.time, others, b.machine)
            if old and old.name != config.auto_name(old.play, old.partners, old.day, old.date, old.time, others,
                                                    old.machine):
                b.name = old.name  # a name typed by hand in bookings.yaml stays
            if b.date:
                w = clubtime.window_open(clubtime.slot_start(b.date, b.part().time), b.part().lead)
                if w < clubtime.now_central() + timedelta(minutes=20):
                    return {"ok": False, "errors": [
                        f"Booking for that date opened {clubtime.fmt_when(w)}, so there's nothing to schedule. "
                        "Use Book Now to book it straight away."]}
            config.put_booking(doc, b, replace=old.name if old else None)
            out = self._commit(doc, f"booking '{b.name}'")
            out["name"] = b.name
            return out

    def _form_booking(self, cfg: config.Config, body: dict, old: Booking | None = None):
        """The booking form's fields as a Booking (named 'x'), and any mistakes in them."""
        login = str(body.get("login") or (cfg.logins[0].nickname if cfg.logins else ""))
        if not cfg.login(login):
            raise UserError("Add your club login first (Settings).")
        try:
            minutes = int(body.get("time"))
        except (TypeError, ValueError):
            raise UserError("Choose a start time.")
        raw: dict[str, Any] = {
            "name": "x", "login": login, "play": body.get("play"),
            **({"machine": body.get("machine") or "either"} if body.get("play") == "machine" else {}),
            "partners": [" ".join(str(p).split()) for p in body.get("partners") or []],
            "time": clubtime.fmt_time(minutes), "length": body.get("length"),
            "shorter_ok": bool(body.get("shorter_ok")) and int(body.get("length") or 0) > 30,
            "courts": body.get("courts") or [],
            "skip": [d.isoformat() for d in old.skip] if old else [],
            "active": old.active if old else True,
        }
        also = str(body.get("also") or "").strip()
        if also:
            raw["also"] = [{"login": also, "partners": [p.strip() for p in (body.get("also_partners") or [])
                                                       if p.strip()]}]
        if body.get("then"):
            raw["then"] = int(body["then"])
        if body.get("weekly", True):
            if body.get("day") is None:
                raise UserError("Choose a day of the week.")
            raw["day"] = clubtime.DAYS[int(body["day"])]
            raw["skip"] = raw["skip"] if old and old.day == int(body["day"]) else []
        else:
            if not body.get("date"):
                raise UserError("Choose a date.")
            raw["date"] = body["date"]
            raw["skip"] = []
        errs: list[str] = []
        b = config.parse_booking(raw, 1, errs)
        return b, [e.replace("Booking 'x': ", "") for e in errs]

    def _booking(self, cfg: config.Config, name: str) -> Booking:
        b = cfg.booking(str(name or ""))
        if not b:
            raise UserError("That booking isn't there any more. The page will refresh.")
        return b

    def remove_booking(self, body: dict) -> dict:
        with self.lock:
            doc, cfg = self._load()
            b = self._booking(cfg, body.get("name"))
            config.remove_booking(doc, b.name)
            return self._commit(doc, f"removed '{b.name}'")

    def pause_booking(self, body: dict) -> dict:
        with self.lock:
            doc, cfg = self._load()
            b = self._booking(cfg, body.get("name"))
            b.active = not b.active if body.get("active") is None else bool(body["active"])
            config.put_booking(doc, b, replace=b.name)
            return self._commit(doc, f"'{b.name}' {'resumed' if b.active else 'paused'}")

    def skip_date(self, body: dict) -> dict:
        with self.lock:
            doc, cfg = self._load()
            b = self._booking(cfg, body.get("name"))
            if b.day is None:
                raise UserError("A one-off booking can't skip a date. Remove it instead.")
            try:
                d = date.fromisoformat(str(body.get("date")))
            except ValueError:
                raise UserError("That isn't a date.")
            if d.weekday() != b.day:
                raise UserError(f"{md(d)} isn't a {clubtime.DAYS[b.day]}.")
            today = clubtime.now_central().date()
            keep = [x for x in config.prune_skips(b, today) if x != d]
            b.skip = keep if body.get("skip") is False or (body.get("skip") is None and d in b.skip) else keep + [d]
            config.put_booking(doc, b, replace=b.name)
            return self._commit(doc, f"'{b.name}' {'skips' if d in b.skip else 'no longer skips'} {md(d)}")

    def add_login(self, body: dict) -> dict:
        user = str(body.get("username") or "").strip()
        pw = str(body.get("password") or "")
        body["password"] = ""
        if not user or not pw:
            raise UserError("Type your club username and password.")
        with self.lock:
            doc, cfg = self._load()
            nick = " ".join(str(body.get("nickname") or "").split())
            existing = next((x for x in cfg.logins if x.username.lower() == user.lower()), None)
            if not nick:
                nick = existing.nickname if existing else ("me" if not cfg.logins else user)
            creds.set_password(user, pw)
            del pw
            if self._live is not None:
                self._live.forget(user)
            login = Login(nick, user)
            config.put_login(doc, login)
            out = self._commit(doc, f"login '{nick}'")
        if out.get("ok"):
            out["job"] = self.start_job({"kind": "new-login", "login": nick})["job"]
        return out

    def remove_login(self, body: dict) -> dict:
        with self.lock:
            doc, cfg = self._load()
            lg = cfg.login(str(body.get("login") or ""))
            if not lg:
                raise UserError("That login isn't there any more.")
            used = [b.name for b in cfg.bookings if b.login == lg.nickname]
            if used:
                raise UserError(f"These bookings use it: {', '.join(used)}. Remove or change them first.")
            config.remove_login(doc, lg.nickname)
            out = self._commit(doc, f"removed login '{lg.nickname}'")
            if out.get("ok"):
                creds.delete_password(lg.username)
                if self._live is not None:
                    self._live.forget(lg.username)
            return out

    def settings(self, body: dict) -> dict:
        with self.lock:
            doc, cfg = self._load()
            changed = []
            if "browser" in body:
                br = str(body["browser"])
                if br not in config.BROWSERS:
                    raise UserError("Unknown browser.")
                config.set_setting(doc, "browser", br)
                if br == "hidden":
                    config.set_setting(doc, "show_window", False)
                changed.append(f"browser {br}")
            if "show_window" in body:
                config.set_setting(doc, "show_window", bool(body["show_window"]))
                changed.append("show window" if body["show_window"] else "hide window")
            if "run_signed_out" in body:
                config.set_setting(doc, "run_signed_out", bool(body["run_signed_out"]))
                if not body["run_signed_out"]:
                    self.windows_password = None
                changed.append(f"run while signed out: {'yes' if body['run_signed_out'] else 'no'}")
            return self._commit(doc, ", ".join(changed) or "settings")

    def windows_password_set(self, body: dict) -> dict:
        pw = str(body.get("password") or "")
        body["password"] = ""
        if not pw:
            raise UserError("Type your Windows password.")
        with self.lock:
            self.windows_password = pw
            del pw
            _, cfg = self._load()
            out = self._sync(cfg)
            out["ok"] = not out.get("task_errors") and not out.get("task_problem")
            out["signed_out"] = bool(self.windows_password)
            return out

    def rebuild(self) -> dict:
        with self.lock:
            _, cfg = self._load()
            if not cfg.ok:
                return {"ok": False, "errors": cfg.errors}
            return {"ok": True, "saved": "scheduled tasks rebuilt", **self._sync(cfg)}

    def wake_timers(self) -> dict:
        ok, msg = scheduler.enable_wake_timers()
        return {"ok": ok, "message": msg}

    # --------------------------------------------------- jobs
    def start_job(self, body: dict) -> dict:
        kind = str(body.get("kind") or "")
        with self.lock:
            if self.job and not self.job.done:
                raise UserError("Another check is still running. Wait for it to finish.")
            _, cfg = self._load()
            login = cfg.login(str(body.get("login") or "")) if body.get("login") else (
                cfg.logins[0] if cfg.logins else None)
            titles = {"test-login": "Testing your login", "buddies": "Reading your buddy list",
                      "family": "Reading your family members", "new-login": "Checking your login",
                      "dry-run": "Looking at the court sheet", "clock": "Checking the PC clock",
                      "test-booking": "Test booking", "court-check": "Validate booking",
                      "calendar": "Court calendar", "reservations": "My reservations",
                      "cancel": "Cancel a reservation", "book-now": "Book now"}
            if kind not in titles:
                raise UserError("Unknown check.")
            if kind != "clock" and not login:
                raise UserError("Add your club login first.")
            job = Job(kind, titles[kind])
            work = self._job_work(kind, job, cfg, login, body)
            self.job = job

        def run():
            try:
                job.ok = bool(work())
            except Exception as e:  # noqa: BLE001
                _log(f"{kind} failed:\n{traceback.format_exc()}")
                job.say(f"Stopped by an unexpected error ({type(e).__name__}). The log has the details.")
                job.ok = False
            finally:
                job.done = True
        threading.Thread(target=run, daemon=True, name=f"job-{kind}").start()
        return {"ok": True, "job": job.view()}

    def _job_work(self, kind: str, job: Job, cfg: config.Config, login: Login | None, body: dict) -> Callable:
        say = job.say
        if kind == "clock":
            def work():
                ok, msg = clock.report()
                say(msg)
                return ok
            return work
        if kind == "test-login":
            return lambda: asyncio.run(runner.login_test(cfg, login, say)) is not None
        if kind == "buddies":
            def work():
                names = asyncio.run(runner.buddy_list(cfg, login, say))
                if names is not None:
                    say(f"Found {len(names)} people on your buddy list.")
                return names is not None
            return work
        if kind == "family":
            def work():
                fam = asyncio.run(runner.read_family(cfg, login, say))
                if fam is not None:
                    say(f"Family members: {names_text(fam)}." if fam else "No family members on this account.")
                return fam is not None
            return work
        if kind == "new-login":
            def work():
                if asyncio.run(runner.login_test(cfg, login, say)) is None:
                    say("Check the username and password, then add the login again.")
                    return False
                names = asyncio.run(runner.buddy_list(cfg, login, say))
                if names is not None:
                    say(f"Found {len(names)} people on your buddy list.")
                return True
            return work
        if kind == "dry-run":
            b = self._booking(cfg, body.get("booking"))
            return lambda: asyncio.run(runner.dry_run(cfg, b, say))
        if kind == "test-booking":
            partner = " ".join(str(body.get("partner") or "").split())
            if not partner:
                raise UserError("Choose who you'd play with.")
            b = next((x for x in cfg.bookings if x.login == login.nickname), None)
            courts = b.courts if b else ["any"]

            def work():
                r = asyncio.run(runner.test_booking(cfg, login, "singles", [partner], courts, say,
                                                    lambda q: job.ask(q, True)))
                return r in ("cancelled", "kept")
            return work
        if kind == "book-now":
            b, errs = self._form_booking(cfg, {**body, "weekly": False})
            if errs:
                raise UserError(" ".join(errs))
            b.name = config.auto_name(b.play, b.partners, None, b.date, b.time, [], b.machine)
            why = runner.book_now_block(b, clubtime.now_central())
            if why:
                raise UserError(f"Book Now isn't open yet: {why}.")
            if not body.get("confirmed"):
                raise UserError("Confirm the booking first.")
            return lambda: asyncio.run(runner.book_now(cfg, b, login, say)) == "booked"
        if kind == "reservations":
            try:
                frm, to = date.fromisoformat(str(body.get("from"))), date.fromisoformat(str(body.get("to")))
            except ValueError:
                raise UserError("Choose the dates first.")
            if to < frm:
                frm, to = to, frm
            if (to - frm).days > 366:
                raise UserError("Choose at most a year at a time.")
            family = bool(body.get("family"))
            return self._live_work(job, cfg, login, lambda site: runner.reservations_on(site, frm, to, family, say))
        if kind == "cancel":
            r = body.get("reservation") or {}
            try:
                r = {"guid": str(r["guid"]).lower(), "date": str(r["date"]), "start": int(r["start"]),
                     "end": int(r["end"]), "court": r.get("court"), "what": str(r.get("what") or "")[:60]}
                datetime.strptime(r["date"], "%m/%d/%Y")
            except (KeyError, TypeError, ValueError):
                raise UserError("That reservation isn't there any more. Refresh the list.")
            if not body.get("confirmed"):
                raise UserError("Confirm the cancellation first.")
            return self._live_work(job, cfg, login, lambda site: runner.cancel_on(site, r, say), retry=False)
        if kind in ("court-check", "calendar"):
            try:
                day = date.fromisoformat(str(body.get("date")))
            except ValueError:
                raise UserError("Choose the date first.")
            if kind == "calendar":
                return self._live_work(job, cfg, login, lambda site: runner.calendar_on(site, day, say))
            try:
                start, length = int(body.get("time")), int(body.get("length") or 60)
            except (TypeError, ValueError):
                raise UserError("Choose the start time first.")
            lengths = [length] + ([x for x in (60, 30) if x < length] if body.get("shorter_ok") else [])
            courts = list(body.get("courts") or ["any"])
            machine = body.get("machine") or None
            if machine is not None and machine not in config.MACHINES:
                raise UserError("Unknown ball machine.")
            return self._live_work(job, cfg, login, lambda site: runner.court_check_on(
                site, day, start, lengths, courts, say, machine))
        raise UserError("Unknown check.")

    def _live_work(self, job: Job, cfg: config.Config, login: Login, fn, retry: bool = True) -> Callable:
        """A job through the warm club session; its result goes to job.data."""
        def work():
            try:
                job.data = self.live.run(cfg, login, fn, job.say, retry=retry)
            except SiteError as e:
                job.say(f"Couldn't read the club site: {e}")
                return False
            return job.data is not None
        return work

    def job_view(self, job_id: str) -> dict:
        if not self.job or self.job.id != job_id:
            raise UserError("That check has finished.")
        return {"ok": True, "job": self.job.view()}

    def job_answer(self, body: dict) -> dict:
        if not self.job or self.job.id != body.get("id"):
            raise UserError("That check has finished.")
        self.job.answer(bool(body.get("yes")))
        return {"ok": True}

    def busy(self) -> bool:
        return bool(self.job and not self.job.done)

    def quit(self) -> dict:
        """Setup asks the page server to stop before it updates the app (never mid-job)."""
        if self.busy():
            return {"ok": False, "errors": ["A check is still running."]}
        self.stop_requested = True
        return {"ok": True}

    # --------------------------------------------------- updates
    def check_update(self, force: bool = False) -> dict:
        if self.update_cache and not force and time.time() - self.update_cache[0] < 3600:
            return self.update_cache[1]
        out: dict[str, Any] = {"current": __version__, "releases": RELEASES_URL}
        try:
            req = urllib.request.Request(LATEST_API, headers={
                "User-Agent": "WAC-Court-Booker", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode("utf-8"))
            latest = str(data.get("tag_name") or "").lstrip("vV")
            out.update(latest=latest, newer=parse_version(latest) > parse_version(__version__),
                       url=data.get("html_url") or RELEASES_URL, checked=True)
            zips = [a.get("browser_download_url") for a in data.get("assets") or []
                    if str(a.get("name", "")).endswith(".zip")]
            if zips:
                out["download"] = zips[0]
        except Exception as e:  # noqa: BLE001
            out.update(checked=False, newer=False,
                       error="Couldn't reach GitHub to check for a newer version.")
            _log(f"update check failed: {type(e).__name__}: {str(e)[:200]}")
        self.update_cache = (time.time(), out)
        return out

    def desktop_shortcut(self) -> dict:
        """(Re)create the desktop shortcut to this window, and remember the choice for setup."""
        target = web_exe()
        if not target.exists():
            raise UserError("Couldn't find the app's program. Run setup.cmd again.")
        link = desktop_shortcut_path()
        env = dict(os.environ, WACB_LNK=str(link), WACB_TARGET=str(target), WACB_DIR=str(paths.home()),
                   WACB_ARGS=f'--home "{paths.home()}"' if os.environ.get("WACB_HOME") else "")
        script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:WACB_LNK); "
                  "$s.TargetPath = $env:WACB_TARGET; $s.Arguments = $env:WACB_ARGS; "
                  "$s.WorkingDirectory = $env:WACB_DIR; "
                  "$s.Description = 'Book WAC Hartland tennis courts when each booking window opens'; $s.Save()")
        try:
            r = subprocess.run([scheduler.pwsh(), "-NoProfile", "-NonInteractive", "-Command", script],
                               env=env, capture_output=True, text=True, timeout=60,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
            raise UserError(f"Couldn't make the shortcut: {e}") from e
        if r.returncode or not link.exists():
            _log(f"desktop shortcut failed: {(r.stderr or r.stdout)[:300]}")
            raise UserError("Couldn't make the desktop shortcut. See the log for details.")
        try:  # setup reads this, so updates keep refreshing the shortcut
            (paths.home() / "desktop-shortcut.txt").write_text("Yes\n", encoding="utf-8")
        except OSError:
            pass
        return {"ok": True}

    def name_player(self, body: dict) -> dict:
        """The calendar: remember who a booker is (by the club's id for them), on this PC."""
        try:
            hid = int(body.get("id"))
        except (TypeError, ValueError):
            raise UserError("Pick a booked court first.")
        try:
            shown = runner.save_player(hid, str(body.get("club") or ""), str(body.get("name") or ""))
        except ValueError as e:
            raise UserError(str(e))
        return {"ok": True, "shown": shown}

    def open_log(self) -> dict:
        p = paths.log_file()
        if not p.exists():
            raise UserError("There's no log yet.")
        os.startfile(str(p))  # noqa: S606 - opens in Notepad
        return {"ok": True}


def web_exe() -> Path:
    """wac-booker-web.exe next to this Python (the venv's Scripts folder)."""
    return Path(sys.executable).parent / "wac-booker-web.exe"


def desktop_shortcut_path() -> Path:
    desk = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    try:  # the real Desktop folder, which OneDrive can move
        import ctypes
        from ctypes import wintypes
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
            desk = Path(buf.value)
    except (AttributeError, OSError):
        pass
    return desk / "WAC Court Booker.lnk"


class UserError(Exception):
    """A problem to show the person as it is."""


# ---------------------------------------------------------------- HTTP

def make_handler(app: WebApp, token: str, port_ref: list[int]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "WACCourtBooker"
        sys_version = ""

        def log_message(self, fmt, *args):  # no stderr under pythonw, and no request bodies in logs
            pass

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            return host in (f"127.0.0.1:{port_ref[0]}", f"localhost:{port_ref[0]}")

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data: dict) -> None:
            self._send(code, json.dumps(data, default=str).encode("utf-8"), "application/json; charset=utf-8")

        def _authed(self) -> bool:
            return secrets.compare_digest(self.headers.get("X-WACB-Token") or "", token)

        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                return self._send(403, b"Forbidden", "text/plain")
            path, _, query = self.path.partition("?")
            if path in ("/", "/index.html", "/calendar"):
                html = (CALENDAR_PAGE if path == "/calendar" else PAGE).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                                 "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(html)
                return
            if path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if not path.startswith("/api/") or not self._authed():
                return self._json(403 if path.startswith("/api/") else 404, {"ok": False, "errors": ["Not allowed."]})
            params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            routes = {"/api/state": app.state, "/api/results": app.results,
                      "/api/ping": lambda: {"ok": True, "version": __version__},
                      "/api/update": lambda: app.check_update(params.get("force") == "1"),
                      "/api/job": lambda: app.job_view(params.get("id", ""))}
            self._call(routes.get(path))

        def do_POST(self):  # noqa: N802
            if not self._host_ok() or not self._authed():
                return self._json(403, {"ok": False, "errors": ["Not allowed."]})
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._json(415, {"ok": False, "errors": ["Send JSON."]})
            n = int(self.headers.get("Content-Length") or 0)
            if n > 64 * 1024:
                return self._json(413, {"ok": False, "errors": ["Too big."]})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._json(400, {"ok": False, "errors": ["Bad request."]})
            path = self.path.partition("?")[0]
            routes = {
                "/api/booking": lambda: app.save_booking(body),
                "/api/booking/remove": lambda: app.remove_booking(body),
                "/api/booking/pause": lambda: app.pause_booking(body),
                "/api/booking/skip": lambda: app.skip_date(body),
                "/api/login": lambda: app.add_login(body),
                "/api/login/remove": lambda: app.remove_login(body),
                "/api/settings": lambda: app.settings(body),
                "/api/windows-password": lambda: app.windows_password_set(body),
                "/api/rebuild": app.rebuild,
                "/api/wake-timers": app.wake_timers,
                "/api/job": lambda: app.start_job(body),
                "/api/job/answer": lambda: app.job_answer(body),
                "/api/player": lambda: app.name_player(body),
                "/api/open-log": app.open_log,
                "/api/desktop-shortcut": app.desktop_shortcut,
                "/api/heartbeat": lambda: {"ok": True, "busy": app.busy()},
                "/api/quit": app.quit,
            }
            self._call(routes.get(path))

        def _call(self, fn):
            app.last_beat = time.monotonic()
            if fn is None:
                return self._json(404, {"ok": False, "errors": ["Not found."]})
            try:
                return self._json(200, fn())
            except UserError as e:
                return self._json(200, {"ok": False, "errors": [str(e)]})
            except Exception as e:  # noqa: BLE001
                _log(f"{self.command} {self.path.partition('?')[0]} failed:\n{traceback.format_exc()}")
                return self._json(500, {"ok": False, "errors": [
                    f"Something went wrong ({type(e).__name__}). The log has the details."]})
    return Handler


class Server:
    def __init__(self, port: int = 0):
        self.app = WebApp()
        self.token = secrets.token_urlsafe(24)
        self.port_ref = [0]
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(self.app, self.token, self.port_ref))
        self.httpd.daemon_threads = True
        self.port_ref[0] = self.httpd.server_address[1]
        self.started = time.monotonic()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port_ref[0]}/#t={self.token}"

    def idle_watch(self) -> None:
        while True:
            time.sleep(1)
            if self.app.stop_requested and not self.app.busy():
                break
            if self.app.busy():
                continue
            beat = self.app.last_beat
            if beat is None and time.monotonic() - self.started > FIRST_LOAD_WAIT:
                break
            if beat is not None and time.monotonic() - beat > IDLE_STOP:
                break
        self.httpd.shutdown()

    def serve(self, stop_when_idle: bool = True) -> None:
        if stop_when_idle:
            threading.Thread(target=self.idle_watch, daemon=True).start()
        try:
            self.httpd.serve_forever(poll_interval=0.5)
        finally:
            self.httpd.server_close()
            self.app.close()


# ---------------------------------------------------------------- opening the window

def _instance_file() -> Path:
    return paths.home() / "web.json"


def running_url() -> str | None:
    """The URL of a server this user already has open, if it still answers."""
    try:
        info = json.loads(_instance_file().read_text(encoding="utf-8"))
        req = urllib.request.Request(f"http://127.0.0.1:{int(info['port'])}/api/ping",
                                     headers={"X-WACB-Token": info["token"]})
        with urllib.request.urlopen(req, timeout=2) as r:
            if json.loads(r.read()).get("ok"):
                return f"http://127.0.0.1:{int(info['port'])}/#t={info['token']}"
    except Exception:  # noqa: BLE001
        pass
    return None


def edge_path() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.environ.get("LOCALAPPDATA")):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.exists():
                return str(p)
    return shutil.which("msedge")


def open_window(url: str) -> None:
    """The page in its own window (Edge app mode: no tabs or address bar), else the default browser."""
    edge = edge_path()
    if edge:
        try:
            subprocess.Popen([edge, f"--app={url}", "--window-size=1100,900"],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return
        except OSError:
            pass
    webbrowser.open(url)


def run(open_page: bool = True, port: int = 0, print_url: Callable[[str], None] | None = None) -> int:
    paths.ensure()
    notify.register_app_id()
    if open_page and port == 0:
        url = running_url()
        if url:
            open_window(url)
            return 0
    srv = Server(port)
    try:
        _instance_file().write_text(json.dumps({"port": srv.port_ref[0], "token": srv.token, "pid": os.getpid()}),
                                    encoding="utf-8")
    except OSError:
        pass
    _log(f"page server on 127.0.0.1:{srv.port_ref[0]}")
    if print_url:
        print_url(srv.url)
    if open_page:
        open_window(srv.url)
    try:
        srv.serve()
    finally:
        try:
            info = json.loads(_instance_file().read_text(encoding="utf-8"))
            if info.get("pid") == os.getpid():
                _instance_file().unlink()
        except (OSError, ValueError):
            pass
        _log("page server stopped")
    return 0


def gui_main() -> int:
    """Entry point of wac-booker-web.exe (no console window)."""
    import sys
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--home":
        os.environ["WACB_HOME"] = args[1]
    try:
        return run()
    except Exception:  # noqa: BLE001
        _log("couldn't start the page:\n" + traceback.format_exc())
        return 1
