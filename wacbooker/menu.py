"""The menu and the first-run setup wizard."""
from __future__ import annotations

import asyncio
import getpass
from datetime import date, datetime, timedelta

from . import (APP_NAME, __version__, clock, clubtime, config, creds, notify, paths, picker, results, runner,
               scheduler)
from .config import Booking, Login

MENU = f"""
{APP_NAME}
─────────────────
1  Show my bookings and next run times
2  Add a booking
3  Edit a booking
4  Remove a booking
5  Skip a date
6  Pause / resume a booking
7  Logins: add, test, remove
8  Test everything (includes a test booking)
9  Show recent results
0  Quit
"""


SIGNED_OUT_HELP = (
    "  The scheduled tasks can run two ways. One needs you to be signed in to this computer (the\n"
    "  screen can be locked). The other runs even when you're signed out, as long as the computer\n"
    "  is on. For that one, the scheduled task has to store your Windows user name and password\n"
    "  (Windows keeps them, not this app). If that's OK, choose Yes for \"Run while signed out\".\n"
    "  Some work PCs don't allow it; then bookings run while you're signed in.")


def _md(d) -> str:
    return f"{d:%a} {d.month}/{d.day}"


def booking_lines(b: Booking, now: datetime, task: dict | None) -> list[str]:
    """Menu 1's view of one booking: what it books, then when each upcoming run happens."""
    t = clubtime.fmt_time
    end = (b.time + b.length) % (24 * 60)
    a, z = t(b.time), t(end)
    span = f"{a[:-3]} to {z}" if a[-2:] == z[-2:] else f"{a} to {z}"
    when = f"Every {clubtime.DAYS[b.day]}" if b.day is not None else f"Once, {_md(b.date)}"
    lines = [f"{b.name}{'' if b.active else '  (PAUSED)'}",
             f"  {when}, {span}, {b.play} with {', '.join(b.partners)}"
             + (" (or shorter if no court has that long)" if b.shorter_ok else "")]
    named = [str(c) for c in b.courts if c != "any"]
    courts = ", then ".join(named + (["any"] if "any" in b.courts else [])) or "any"
    lines.append(f"  Courts: {courts}.  Login: {b.login}")
    nxt = b.next_runs(now - clubtime.LATE_OK, 2)
    if nxt:
        lines.append("  Next runs, every week until you remove or pause it (courts open 1 week + 1 hour ahead):"
                     if b.day is not None else "  Runs once (courts open 1 week + 1 hour ahead):")
        runs = [(f"{_md(o.window)} at {t(o.window.hour * 60 + o.window.minute)}", o) for o in nxt]
        width = max(len(r) for r, _ in runs)
        books = [f"books {_md(o.start)}, {t(o.start.hour * 60 + o.start.minute)}" for _, o in runs]
        bwidth = max(len(x) for x in books)
        for (run, o), bk in zip(runs, books):
            on = o.run_at
            on_txt = t(on.hour * 60 + on.minute) if on.date() == o.window.date() else clubtime.fmt_when(on)
            lines.append(f"    {run:<{width}}  {bk:<{bwidth}}  (PC on by {on_txt})")
    else:
        lines.append("  No future dates (a past one-off). Remove it when you like.")
    skips = [d for d in b.skip if d >= now.date()]
    if skips:
        lines.append(f"  Skipping: {', '.join(_md(d) for d in skips)}")
    if nxt and b.active and not task:
        lines.append("  Warning: no scheduled task. Choose 7, then 'Rebuild scheduled tasks'.")
    elif task:
        how = "runs even when you're signed out" if task["logon"] == "Password" \
            else "runs while you're signed in to Windows"
        lines.append(f"  Scheduled task: {task['state'].lower()} ({how})")
    return lines


def say(msg: str = "") -> None:
    print(msg)


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    try:
        ans = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        ans = ""
    return ans if ans else (default or "")


