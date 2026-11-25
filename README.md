# WAC Court Booker

Books tennis courts at WAC Hartland the moment each slot becomes bookable, 169 hours before it starts. You set up your bookings once in a simple menu, and Windows runs each one in the background at the right time.

Windows only for now. [DESIGN.md](DESIGN.md) explains the decisions behind it.

## Install

1. Download the release zip, unzip it anywhere (Downloads is fine), and double-click **setup.cmd**.
2. Setup installs what's missing (PowerShell 7, Python), sets up the app and its own browser, adds **WAC Court Booker** to the Start menu, then starts a short wizard:
   - add your club login (the password goes straight into Windows Credential Manager and is never written to a file);
   - test the login and read your buddy list, so partners can be picked by name;
   - check the PC clock against internet time;
   - choose whether bookings may run while you're signed out of Windows;
   - turn on wake timers so a sleeping PC wakes up for a booking;
   - offer a test booking you can cancel straight after;
   - add your first booking.

Run setup.cmd again any time to update the app. Your bookings and logins are kept.

## Day to day

Open **WAC Court Booker** from the Start menu:

```
1  Show my bookings and next run times
2  Add a booking
3  Edit a booking
4  Remove a booking
5  Skip a date
6  Pause / resume a booking
7  Logins: add, test, remove (also: browser, signed-out runs, wake timers)
8  Test everything (includes a test booking)
9  Show recent results
```

Every change is saved and the scheduled tasks are rebuilt straight away. Menu 1 shows when the PC must be on for each booking.

On a booking day there's nothing to do. A toast tells you how it went, for example "Booked: Ct 5, Tue 12/15 6:00 PM, 90 min", or "Not booked: no court open at 6:00 PM ... Book on the club site."

## What a booking can be

- Singles (1 partner) or doubles (3 partners), picked from your buddy list on the club site.
- 30, 60 or 90 minutes, optionally falling back to shorter at the same start time.
- A court preference list, such as `5, 4, 3, any`. `any` is optional and must come last.
- Weekly on a day, or a one-off date, with skip dates.
- Booked by any of the club logins you've added on this PC.

The club allows 2 reservations per login per day. The app warns when a day would go over that and refuses bookings that overlap on one login.

## The config file

The menu writes `%LOCALAPPDATA%\WAC Court Booker\bookings.yaml`. You can edit it by hand: it's commented, and the app explains any mistake in plain words. The scheduled tasks pick up hand edits at their next run, and opening the menu and choosing **7 → Rebuild scheduled tasks** updates the run times.

## How a booking runs

Each booking has its own task in Task Scheduler under `\WAC Court Booker\`. It starts 75 minutes before the window W (to cover a daylight-saving week), waits until W − 15 minutes, then:

1. signs in with a hidden browser, opens the court grid for the target day and picks the first court on your list that's open at your length;
2. clicks through to the participants page and ticks you and your partners, then keeps the page fresh until 45 seconds before W;
3. from W + 1 s presses **Continue to Cart** once a second. The club site turns everyone away until about W + 43–45 s; pressing early costs nothing;
4. if your court goes to someone else, moves down your list (and to shorter lengths if you allowed that);
5. if the site doesn't answer a press, it checks your reservation list before pressing again, so it can't double-book;
6. gives up about 4 minutes after W and tells you to book by hand.

The PC has to be on (asleep is fine with wake timers on). If it's off at W, you get a "Not booked" toast when it next starts.

## Browsers

Menu 7 → Browser, or `browser:` in bookings.yaml:

| Setting | What runs |
|---|---|
| `hidden` (default) | The app's own Chromium (downloaded by setup), no window |
| `edge` | Microsoft Edge on this PC, with its own separate profile |
| `chrome` | Google Chrome on this PC, with its own separate profile |

For Edge and Chrome, `show_window: true` shows the window, which helps when watching a test. Your everyday browser profile, bookmarks and saved passwords are never touched. If the app's own browser won't start on a booking morning, the run tries Edge.

## Where things are

`%LOCALAPPDATA%\WAC Court Booker\`:

| File | What |
|---|---|
| `bookings.yaml` | Your settings and bookings |
| `logs\wac-booker.log` | Everything each run did |
| `results.jsonl` | One line per run (menu 9 shows them) |
| `buddies.json` | Buddy names read from the club site |
| `venv\`, `browsers\` | The app and its browser |

Passwords live only in Windows Credential Manager, under "WAC Court Booker".

## Commands

The Start-menu entry opens the menu. The same program has commands for checking things (`wac-booker --help`):

```powershell
& "$env:LOCALAPPDATA\WAC Court Booker\venv\Scripts\wac-booker.exe" check
```

`check` lists bookings and next windows. `test-login`, `buddies`, `dry-run --booking NAME` and `clock` are read-only. `tasks` and `rebuild-tasks` show or rebuild the scheduled tasks. `selftest` checks the install. `run --booking NAME` is what the scheduled task runs.

## Development

```powershell
pwsh -NoProfile -File setup.ps1 -Dev -NoWizard     # editable install into %LOCALAPPDATA%\WAC Court Booker
& "$env:LOCALAPPDATA\WAC Court Booker\venv\Scripts\python.exe" -m pip install pytest
& "$env:LOCALAPPDATA\WAC Court Booker\venv\Scripts\python.exe" -m pytest
```

The tests run offline: the booking engine is tested against a fake club site and a fake clock (`tests/fakes.py`). Set `WACB_HOME` to use a scratch folder and `WACB_TASK_FOLDER` (for example `\WAC Court Booker\Test\`) to keep test tasks apart from real ones.

Release zip: `git archive --format=zip -o wac-court-booker-<version>.zip HEAD`.

Rules: never run a real booking or cancel without the account holder's OK for that run; never print or log passwords. Keep `pyproject.toml` and `wacbooker/__init__.py` on the same version and record changes in [CHANGELOG.md](CHANGELOG.md).
