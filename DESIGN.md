# wac-court-booker: design

A simple, shareable tool that books tennis courts at WAC Hartland the moment each slot becomes bookable (169 hours before it starts). It's a cut-down sibling of the author's own booking system: one booking per entry, no blockers, no back-to-back logic, set up and changed through a plain menu.

Status: design draft for review. Windows only for the first release.

## Who it's for

WAC Hartland members who aren't technical. If someone can download a zip, double-click a file and answer questions, they can use it. Admin rights on the PC are assumed.

## What it does and doesn't do

| In | Out (v1) |
|---|---|
| Book singles or doubles at WAC Hartland | Other clubs or WAC locations |
| 30, 60 or 90 minutes, with an optional "fall back to shorter" | Back-to-back slots (book a second entry instead) |
| A court preference list, any order or subset, optionally ending in `any` | Blockers |
| Weekly bookings and one-off dates, with skip dates | Cancelling real bookings (players use the club's site or phone) |
| Several club logins on one PC, chosen per booking | Email or phone push alerts |
| Runs in the background with a hidden browser, wakes the PC from sleep, can run signed out | Mac (later) |
| A full test: login, dry run, buddy list, clock check, and a real test booking that can be cancelled | |
| Windows toast notification and a log file for every run | |

## The user's journey

1. **Install.** Download the release zip from the private repo, unzip it, double-click `setup.cmd`. Setup:
   - installs Python if it's missing (Python Install Manager);
   - creates a private Python environment for the app and installs its packages and a bundled Chromium (Playwright);
   - adds a Start-menu shortcut called **WAC Court Booker**;
   - starts the setup wizard.
2. **Setup wizard** (first run only):
   1. Add a club login: a nickname plus the club username and password. The password goes straight into Windows Credential Manager and is never written to a file.
   2. Test that login.
   3. Read the login's buddy list, so partners can be picked by name later.
   4. Check the PC's clock against internet time and warn if it's more than 2 seconds off.
   5. Ask "Run even when you're signed out?" If yes, Windows asks for the Windows password and stores it with the scheduled tasks. If the PC doesn't allow that (common on work PCs), say so plainly and use "signed in, screen can be locked".
   6. Turn on wake timers so a sleeping PC wakes up for a booking.
   7. Offer the test booking (below).
   8. Add the first booking.
3. **Day to day:** open **WAC Court Booker** for the menu:

   ```
   WAC Court Booker
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
   ```

   Every change is saved to the config file, and the scheduled tasks are rebuilt to match straight away. The menu shows when each booking will next run.
4. **Booking morning:** nothing to do. The task runs in the background, books, and shows a toast: "Booked: Ct 5, Tue 12/15 6:00 PM, 90 min" or "Not booked: no court open at 6:00 PM. Book on the club site." Details go to the log.

## The config file

One commented file, `bookings.yaml`, in the user's app-data folder. The menu writes it. Confident users can edit it by hand, and the app checks it and explains any mistake in plain words.

```yaml
# WAC Court Booker. Edit with the menu, or by hand if you're comfortable.
# Times are club time (Central). Lengths: 30, 60 or 90 minutes.

logins:
  - nickname: me          # the password is in Windows Credential Manager, not here
    username: jsmith
  - nickname: partner
    username: asmith

bookings:
  - name: Tuesday doubles
    login: me
    play: doubles          # singles = 1 partner, doubles = 3
    partners: [Pat Lee, Sam Ortiz, Kim Park]   # names exactly as in your buddy list
    day: Tuesday           # weekly; or use  date: 2026-12-19  for a one-off
    time: "6:00 PM"
    length: 90
    shorter_ok: true       # if no court has 90, try 60, then 30 (same start time)
    courts: [5, 4, 3, any] # preference order; 'any' only at the end, optional
    skip: [2026-12-22, 2026-12-29]
    active: true
```

Rules the app enforces:
- `courts` holds court numbers and at most one `any`, which must come last.
- The number of partners matches `play`.
- No two bookings on the same login overlap. The club allows 2 reservations per login per day, and the app warns when a day would go over that.
- Each window must be in the future, and a one-off date has to be at least 169 hours away when it's added (24 hours for Prime Time singles), otherwise "book this on the club site now".

## Prime Time

The club's FAQ: Prime Time is Monday-Friday 9:00-10:30 AM and Monday-Thursday 5:00-8:00 PM, and in those hours singles can only be booked 24 hours ahead (doubles keep 1 week and 1 hour). The hours live in `clubtime.PRIME_TIME`.

- A booking is cut into **parts** (`Booking.parts`). Doubles, and singles outside Prime Time, are one part with W = start − 169 h. Singles entirely inside Prime Time are one part with W = start − 24 h.
- Singles that straddle a Prime Time edge become two parts: `main` (the regular hours, W = its start − 169 h) and `prime` (the Prime Time hours, W = its start − 24 h). Prime Time spans are 90 minutes or longer, so a booking of up to 90 minutes has at most one edge and at most two parts.
- Each part has its own scheduled task; the Prime Time one is named `<booking> (Prime Time part)` and runs `wac-booker run --booking <name> --part prime`.
- The `prime` run looks up the `main` run's result for that play date in results.jsonl. If the main part wasn't booked it records "skipped" and stops (no notification: half a booking isn't worth a second alert). Otherwise it puts the court the main part got first in the court list, then the rest, then any court.
- Both parts count toward the 2-reservations-a-day check.
- Straddling is allowed but discouraged: Prime Time is often held for lessons. The form explains this and offers nearby times that stay on one side (same length moved out, just the regular part, same length moved in, just the Prime Time part).
- The 43-45 s acceptance delay was measured on 169-hour windows. The engine presses from W + 1 s until accepted either way, so 24-hour windows need no different timing, but it hasn't been measured there.

## How a booking runs

Each booking gets its own Windows scheduled task under `\WAC Court Booker\` (two for a singles booking split at Prime Time), set to start 15 minutes before its window W (W = slot start − 169 hours, or 24 hours for Prime Time singles). The task runs `wac-booker run <booking>`. The steps:

1. **Before W (about W − 15 min to W − 1 min):**
   - read the password from Credential Manager;
   - start a hidden Chromium and sign in;
   - open the grid for the target day (using the time-of-day search when the slot isn't in the default view);
   - pick the first court on the list whose slot shows open, at the requested length;
   - click through to the participants page and tick the partners;
   - keep the page alive with a reload every 60 seconds, and stop reloading 45 seconds before W.
2. **From W + 1 second:** press **Continue to Cart** once a second until the site answers. From the author's real runs, the site turns everyone away until about W + 43–45 seconds. Pressing from W + 1 s costs nothing and wins the race.
3. **Read the answer:**
   - **Confirmed:** check the court is now taken on a fresh grid, then show the toast and log it.
   - **Turned away:** press again on the next tick.
   - **Court taken by someone else:** move to the next court on the list, then `any`.
   - **No answer:** never press again blind. Check the club's reservation list first, so it can't double-book.
   - With `shorter_ok`, if no court has the full length, retry with 60 and then 30 minutes at the same start time. All three lengths open at the same moment.
4. **Give up** after about 4 minutes past W: show a "not booked" toast with what to do by hand.

## Test everything (menu 8)

1. **Login test:** sign in with each login and confirm the welcome page.
2. **Clock check:** compare with internet time.
3. **Buddy list:** show the partners each login can pick.
4. **Dry run:** for a chosen booking, open next week's grid and show which preferred court is open right now. Stops before booking.
5. **Test booking (real, optional):**
   - Books a quiet slot now: 30 minutes, more than 24 hours away so cancelling is free, on the user's first-choice court if it's open at an unpopular time.
   - Then: "Booked Ct 5, Fri 12/18 1:30 PM. Check it on the club site or app. Do you see it?"
   - Then: "Cancel this test booking now?" Yes cancels it and checks it's gone. No keeps it.
   - This is the only place the app ever cancels anything.

## Windows details

| Need | How |
|---|---|
| Python | Python Install Manager if missing (`winget`, or the installer from python.org), then a private virtual environment for the app |
| Browser | See "Browser choice" below |
| Passwords | Windows Credential Manager (Python `keyring`) |
| Scheduling | Task Scheduler, one task per booking, `WakeToRun`, `StartWhenAvailable`, no second copy of a running task |
| Signed out | Task logon type "Password" (Windows collects and stores the Windows password), so the vault is reachable. Falls back to "Interactive only" if that's not allowed |
| Notifications | Windows toast (a small library such as `winotify`); skipped when nobody is signed in, the log always written |
| Wake from sleep | Wake timers turned on for the active power plan during setup |
| Club time | All times are Central; the PC's own time zone doesn't matter |

## Browser choice

A setting in the menu (**Logins → Browser**, and in `bookings.yaml` as `browser:`), with one value for the whole app:

| Setting | What runs | When to use it |
|---|---|---|
| `hidden` (default) | The app's own copy of Chromium, downloaded by setup (about 150 MB), with no window | Normal use. The same version on every PC, unaffected by browser updates or company browser policies |
| `edge` | The Microsoft Edge already on the PC | The app's own browser won't download or start (antivirus, company network) |
| `chrome` | Google Chrome, if it's installed | Same as Edge, for people who prefer Chrome |

- For `edge` and `chrome`, a second option `show_window: true|false` (default false). A visible window helps when someone wants to watch a test run or troubleshoot.
- Edge and Chrome run with **their own separate profile** in the app's folder, never the person's everyday profile. Their bookmarks, saved passwords and open tabs are never touched, and the booking can run while they're browsing. (Chrome and Edge also refuse automation on a person's everyday profile.)
- Firefox and Safari aren't supported.
- Setup tries `hidden` first. If it can't download or start, setup offers Edge and says why. "Test everything" runs with whichever browser is set, so a switch can be checked at once.

## Lessons carried over from the author's system

- A slot opens exactly 169 hours before it starts. The site starts accepting about 43–45 seconds after that.
- Stage everything early, and keep the staged page fresh until 45 seconds before W.
- Never re-submit over an unanswered booking: check the reservation list first.
- The grid's default view lists only the first few start times, so use its time-of-day search.
- The site sometimes glitches for one login (empty grid, a participants page that never loads). Retry the whole staging sequence rather than giving up.
- Files written from inside the Claude desktop app can land in the app's private AppData copy. Setup must write its config and tasks from a normal process, and the tool must never depend on files created that way.

## Risks and open questions

- **Hidden browser:** the author's system runs a visible browser. The site may behave differently with no window. Test this first; the Edge and Chrome settings (with an optional visible window) are the fallback.
- **Work PCs:** forced sign-outs, blocked stored passwords and sleep policies may stop runs. The app reports what the PC allows during setup.
- **PC off:** a PC that's shut down misses its run. The menu shows the next run time so people know when to leave it on.
- **Club terms of use:** the repo stays private and is shared only with members you invite.
- **Login form fields:** whether the club login is a member number, an email or a username. To confirm while building the login test.

## Repo and release

- Private GitHub repo `wac-court-booker` on the author's account. Friends are added as collaborators or get the release zip.
- Command: `wac-booker`. Start-menu entry: **WAC Court Booker**.
- First release: Windows only, versioned from 0.1.0.

## Build order

1. Login test and buddy list (read-only), headless check.
2. Config file, menu, validation.
3. Scheduler: create, update and remove tasks; wake timers; signed-out option.
4. Booking engine: staging, commit loop, court and length fallback, no-blind-resubmit check.
5. Test booking with confirm and cancel.
6. Setup script and Start-menu shortcut.
7. Toasts, log, "show recent results".
8. A friend-test on a second PC.
