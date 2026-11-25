"""Writes a test bookings.yaml inside Windows Sandbox: one login with no saved password,
and one one-off booking whose window opens in about 70-100 minutes, so a scheduled run
started now counts as due and stops at "no password" before it ever opens the club site.
Run with the app's venv Python."""
from datetime import timedelta

from wacbooker import clubtime, paths

now = clubtime.now_central()
t = now + clubtime.OPEN_LEAD + timedelta(minutes=70)
mins = -(-(t.hour * 60 + t.minute) // 30) * 30  # round up to :00 or :30
day = t.date()
if mins >= 24 * 60:
    day += timedelta(days=1)
    mins -= 24 * 60

paths.ensure()
paths.config_file().write_text(f"""\
browser: hidden
show_window: false
run_signed_out: false

logins:
  - nickname: sandbox
    username: sandbox-test

bookings:
  - name: Sandbox check
    login: sandbox
    play: singles
    partners: [Test Partner]
    date: {day.isoformat()}
    time: "{clubtime.fmt_time(mins)}"
    length: 30
    courts: [2, any]
""", encoding="utf-8")
print(f"Sandbox check: {day.isoformat()} {clubtime.fmt_time(mins)}")
