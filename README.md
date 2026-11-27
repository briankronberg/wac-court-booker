# WAC Court Booker

This project is for WAC Lake Country people that would like a better way to automate the booking of tennis courts week after week at the same time. You set up your bookings once in a simple menu, and Windows runs each one in the background at the right time.  For example, I use it to book courts every Saturday morning so I don't need to wake up at 5AM just to book courts online.  The install is easy and the simple interface makes it easy to set up automatic bookings for yourself.  The same rules of the WAC still apply.  
   - You can only book 1 week and 1 hour ahead.
   - You can only book 2 courts on the same day.
   - You must include someone from your family or buddy list in a booking and they are also limited to just 2 court bookings a day.

Windows only for now as I do not have a Mac to test the builds on. [DESIGN.md](DESIGN.md) explains the decisions I made while building the process with AI.  AI is not required to use this project, it only uses PowerShell and Python which are free and installed for you during setup.

## Install

1. On GitHub, open **Releases**, download `wac-court-booker-<version>.zip`, unzip it anywhere (Downloads is fine), and double-click **setup.cmd**. If Windows says "Windows protected your PC", choose **More info → Run anyway** (it does that for any file from the internet).
2. Setup installs what's missing (PowerShell 7, Python), sets up the app and its own browser, adds **WAC Court Booker** to the Start menu and your desktop. Then the app opens in its own window and walks you through four steps:
   - sign in to the club (the password goes straight into Windows Credential Manager and is never written to a file); the app tests it and reads your buddy list;
   - get the PC ready: wake timers, a clock check, and whether bookings may run while you're signed out of Windows;
   - find your family members (optional);
   - book your first court.

Run setup.cmd again any time to update the app. Your bookings and logins are kept.

## Day to day

Open **WAC Court Booker** from the Start menu or your desktop. It opens in its own window with four pages:

- **My bookings:** each booking in plain words ("Every Tuesday, 6:00 to 7:30 PM, singles with Pat"), the next dates it books, when the app books them and when the PC must be on. Press **Book a court** to add one. Each booking has **Change**, **Skip a week**, **Pause** and **Remove**.
- **My reservations:** what's actually booked on the club site, read live: the next 30 days unless you pick other dates (next 7 or 90 days, this month, the past 30 days, or any range). Tick **Include family members** to see theirs too, marked "Family". Each reservation has **Cancel**: the app asks first, warns when it's less than 24 hours away (the club charges a late-cancel fee then), cancels it on the club site and tells you when it's done.
- **What happened:** every booking run, newest first.
- **Settings:** your club login (test it, re-read your buddy list or family), wake timers, running while signed out, the clock check, a real test booking you can cancel straight after, which browser the app uses, and a button that puts the shortcut on your desktop (or makes it again).

Every change is saved and the scheduled tasks are rebuilt straight away. You can close the window any time: bookings run on their own.

**Updates:** the app checks GitHub for a newer version each time it opens (or press **Check for updates** at the top). When there is one, it shows the download link and the steps.

On a booking day there's nothing to do. A notification tells you how it went, for example "Booked: Ct 5, Tue 12/15 6:00 PM, 90 min", or "Not booked: no court open at 6:00 PM ... Book on the club site."

## What a booking can be

- Singles (1 partner), doubles (3 partners) or a **ball machine** (just you), with partners picked from your buddy list on the club site: click their names (type a few letters to narrow the list). Family members on your club account come first, marked "Family". The club site shows them only once a court is in your cart, so the app offers to find them: it puts a quiet court in the cart for a few seconds, then presses Back, and nothing is booked. Each test or real booking also updates the list. Anyone else: choose "Someone else" and type their full name.
- 30, 60 or 90 minutes, optionally falling back to shorter at the same start time.
- Courts in order of preference (press them in order), optionally followed by any other court.
- Weekly on a day, or a one-off date, with skip dates.
  - **See Available Courts** (next to **Every week** and **Just once**) opens a window with every court for the day you chose (for a weekly booking, its next date; or today), half hour by half hour: open, booked (with who booked it), or blocked for a lesson or event, with Prime Time marked, your time outlined, and when each ball machine is free. Press an open court to put that date, time and court into your booking. It has a date box, day before and day after, and **Refresh**.
    The club gives only the first letters of a booker's last name. You, your buddies and your family show with the full last name (first initial and last name); anyone else shows as the club gives it, such as "A. Smi…". Press a booked court to say who it is: type their first and last name once and the calendar shows it on all their bookings from then on. The name has to fit what the club shows (for "Smi, A.", a first name starting with A and a last name starting with Smi), which catches typos. Leave it empty to forget a name.
  - **Validate booking** (next to **Save booking**) checks the club's court sheet and says which courts are free at your time right now, and whether your first choice is one of them. For a weekly booking it checks the next date it will book.
  - Both only read the court sheet; nothing is booked.
  - **Save booking** schedules the booking: the app books it the moment the club opens that time (a week ahead, or a day ahead in Prime Time). For a one-off date the club already takes bookings for, it's greyed out.
  - **Book Now** books it on the club site straight away, after you confirm. It works once the club takes bookings for that time and is greyed out until then, or while something is still to choose; the note above the buttons says when it opens. For a weekly booking it books the soonest such day, if that's already open.
