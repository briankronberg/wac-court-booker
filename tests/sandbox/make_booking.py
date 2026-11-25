"""Writes the sandbox test's own bookings.yaml in a SCRATCH app folder (WACB_HOME), never
the one the person uses, so their menu only shows logins and bookings they added.

- Login 'test-no-password' (no saved password), booking 'Sandbox check' on it: a one-off
  whose window opens in about 70-100 minutes, so a scheduled run started now counts as
  due and stops at "no password" before it ever opens the club site.
- With --dry-login NICK --dry-user USERNAME (after the person typed a login into the
  wizard): the same login in the scratch config (its password is found in Credential
  Manager by username), and booking 'Sandbox dry run' on it, PAUSED (its task is
  disabled), used only for the read-only dry run.

Run with the app's venv Python, with WACB_HOME set to the scratch folder."""
import os
import sys
from datetime import timedelta
from pathlib import Path

from wacbooker import clubtime, config, paths

home = os.environ.get("WACB_HOME")
real = Path(os.environ.get("LOCALAPPDATA", "")) / "WAC Court Booker"
if not home or Path(home).resolve() == real.resolve():
    sys.exit("make_booking.py writes only to a scratch folder: set WACB_HOME to one.")


def arg(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


dry_login, dry_user = arg("--dry-login"), arg("--dry-user")

now = clubtime.now_central()
t = now + clubtime.OPEN_LEAD + timedelta(minutes=70)
mins = -(-(t.hour * 60 + t.minute) // 30) * 30  # round up to :00 or :30
day = t.date()
if mins >= 24 * 60:
    day += timedelta(days=1)
    mins -= 24 * 60

paths.config_file().unlink(missing_ok=True)  # start from the template every time
doc, _ = config.load()


def slot() -> dict:  # fresh lists each time, so the YAML has no shared anchors
    return {"play": "singles", "partners": ["Test Partner"], "date": day.replace(),
            "time": clubtime.fmt_time(mins), "length": 30, "courts": [2, "any"]}


logins = [{"nickname": "test-no-password", "username": "test-no-password"}]
bookings = [{"name": "Sandbox check", "login": "test-no-password", **slot()}]
if dry_login and dry_user:
    logins.append({"nickname": dry_login, "username": dry_user})
    bookings.append({"name": "Sandbox dry run", "login": dry_login, **slot(), "active": False})
doc["logins"], doc["bookings"] = logins, bookings
config.save(doc)

_, cfg = config.load()
if not cfg.ok:
    print("test bookings.yaml has problems: " + "; ".join(cfg.errors))
    sys.exit(1)
print(f"Sandbox check: {day.isoformat()} {clubtime.fmt_time(mins)}"
      + (f"; Sandbox dry run (paused) on login {dry_login}" if dry_login and dry_user else ""))
