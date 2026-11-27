# wac-court-booker: design

A simple, shareable tool that books tennis courts at WAC Hartland the moment each slot becomes bookable (169 hours before it starts). It started as a cut-down sibling of the author's own booking system; since 0.6.0 it also has that system's coordinated logins, back-to-back sessions, guard slots (blockers) and email summaries, all set up through the same page.

Status: design draft for review. Windows only for the first release.

## Who it's for

WAC Hartland members who aren't technical. If someone can download a zip, double-click a file and answer questions, they can use it. Admin rights on the PC are assumed.

## What it does and doesn't do

| In | Out (v1) |
|---|---|
| Book singles or doubles at WAC Hartland | Other clubs or WAC locations |
| 30, 60 or 90 minutes, with an optional "fall back to shorter", and an optional second session right after | |
| A court preference list, any order or subset, optionally ending in `any`, and an optional guard slot before the start | |
| Weekly bookings and one-off dates, with skip dates | Cancelling real bookings (players use the club's site or phone) |
| Several club logins on one PC, chosen per booking, and logins booking together | Phone push alerts |
| Runs in the background with a hidden browser, wakes the PC from sleep, can run signed out | Mac (later) |
| A full test: login, dry run, buddy list, clock check, and a real test booking that can be cancelled | |
| Windows toast notification and a log file for every run, and an optional email | |

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
- **Book Now** (`book-now` job, `runner.book_now`) runs the same engine with W = now for a one-off date whose every part's window is open (`runner.book_now_block`); a weekly booking sends its soonest open date. A split booking books its regular part, then the Prime Time part on the same court first. The page greys the button out with the same rule (club time via `America/Chicago`), and Save booking refuses one-off dates opening within 20 minutes.
- After signing in, a run reads the login's own reservations for the day (`engine.day_check`). At the limit, or with one overlapping the booking's time, it stops as not booked before staging: the club refuses such a commit without a clear answer (the press times out), which would otherwise end as a vague failure. If the report can't be read, the run goes ahead. Validate booking and the test booking use the same check (`engine.day_conflict`).
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

## Court availability (one-off dates)

- The club's court sheet is drawn in the browser from its JSON web service, `Library/OlsService.asmx` (POST, JSON body, the signed-in session's cookies). `ClubSite.api()` calls it with `fetch` from the signed-in page. The calls the app uses (all read-only):
  - `GetSchedulerResourceAvailability {siteId, resourceIds, selectedDate}`: per court, 1440 `{TimeId, IsAvailable}` minutes plus `BookingDetails` (member reservations, each with `HostName`, the club's short form: up to 3 letters of the last name and the first initial). The calendar shows it as an initial and last name, with the full last name when exactly one person in the buddy list, family or the login itself fits it (`runner.short_name`). Pressing a booked cell names that booker: `POST /api/player {id, club, name}` keeps `{HostId: full name}` in `players.json` after checking the name fits the short form (`runner.name_fits`); a saved name wins over the buddy-list match. Names go only to the calendar window and that file: never to the log, results or notifications. The club's member search (`SearchMembers`) would give full names but returns other members' contact details, usernames and PINs with them, so the app never calls it.
  - `GetServiceAvailability {serviceUniqueId, selectedDate}`: when a service is offered (doubles all day; singles and ball machines split at Prime Time into separate services).
  - `GetSiteAvailability {siteId, selectedDate}`: the club's hours.
  - `GetSchedulerProviderAvailability {siteId, providerIds, selectedDate}`: ball machines, which are "providers" (regular 121, Genie 442).
- A minute is free when the court, the service and the club all say so (the page ANDs them the same way; today it also blocks times already past). A half hour is **booked** if a member reservation overlaps it, otherwise **blocked** (lesson, league, event or closed).
- **Validate booking** (next to Save) checks the form's date (a weekly booking: its next date more than a week away), start and lengths; **See Available Courts** opens `/calendar` for the form's date or today. Pressing an open cell there posts `{type: "wacb-pick", date, time, court}` to the main window, which fills the form. A second open of the calendar only changes its hash, so the page reloads on `hashchange`.
- Both use a warm session (`live.py`): one signed-in browser on its own event-loop thread, kept 10 minutes after its last use, closed when the page server stops. The first look takes a few seconds (sign-in), later ones about one. Scheduled bookings never use it.
- The booking engine still stages courts through the court list (it needs the page's slot links), with every court selected first: the list opens with only courts 2-6 selected.

## Ball machines

- Ball machines are "providers" on their own services: `3.01 Genie Ball Machine` (provider 442, "Genie M.") and `3 Ball Machine` (121, "Ball M."), each with a Prime Time service (`3.22`, `3.2`). Their resources are courts 2, 3, 8, 9 and ten. The service setup says `ProviderRequired` and `ResourceRequired`.
- On the club site you pick a machine's time on a calendar, then a court in a popup. The popup's Continue calls `SetScheduleInformation` with `{ScheduleDate, Duration, Resource, Provider, SiteId, ProviderId, ResourceId, ServiceId, ServiceName, ServiceUniqueIdentifier}` and the start, then opens `AddFamilyMembersScheduler.aspx?showOfflineMessage=true`, the same participants page courts use. `ClubSite.stage_machine` does exactly that, after checking the machine and the court are both free, so the rest of the engine (keep-alive, presses, report check) is unchanged.
- `play: machine` with `machine: genie | regular | either` in bookings.yaml; no partners; courts limited to 2, 3, 8, 9, 10. `find_open` returns, per length, each free machine court with the machine to use (Genie first for `either`). The service follows Prime Time: a slot inside it uses the Prime Time service, and the booking's lead is 24 hours, split in two parts like singles if it straddles.
- Not yet tried against a real window: whether the participants page for a machine lets a partner be added (bookings are just you for now).

## My reservations

- The Reservation Report (`ReservationReport.aspx`) run for a date range, with `lstModule` = Scheduler and, for family, `ddlIncludeSubMembers` = Yes. It reloads in an UpdatePanel, so the app waits for the PageRequestManager's `endRequest` (or a full reload). Rows are [Schedule, Club, Date, Providers, Resources] with a link holding the `ScheduleGuid`. The report doesn't say whose a row is, so with family on the app reads it twice and marks the rows missing from your own list as family.
- Cancel opens `CurrentScheduleDetail.aspx?ScheduleGuid=...`, checks the page still shows the same date and time, presses Cancel Schedule, waits for the confirm box's Yes to be visible and presses it, then waits for the URL to say CANCELED. The page confirms first and warns inside 24 hours (the club's late-cancel fee). Each cancel is recorded in results.jsonl and shown as a notification.


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

## Timing at the window

- `RealClock` starts from PC time plus the internet-time correction and then runs on `time.monotonic()`, so Windows adjusting its clock during the wait can't move W.
- Just before the window (after the last keep-alive, at least 8 s before W), `RealClock.resync()` reads the club server's own clock: HEAD requests over one kept-open connection until the `Date` header ticks over (`clock.server_offset`, about ±0.06 s). The logins of one run share the clock and the read.
- The participants page shows its rows switched off until the club opens the time, and only a fresh load shows them on. In the author's real windows every accepted booking was a press straight after such a load, and presses on a switched-off page were all refused (one went unanswered for a minute). So `ClubSite.attempt` reloads back to back while the rows are off (`fresh_gap` 0.5 s, `row_watch` 2 s) and presses only once they're on; from W + 75 s the engine forces a press every 15 s as a fallback.
- A run that starts late (the PC was off or asleep) still books what's open, up to 20 minutes after W (`clubtime.LATE_OK`), with the usual 4 minutes of pressing counted from when it starts.

## Coordinated logins

- A booking's `also:` list adds more logins (each with its own partners) that book the same time with the same courts and lengths. `Booking.members` is the booking's own login first, then those.
- One scheduled task runs them all at once (`runner.run_group`): one browser per login, each with its own throwaway profile (two Edge or Chrome sessions never share one), one shared clock, and a `group.Group` that hands out different courts. With nobody placed yet it takes the best block of courts in a row; once someone has a court, the others sit next to it when they can (same bank, one apart).
- Each login gets one line in results.jsonl (`login=`), and the group gets one notification. A Prime Time part or a second session puts each login's own court from the first part first.

## Second session (back-to-back)

- `then: 30|60|90` adds a part `next` from the booking's end, with its own task (" (second session)") and window, on the court the first part got (per login), else by preference. Unlike the Prime Time part it still books when the first part didn't. Refused where either session would cross a Prime Time edge for singles.
- It counts as a second reservation of the day for every login.

## Guard slots (blockers)

- `blocker: true` adds a part `blocker` with its own task, an hour before the main task (" (blocker)"). Not for a main part that books 24 hours ahead (Prime Time singles or ball machines).
- The guard run signs in and skips the day if the login already has a reservation on it (guard + booking + that one would be 3). It reads the day's court sheet and plans with `runner.plan_blocker`: the earliest of main − 60 and main − 30 that is free right up to the start, on a court also free when play starts, in preference order. It then books that one slot with the usual engine, at the slot's own window. Coordinated logins plan in turn, on different courts, next to each other when possible. Each guard is recorded with its start and length. The run has its own lock, because the main task starts while it's still going.
- The main run looks the guard up after its wait (`runner.guard_slot`), tries the guard's court first, and in the same session, once its outcome is known, cancels the guard (`settle_guard`, a week ahead so free) and records the cancel. If the outcome is unknown, the guard is kept and the notification says to check the club site; if the cancel fails, it says to cancel it there.
- **Backstop:** the guard run stays up until 25 minutes after the main window (`_guard_backstop`; the task's 3-hour limit covers it). If the main run hasn't settled a guard by then (the booking was paused, skipped or removed, the PC missed the window, or the run crashed), the guard run cancels it itself. A guard the main run kept on purpose (outcome unknown, recorded as "kept") is left alone; a failed cancel is tried again.
- For singles, a guard never goes in Prime Time (it opens only 24 hours ahead there), so a main starting right after Prime Time gets an earlier-free guard or none.
- The guard is booked with the booking's partners (the club needs a family or buddy member on every booking), so a partner who already has a reservation that day can have the main refused while the guard holds their second.
- Book Now never books a guard: once play opens, every earlier slot is open too, so it would protect nothing.
- A guard doesn't count toward the 2 a day (`Booking.reservations`), since it's gone before the second session's window.

## Email summary

- `email_to`, `email_from` (empty = `email_to`), `smtp_host` (smtp.gmail.com) and `smtp_port` (465) in bookings.yaml. The app password is in Credential Manager under "WAC Court Booker email", keyed by the sending address (`mail.py`), and never in a file, log or email.
- The scheduled task runs `runner.run_and_report`: the run, then one plain email with what that run's notifications said. Below a "details for troubleshooting" divider it adds only the engine's timing lines, never the "signed in as" line or the booking's description, and any number of 5 or more digits is masked. A guard-slot run emails only when its outcome is unknown; otherwise the booking's own run reports the guard.
- **Settings → Email after each booking** saves the addresses and the password and has **Send test email**.

## Lessons carried over from the author's system

- A slot opens exactly 169 hours before it starts. The site starts accepting about 43–45 seconds after that.
- Stage everything early, and keep the staged page fresh until 45 seconds before W.
- Never re-submit over an unanswered booking: check the reservation list first.
- The grid's default view lists only the first few start times, so use its time-of-day search.
- The grid's court list (lstResource) opens with only courts 2-6 selected. Every grid read presses Select All before searching, or courts 8, 9 and ten never show.
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
