"""wac-booker: the menu by default, plus commands for scheduled runs and checks."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from . import APP_NAME, __version__


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wac-booker", description=f"{APP_NAME} {__version__}")
    p.add_argument("--home", help="use this folder instead of %%LOCALAPPDATA%%\\WAC Court Booker")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("menu", help="the menu (default)")
    sub.add_parser("setup", help="first-run setup wizard")
    r = sub.add_parser("run", help="run one booking now (what the scheduled task does)")
    r.add_argument("--booking", required=True)
    sub.add_parser("check", help="check bookings.yaml and list next run times")
    t = sub.add_parser("test-login", help="sign in with a login (read-only)")
    t.add_argument("--login")
    bd = sub.add_parser("buddies", help="read and save a login's buddy list (read-only)")
    bd.add_argument("--login")
    d = sub.add_parser("dry-run", help="open the grid for a booking's next date (read-only)")
    d.add_argument("--booking", required=True)
    sub.add_parser("clock", help="compare the PC clock with internet time")
    sub.add_parser("tasks", help="show the scheduled tasks")
    sub.add_parser("rebuild-tasks", help="make the scheduled tasks match bookings.yaml")
    st = sub.add_parser("selftest", help="check this install from where it runs (no club sign-in)")
    st.add_argument("--out", help="also write the result as JSON here")
    st.add_argument("--browser", action="store_true", help="also start the browser and open the club sign-in page")
    sub.add_parser("version")
    return p


def _login(cfg, nickname):
    if nickname:
        lg = cfg.login(nickname)
        if not lg:
            raise SystemExit(f"No login called '{nickname}'.")
        return lg
    if not cfg.logins:
        raise SystemExit("No logins yet. Open the menu to add one.")
    return cfg.logins[0]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.home:
        os.environ["WACB_HOME"] = args.home
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    from . import clock, clubtime, config, menu, runner, scheduler

    cmd = args.cmd or "menu"
    if cmd == "menu":
        return menu.main_menu()
    if cmd == "setup":
        return menu.wizard()
    if cmd == "run":
        return runner.run_booking(args.booking)
    if cmd == "version":
        print(__version__)
        return 0
    if cmd == "clock":
        ok, msg = clock.report()
        print(msg)
        return 0 if ok else 1
    if cmd == "tasks":
        for t in scheduler.status():
            print(f"{t['name']}: {t['state']}, logon {t['logon']}, wake {t['wake']}, "
                  f"next {t['next'] or '-'}, last {t['last'] or '-'} (result {t['result']})")
        return 0

    doc, cfg = config.load()
    if cmd == "check":
        for e in cfg.errors:
            print(f"ERROR: {e}")
        for w in cfg.warnings:
            print(f"Note: {w}")
        now = clubtime.now_central()
        for b in cfg.bookings:
            nxt = b.next_runs(now, 1)
            when = (f"next {clubtime.fmt_when(nxt[0].start)}, window {clubtime.fmt_when(nxt[0].window)}"
                    if nxt else "no future dates")
            print(f"{b.name}: {b.describe()}; {when}{'' if b.active else ' (paused)'}")
        return 0 if cfg.ok else 2
    if not cfg.ok:
        print("bookings.yaml has a problem:\n  " + "\n  ".join(cfg.errors))
        return 2
    if cmd == "rebuild-tasks":
        r = scheduler.sync(cfg)
        print(f"registered {r.registered}, removed {r.removed}, logon {r.logon}. {r.note}")
        for e in r.errors:
            print(f"ERROR: {e}")
        return 0 if r.ok else 1
    if cmd == "test-login":
        return 0 if asyncio.run(runner.login_test(cfg, _login(cfg, args.login), print)) else 1
    if cmd == "buddies":
        names = asyncio.run(runner.buddy_list(cfg, _login(cfg, args.login), print))
        if names is None:
            return 1
        print(f"{len(names)} buddies saved.")
        return 0
    if cmd == "dry-run":
        b = cfg.booking(args.booking)
        if not b:
            raise SystemExit(f"No booking called '{args.booking}'.")
        return 0 if asyncio.run(runner.dry_run(cfg, b, print)) else 1
    if cmd == "selftest":
        return selftest(cfg, args.out, args.browser)
    return 2


def selftest(cfg, out: str | None, browser: bool) -> int:
    """What a scheduled run depends on, checked from wherever this runs."""
    from . import creds, notify, paths, scheduler
    rep: dict = {"version": __version__, "python": sys.executable, "home": str(paths.home()),
                 "home_exists": paths.home().exists(), "config_exists": paths.config_file().exists(),
                 "config_ok": cfg.ok, "errors": cfg.errors, "logins": [x.nickname for x in cfg.logins],
                 "passwords_reachable": {x.nickname: creds.has_password(x.username) for x in cfg.logins},
                 "browsers_dir": paths.browsers_dir().exists(), "wake_timers": scheduler.wake_timers_on()}
    try:
        paths.ensure()
        probe = paths.home() / ".selftest"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        rep["home_writable"] = True
    except OSError as e:
        rep["home_writable"] = str(e)
    notify.logger().info("selftest ran")
    rep["log_file"] = paths.log_file().exists()
    if browser:
        async def _b():
            from .site import ClubSite, LOGIN_URL
            s = ClubSite("", lambda: "", browser=cfg.browser, show_window=cfg.show_window)
            await s.start()
            try:
                await s.goto(LOGIN_URL, timeout=60)
                return bool(await s.js("!!document.querySelector('#ctl00_pageContentHolder_loginControl_UserName')"))
            finally:
                await s.close()
        try:
            rep["browser_ok"] = asyncio.run(_b())
        except Exception as e:  # noqa: BLE001
            rep["browser_ok"] = f"{type(e).__name__}: {str(e)[:200]}"
    text = json.dumps(rep, indent=1)
    print(text)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    return 0
