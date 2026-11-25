"""Adds test bookings to bookings.yaml inside Windows Sandbox, keeping whatever is there.

- Login 'sandbox' with no saved password, and booking 'Sandbox check' on it: a one-off
  whose window opens in about 70-100 minutes, so a scheduled run started now counts as
  due and stops at "no password" before it ever opens the club site.
- With --dry-login NICK (hands-on mode, after the account holder signed in): booking
  'Sandbox dry run' on that login, same slot, PAUSED (its task is disabled), used only
  for the read-only dry run.

Run with the app's venv Python."""
import sys
from datetime import timedelta

from wacbooker import clubtime, config

now = clubtime.now_central()
t = now + clubtime.OPEN_LEAD + timedelta(minutes=70)
mins = -(-(t.hour * 60 + t.minute) // 30) * 30  # round up to :00 or :30
day = t.date()
if mins >= 24 * 60:
    day += timedelta(days=1)
    mins -= 24 * 60

dry_login = sys.argv[sys.argv.index("--dry-login") + 1] if "--dry-login" in sys.argv else None

doc, _ = config.load()
logins = [x for x in (doc.get("logins") or []) if x.get("nickname") != "sandbox"]
logins.append({"nickname": "sandbox", "username": "sandbox-test"})
doc["logins"] = logins

def slot() -> dict:  # fresh lists each time, so the YAML has no shared anchors
    return {"play": "singles", "partners": ["Test Partner"], "date": day.replace(),
            "time": clubtime.fmt_time(mins), "length": 30, "courts": [2, "any"]}


bookings = [x for x in (doc.get("bookings") or [])
            if x.get("name") not in ("Sandbox check", "Sandbox dry run")]
bookings.append({"name": "Sandbox check", "login": "sandbox", **slot()})
if dry_login:
    bookings.append({"name": "Sandbox dry run", "login": dry_login, **slot(), "active": False})
doc["bookings"] = bookings
config.save(doc)

_, cfg = config.load()
if not cfg.ok:
    print("bookings.yaml has problems: " + "; ".join(cfg.errors))
    sys.exit(1)
print(f"Sandbox check: {day.isoformat()} {clubtime.fmt_time(mins)}"
      + (f"; Sandbox dry run (paused) on login {dry_login}" if dry_login else ""))