def yes(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    while True:
        try:
            ans = input(f"{prompt} ({d}): ").strip().lower()
        except EOFError:
            return default
        if not ans:
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False


def choose(title: str, options: list[str], allow_none: bool = True) -> int | None:
    if not options:
        return None
    say(title)
    for i, o in enumerate(options, 1):
        say(f"  {i}  {o}")
    while True:
        a = ask("Number" + (" (Enter to go back)" if allow_none else ""))
        if not a and allow_none:
            return None
        if a.isdigit() and 1 <= int(a) <= len(options):
            return int(a) - 1
        say("  Type one of the numbers above.")


class App:
    def __init__(self):
        self.windows_password: str | None = None
        self.doc = None
        self.cfg = None
        self.reload()

    # ------------------------------------------------------------ state
    def reload(self) -> None:
        self.doc, self.cfg = config.load()

    def explain_problems(self) -> bool:
        if self.cfg.errors:
            say("\nbookings.yaml has a problem, so nothing will book until it's fixed:")
            for e in self.cfg.errors:
                say(f"  - {e}")
            say(f"The file is {paths.config_file()}")
            return False
        for w in self.cfg.warnings:
            say(f"  Note: {w}")
        return True

    def commit(self, what: str) -> bool:
        """Check the edited document, save it and rebuild the scheduled tasks."""
        new = config.from_doc(self.doc)
        if not new.ok:
            say("\nThat change wasn't saved:")
            for e in new.errors:
                say(f"  - {e}")
            self.reload()
            return False
        config.save(self.doc)
        self.cfg = new
        for w in new.warnings:
            say(f"  Note: {w}")
        say(f"Saved: {what}.")
        self.rebuild_tasks()
        return True

    def rebuild_tasks(self) -> None:
        if self.doc is None:
            return
        pw = None
        if self.cfg.run_signed_out:
            if self.windows_password is None:
                say("Bookings are set to run while you're signed out. Windows needs your Windows "
                    "password to store with the tasks (it's not saved by this app).")
                self.windows_password = getpass.getpass("Windows password (Enter to skip): ") or ""
            pw = self.windows_password or None
        try:
            r = scheduler.sync(self.cfg, pw)
        except Exception as e:  # noqa: BLE001
            say(f"  Couldn't update Task Scheduler: {e}")
            return
        if r.note:
            say(f"  {r.note}")
            if r.logon == "InteractiveToken" and pw:
                self.windows_password = None
        for e in r.errors:
            say(f"  Task problem: {e}")
        n = len(r.registered)
        say(f"  Scheduled tasks updated ({n} booking task{'s' if n != 1 else ''}"
            f"{', ' + str(len(r.removed)) + ' removed' if r.removed else ''}).")

    def buddies(self, nickname: str) -> list[str]:
        return (runner.load_buddies().get(nickname) or {}).get("names") or []

    def offer_family(self, login: Login) -> list[str] | None:
        """Ask, then read the login's family members (a few seconds with a court in the cart)."""
        say("  Family members on your club account aren't on the buddy list. The club site shows them\n"
            "  only on the page where you choose who's playing, which opens once a court is in your\n"
            "  cart. To read them, the app puts a quiet 30-minute court in your cart for a few seconds,\n"
            "  reads the names, then presses Back, which empties the cart. Nothing is booked.")
        if not yes("  Read your family members now?", True):
            say("  Skipped. A test booking also reads them, or use menu 7 later.")
            return None
        fam = asyncio.run(runner.read_family(self.cfg, login, say))
        if fam is not None:
            say(f"  Family members: {', '.join(fam) if fam else 'none on this account'}.")
        return fam

    def read_family(self) -> None:
        login = self.pick_login("Whose family members?")
        if login:
            self.offer_family(login)

    # ------------------------------------------------------------ 1 show
    def show(self) -> None:
        if not self.explain_problems():
            return
        if not self.cfg.bookings:
            say("\nNo bookings yet. Choose 2 to add one.")
            return
        try:
            tasks = {t["name"]: t for t in scheduler.status()}
        except Exception:  # noqa: BLE001
            tasks = {}
        now = clubtime.now_central()
        for b in self.cfg.bookings:
            say("")
            for line in booking_lines(b, now, tasks.get(scheduler.task_name(b.name))):
                say(line)
        local = datetime.now().astimezone()
        if local.utcoffset() != now.utcoffset():
            say("\nNote: this PC isn't on Central time. Times above are club (Central) time; "
                "tasks start early enough to cover the difference.")

    # ------------------------------------------------------------ 2/3 add, edit
    def pick_booking(self, title: str) -> Booking | None:
        i = choose(title, [f"{b.name}  ({b.describe()})" for b in self.cfg.bookings])
        return None if i is None else self.cfg.bookings[i]

    def pick_partners(self, nickname: str, play: str, current: list[str]) -> list[str]:
        need = config.PARTNERS_FOR[play]
        if current and len(current) == need and yes(f"Keep partners {', '.join(current)}?"):
            return current
        login = self.cfg.login(nickname)
        buddies = self.buddies(nickname)
        if not buddies and login and yes("Read your buddy list from the club site first, to pick partners by name?"):
            buddies = asyncio.run(runner.buddy_list(self.cfg, login, say)) or []
        family = runner.load_family(nickname)
        if family is None and login and buddies:
            family = self.offer_family(login)
        family = family or []
        # Family members first, then buddies (a family member who's also a buddy shows once).
        names = family + [n for n in buddies if n.lower() not in {f.lower() for f in family}]
        labels = {f"{n}  (family)" if n in family else n: n for n in names}
        if not names:
            say("I don't have this login's buddy list yet (menu 7 can read it). Type names exactly as "
                "they appear in your buddy list on the club site.")
        out: list[str] = []
        if names and picker.available():
            while len(out) < need:
                label = f"Partner {len(out) + 1} of {need}" + (f" (picked: {', '.join(out)})" if out else "")
                got = picker.pick(label, [lab for lab, n in labels.items() if n not in out],
                                  "Not listed? Choose the last row and type their full name.")
                got = labels.get(got, got)
                if got is None:  # Esc: take back the last pick (or keep the old partners)
                    if out:
                        out.pop()
                    elif len(current) == need:
                        return current
                elif got == picker.OTHER:
                    typed = " ".join(ask("  Full name, exactly as the club site shows it").split())
                    if len(typed.split()) >= 2 and typed not in out:
                        out.append(typed)
                    elif typed:
                        say("  Please type a first and last name.")
                else:
                    out.append(got)
                    say(f"  Partner {len(out)}: {got}")
            return out
        while len(out) < need:
            q = ask(f"Partner {len(out) + 1} of {need} (type part of a name)")
            if not q:
                continue
            if not names:
                out.append(" ".join(q.split()))
                continue
            hits = [n for n in names if q.lower() in n.lower() and n not in out]
            if not hits:
                typed = " ".join(q.split())
                say("  Nobody on your family or buddy list matches that. If they're on your club account, "
                    "type their full name as the club site shows it.")
                if len(typed.split()) >= 2 and yes(f"  Use '{typed}' anyway?", False):
                    out.append(typed)
                continue
            if len(hits) == 1:
                out.append(hits[0])
                say(f"  {hits[0]}")
                continue
            i = choose("  Which one?", hits[:20])
            if i is not None:
                out.append(hits[i])
        return out

    def booking_form(self, old: Booking | None) -> Booking | None:
        cfg = self.cfg
        if not cfg.logins:
            say("Add a club login first (menu 7).")
            return None
        if len(cfg.logins) == 1:
            login = cfg.logins[0].nickname
        else:
            i = choose("Which login books it?", [f"{x.nickname} ({x.username})" for x in cfg.logins], False)
            login = cfg.logins[i].nickname
        play = ""
        while play not in ("singles", "doubles"):
            a = ask("Singles or doubles", old.play if old else "singles").lower()
            play = {"s": "singles", "d": "doubles"}.get(a, a)
        partners = self.pick_partners(login, play, old.partners if old and old.play == play else [])
        weekly = yes("Every week?", old.day is not None if old else True)
        day = one_off = None
        while weekly and day is None:
            try:
                day = clubtime.parse_day(ask("Day of the week", clubtime.DAYS[old.day] if old and old.day is not None else "Tuesday"))
            except ValueError as e:
                say(f"  {e}")
        while not weekly and one_off is None:
            try:
                one_off = datetime.strptime(ask("Date (YYYY-MM-DD)", old.date.isoformat() if old and old.date else ""),
                                            "%Y-%m-%d").date()
            except ValueError:
                say("  Type the date like 2026-12-19.")
        minutes = None
        while minutes is None:
            try:
                minutes = clubtime.parse_time(ask("Start time", clubtime.fmt_time(old.time) if old else "6:00 PM"))
                if minutes % 30:
                    say("  Courts start on the hour or half hour.")
                    minutes = None
            except ValueError as e:
                say(f"  {e}")
        length = 0
        while length not in config.LENGTHS:
            try:
                length = int(ask("Length in minutes (30, 60 or 90)", str(old.length) if old else "90"))
            except ValueError:
                pass
        shorter_ok = length > 30 and yes("If no court has that length, try shorter (same start)?",
                                         old.shorter_ok if old else True)
        courts = None
        while courts is None:
            raw = ask("Courts in order of preference, e.g. 5 4 3 any", " ".join(map(str, old.courts)) if old else "any")
            errs: list[str] = []
            b = config.parse_booking({"name": "x", "login": "x", "play": "singles", "partners": ["x"], "day": "Monday",
                                      "time": "6:00 PM", "length": 60, "courts": raw.replace(",", " ").split()}, 1, errs)
            if errs:
                say("  " + " ".join(e.replace("Booking 'x': ", "") for e in errs))
            else:
                courts = b.courts
        # The name is made from the booking (it labels the task, results and menus). An
        # edited booking keeps a name typed by hand; a made-up name follows the changes.
        others = [b.name for b in cfg.bookings if not old or b.name != old.name]
        name = config.auto_name(play, partners, day, one_off, minutes, others)
        if old and old.name != config.auto_name(old.play, old.partners, old.day, old.date, old.time, others):
            name = old.name
        new = Booking(name=name, login=login, play=play, partners=partners, time=minutes, length=length,
                      courts=courts, day=day, date=one_off, shorter_ok=shorter_ok,
                      skip=list(old.skip) if old else [], active=old.active if old else True)
        if new.date:
            w = clubtime.window_open(clubtime.slot_start(new.date, new.time))
            if w < clubtime.now_central() + timedelta(minutes=20):
                say(f"  That slot's booking window opened {clubtime.fmt_when(w)}. "
                    f"Book this one on the club site now.")
                return None
        return new

    def add(self) -> None:
        b = self.booking_form(None)
        if b:
            config.put_booking(self.doc, b)
            self.commit(f"booking '{b.name}'")

    def edit(self) -> None:
        old = self.pick_booking("Edit which booking?")
        if not old:
            return
        b = self.booking_form(old)
        if b:
            config.put_booking(self.doc, b, replace=old.name)
            self.commit(f"booking '{b.name}'")

    # ------------------------------------------------------------ 4/5/6
    def remove(self) -> None:
        b = self.pick_booking("Remove which booking?")
        if b and yes(f"Remove '{b.name}' and its scheduled task?", False):
            config.remove_booking(self.doc, b.name)
            self.commit(f"removed '{b.name}'")

    def skip(self) -> None:
        b = self.pick_booking("Skip a date for which booking?")
        if not b:
            return
        if b.date:
            say("That's a one-off booking. Remove it instead (4).")
            return
        now = clubtime.now_central()
        occ = b.occurrences(now, 8)
        opts = [f"{o.day:%a %m/%d/%Y}{'  (skipped; choose to un-skip)' if o.day in b.skip else ''}" for o in occ]
        i = choose("Which date?", opts)
        if i is None:
            return
        d = occ[i].day
        b.skip = [x for x in config.prune_skips(b, now.date()) if x != d] if d in b.skip else \
            config.prune_skips(b, now.date()) + [d]
        config.put_booking(self.doc, b, replace=b.name)
        self.commit(f"'{b.name}' {'skips' if d in b.skip else 'no longer skips'} {d:%a %m/%d}")

    def pause(self) -> None:
        b = self.pick_booking("Pause or resume which booking?")
        if not b:
            return
        b.active = not b.active
        config.put_booking(self.doc, b, replace=b.name)
        self.commit(f"'{b.name}' {'resumed' if b.active else 'paused'}")

    # ------------------------------------------------------------ 7 logins
    def logins(self) -> None:
        while True:
            opts = ["Add a login", "Test a login", "Read a login's buddy list", "Read a login's family members",
                    "Remove a login",
                    f"Browser (now: {self.cfg.browser}{', window shown' if self.cfg.show_window else ''})",
                    f"Run while signed out (now: {'yes' if self.cfg.run_signed_out else 'no'})",
                    "Rebuild scheduled tasks", f"Wake timers (now: {self._wake_text()})"]
            i = choose("\nLogins and settings", opts)
            if i is None:
                return
            [self.add_login, self.test_login, self.read_buddies, self.read_family, self.remove_login,
             self.set_browser, self.set_signed_out, self.rebuild_tasks, self.wake][i]()

    def _wake_text(self) -> str:
        on = scheduler.wake_timers_on()
        return "on" if on else ("off" if on is False else "unknown")

    def pick_login(self, title: str) -> Login | None:
        if not self.cfg.logins:
            say("No logins yet.")
            return None
        if len(self.cfg.logins) == 1:
            return self.cfg.logins[0]
        i = choose(title, [f"{x.nickname} ({x.username})" for x in self.cfg.logins])
        return None if i is None else self.cfg.logins[i]

    def add_login(self) -> Login | None:
        nick = ask("Nickname for this login (e.g. me)", "me" if not self.cfg.logins else "")
        if not nick:
            return None
        user = ask("Club username (what you type on the club's sign-in page)")
        if not user:
            return None
        pw = getpass.getpass("Club password (typing is hidden): ")
        if not pw:
            say("No password typed; login not added.")
            return None
        creds.set_password(user, pw)
        del pw
        login = Login(nick, user)
        config.put_login(self.doc, login)
        if not self.commit(f"login '{nick}' (password saved in Windows Credential Manager)"):
            return None
        say("Testing it ...")
        if asyncio.run(runner.login_test(self.cfg, login, say)):
            say("Reading the buddy list ...")
            names = asyncio.run(runner.buddy_list(self.cfg, login, say))
            if names is not None:
                say(f"  {len(names)} buddies saved for picking partners.")
            self.offer_family(login)
        else:
            say("Check the username and password, then add the login again with the same nickname.")
        return login

    def test_login(self) -> None:
        login = self.pick_login("Test which login?")
        if login:
            asyncio.run(runner.login_test(self.cfg, login, say))

    def read_buddies(self) -> None:
        login = self.pick_login("Whose buddy list?")
        if not login:
            return
        names = asyncio.run(runner.buddy_list(self.cfg, login, say))
        if names is not None:
            say(f"  {len(names)} buddies: " + ", ".join(names))

    def remove_login(self) -> None:
        login = self.pick_login("Remove which login?")
        if not login:
            return
        used = [b.name for b in self.cfg.bookings if b.login == login.nickname]
        if used:
            say(f"  Bookings use it: {', '.join(used)}. Remove or change those first.")
            return
        if yes(f"Remove login '{login.nickname}' and its saved password?", False):
            config.remove_login(self.doc, login.nickname)
            if self.commit(f"removed login '{login.nickname}'"):
                creds.delete_password(login.username)

    def set_browser(self) -> None:
        i = choose("Which browser should bookings use?",
                   ["hidden: the app's own Chromium, no window (normal)",
                    "edge: Microsoft Edge on this PC, separate profile",
                    "chrome: Google Chrome on this PC, separate profile"])
        if i is None:
            return
        br = config.BROWSERS[i]
        config.set_setting(self.doc, "browser", br)
        config.set_setting(self.doc, "show_window", br != "hidden" and yes("Show the browser window?", False))
        self.commit(f"browser set to {br}")

    def set_signed_out(self) -> None:
        say(SIGNED_OUT_HELP)
        on = yes("Run while signed out?", self.cfg.run_signed_out)
        config.set_setting(self.doc, "run_signed_out", on)
        self.windows_password = None
        self.commit(f"run while signed out: {'yes' if on else 'no'}")

    def wake(self) -> None:
        if scheduler.wake_timers_on():
            say("  Wake timers are already on, so a sleeping PC wakes up for a booking.")
            return
        if yes("Turn on wake timers so a sleeping PC wakes up for a booking?"):
            ok, msg = scheduler.enable_wake_timers()
            say(f"  {'Done: ' if ok else 'Not changed: '}{msg}")

    # ------------------------------------------------------------ 8 test everything
    def test_everything(self) -> None:
        if not self.cfg.logins:
            say("Add a login first (7).")
            return
        say("\n1. Login test")
        for lg in self.cfg.logins:
            say(f" {lg.nickname}:")
            asyncio.run(runner.login_test(self.cfg, lg, say))
        say("\n2. Clock check")
        say("  " + clock.report()[1])
        say("\n3. Buddy lists")
        for lg in self.cfg.logins:
            names = asyncio.run(runner.buddy_list(self.cfg, lg, say))
            if names is not None:
                say(f"  {lg.nickname}: {len(names)} buddies" + (f" (e.g. {', '.join(names[:3])})" if names else ""))
        say("\n4. Dry run")
        b = self.pick_booking("Dry run which booking?") if self.cfg.bookings else None
        if b:
            asyncio.run(runner.dry_run(self.cfg, b, say))
        else:
            say("  Skipped (no booking chosen).")
        say("\n5. Test booking (real)")
        self.offer_test_booking()

    def offer_test_booking(self) -> None:
        say("  This books a real court now: 30 minutes, more than 24 hours away (so cancelling is free), "
            "at an early, quiet time. You can cancel it straight after.")
        if not yes("  Make a test booking?", False):
            say("  Skipped.")
            return
        login = self.pick_login("Which login?")
        if not login:
            return
        b = next((x for x in self.cfg.bookings if x.login == login.nickname and x.play == "singles"), None)
        partners = b.partners if b else self.pick_partners(login.nickname, "singles", [])
        courts = b.courts if b else ["any"]
        r = asyncio.run(runner.test_booking(self.cfg, login, "singles", partners, courts, say,
                                            lambda q: yes(q, True)))
        say(f"  Test booking: {r}.")

    # ------------------------------------------------------------ 9 results
    def show_results(self) -> None:
        rows = results.recent(15)
        if not rows:
            say("\nNo runs yet.")
        for r in rows:
            say(f"{r['at'][:16].replace('T', ' ')}  {r['booking']}: {r['message']}")
        say(f"\nFull log: {paths.log_file()}")

    # ------------------------------------------------------------ loops
    def loop(self) -> None:
        say(f"{APP_NAME} {__version__}")
        self.explain_problems()
        actions = {"1": self.show, "2": self.add, "3": self.edit, "4": self.remove, "5": self.skip,
                   "6": self.pause, "7": self.logins, "8": self.test_everything, "9": self.show_results}
        while True:
            say(MENU)
            c = ask("Choose")
            if c == "0" or c.lower() in ("q", "quit", "exit"):
                return
            fn = actions.get(c)
            if fn is None:
                continue
            self.reload()
            if c != "1" and c != "9" and c != "7" and not self.cfg.ok:
                self.explain_problems()
                continue
            try:
                fn()
            except KeyboardInterrupt:
                say("\n(cancelled)")

    def wizard(self) -> None:
        say(f"\nWelcome to {APP_NAME}. A few questions to get going.\n")
        if self.cfg.browser == "hidden" and not any(paths.browsers_dir().glob("chromium*")):
            say("The app's own browser isn't installed (setup couldn't download it), so bookings will "
                "use Microsoft Edge with a separate profile. You can change this in menu 7.\n")
            config.set_setting(self.doc, "browser", "edge")
            self.commit("browser set to edge")
        say("Step 1: add your club login.")
        login = self.cfg.logins[0] if self.cfg.logins else None
        if login and creds.has_password(login.username):
            say(f"  You already have login '{login.nickname}'.")
        else:
            login = self.add_login()
        say("\nStep 2: check the PC clock.")
        say("  " + clock.report()[1])
        say("\nStep 3: run while signed out?")
        say(SIGNED_OUT_HELP)
        on = yes("  Run while signed out?", False)
        config.set_setting(self.doc, "run_signed_out", on)
        self.commit(f"run while signed out: {'yes' if on else 'no'}")
        say("\nStep 4: wake timers.")
        self.wake()
        if login:
            say("\nStep 5: test booking.")
            self.offer_test_booking()
        say("\nStep 6: add your first booking.")
        if yes("  Add one now?"):
            self.add()
        say(f"\nAll set. Open '{APP_NAME}' from the Start menu any time to change things.")


def main_menu() -> int:
    paths.ensure()
    notify.register_app_id()
    App().loop()
    return 0


def wizard() -> int:
    paths.ensure()
    notify.register_app_id()
    app = App()
    app.wizard()
    if yes("\nOpen the menu now?"):
        app.loop()
    return 0