- Booked by any of the club logins you've added on this PC.

### Ball machines

The club has two ball machines: the **Genie** (you control it from its phone app, so no walking to the far side of the court) and the **regular** one. They go only on courts 2, 3, 8, 9 and 10. On the club site you find a free machine, pick a time, then pick a court. In the app you choose **Ball machine**, then **Genie**, **Regular** or **Either one** (Genie first), and the time and courts as usual. When the booking opens, the app finds a court that takes a machine at a time the machine is free, and books both together. **See Available Courts** shows when each machine is free, next to the courts, and **Validate booking** checks your machine and courts. Like singles, a ball machine in Prime Time is booked 24 hours ahead.

The club allows 2 reservations per login per day. The app warns when a day would go over that and refuses bookings that overlap on one login. It also checks what you already have on the club site: **Validate booking** says when that day is full or the time clashes with one of your reservations, and a booking that opens on such a day stops and tells you, instead of trying and getting turned away.

### Prime Time

Prime Time is Monday-Friday 9:00-10:30 AM and Monday-Thursday 5:00-8:00 PM. In those hours the club opens **singles** courts and **ball machines** only 24 hours ahead; doubles still book 1 week and 1 hour ahead (see the [WAC Tennis FAQ](https://www.thewac.com/sports/tennis/tennis-faq/)). The app follows that:

- A singles or ball machine booking entirely in Prime Time is booked 24 hours ahead.
- A singles or ball machine booking that runs into or out of Prime Time (for example Monday 8:00-9:30 AM) is booked in two parts: the regular hours a week ahead (8:00-9:00), then the Prime Time part 24 hours ahead (9:00-9:30), on the same court if it's free. If the first part isn't booked, the second isn't tried. Each part counts toward the 2 reservations a day. Prime Time is often taken by lessons, so the second part may not get a court. The booking form warns about this and offers nearby times that stay on one side.

## The config file

The menu writes `%LOCALAPPDATA%\WAC Court Booker\bookings.yaml`. You can edit it by hand: it's commented, and the app explains any mistake in plain words. The scheduled tasks pick up hand edits at their next run, and **Settings → Rebuild scheduled tasks** updates the run times.

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

**Settings → Browser the app uses**, or `browser:` in bookings.yaml:

| Setting | What runs |
|---|---|
| `hidden` (default) | The app's own Chromium (downloaded by setup), no window |
| `edge` | Microsoft Edge on this PC, with its own separate profile |
| `chrome` | Google Chrome on this PC, with its own separate profile |

For Edge and Chrome, `show_window: true` shows the window, which is handy for watching a booking run. Your everyday browser profile, bookmarks and saved passwords are never touched. If the app's own browser won't start on a booking morning, the run tries Edge.

## Where things are

`%LOCALAPPDATA%\WAC Court Booker\`:

| File | What |
|---|---|
| `bookings.yaml` | Your settings and bookings |
| `logs\wac-booker.log` | Everything each run did |
| `results.jsonl` | One line per run ("What happened" shows them) |
| `buddies.json` | Buddy names read from the club site |
| `players.json` | Names you gave to bookers in **See Available Courts** |
| `venv\`, `browsers\` | The app and its browser |

Passwords live only in Windows Credential Manager, under "WAC Court Booker".

## Commands

The Start-menu entry opens the app's window. `wac-booker menu` is the older text menu, for anyone who prefers a console. The same program has commands for checking things (`wac-booker --help`):

```powershell
& "$env:LOCALAPPDATA\WAC Court Booker\venv\Scripts\wac-booker.exe" check
```

`check` lists bookings and next windows. `test-login`, `buddies`, `dry-run --booking NAME` and `clock` are read-only. `tasks` and `rebuild-tasks` show or rebuild the scheduled tasks. `selftest` checks the install. `run --booking NAME` is what the scheduled task runs.
