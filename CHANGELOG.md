# Changelog

## 0.1.0 (first release, Windows)

- Menu app and commented `bookings.yaml`: add, edit, remove, skip dates, pause and resume bookings; logins with passwords in Windows Credential Manager; browser choice; signed-out runs; wake timers.
- One Task Scheduler task per booking under `\WAC Court Booker\`: wakes the PC, starts late if it was off, never two copies at once. Weekly tasks start 75 minutes before the window so daylight-saving weeks are still early. Optional "Password" logon for signed-out runs, falling back to "signed in" when the PC refuses.
- Booking engine: stage before W, keep the page fresh until W − 45 s, press from W + 1 s once a second, court and length fallback, no re-press over an unanswered commit (reservation report, then grid), give up at about W + 4 min.
- Singles look in both "2 Singles" and "3.1 Primetime Singles" (evening singles are Primetime); doubles use "1 Doubles".
- Test everything: login, clock, buddy list, read-only dry run, and a real test booking (30 min, more than 24 h away) with confirm and cancel.
- Toasts and a log for every run, plus "missed" toasts when the PC was off at W.
- `setup.cmd` installs PowerShell 7 and Python if missing, the app, its Chromium and a Start-menu shortcut.
