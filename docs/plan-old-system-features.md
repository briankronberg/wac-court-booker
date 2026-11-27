# Plan: bring the old system's features into WAC Court Booker

Branch: `old-system-features`. Work started from `main` at v0.5.1. The owner chose these features from the old `wac-court-booking` repo:

| # | Feature | State |
|---|---|---|
| 1 | Clock fix just before the window | **Done** (commit ec59ead) |
| 2 | Late start (book up to 20 min late) | **Done** (ec59ead) |
| 3 | New speed ideas: press only on a freshly loaded, switched-on page | **Done** (ec59ead) |
| 4 | Coordinated logins (several logins, same time, different courts, side by side) | **Started**: config and profiles done, engine/runner/UI to do |
| 5 | Back-to-back (second session right after, same court) | To do |
| 6 | Blockers (guard slot before the main, cancelled automatically) | To do |
| 7 | Email summary | To do |

Not chosen (don't build): phone push (ntfy), evening-before check, after-run check, nightly reservation log, rehearsal.

Rules that still apply: never book, cancel or hold a real court without the owner's OK for that run (read-only probes are fine); never see, print, log or commit passwords; no names or member numbers in notifications; user-facing docs (README, zip, release notes) cover install and use only; use `pwsh`; commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; PR bodies end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`; the README intro (lines 3–6) stays unchanged.

Tests: `"$env:LOCALAPPDATA\WAC Court Booker\venv\Scripts\python.exe" -m pytest -q tests` (138 pass at the time of writing). Release flow: see DEVELOPMENT.md (PR, sandbox test `tests/sandbox/run-sandbox-test.ps1 -Reuse`, merge, tag, `git archive` zip, `gh release create`).

## What's done

### 1. Clock (`clock.server_offset`, `engine.RealClock`)
- `clock.server_offset()` sends HEAD requests to the club login page over one kept-open connection until the `Date` header ticks over. That gives the club server's clock to about ±0.06 s (measured: PC −0.79 s, matching SNTP −0.80 s).
- `RealClock` runs on `time.monotonic()` from its start, so a Windows clock adjustment can't move W. `resync()` reads the club clock once per run (a lock is shared by all logins in a group). On failure it keeps the earlier correction.
- `Engine.run` calls `clock.resync()` after `hold()` (between W−105 s and W−45 s) when more than `Timing.resync_by` (8 s) is left. The runner builds `RealClock(offset, measure=clock.server_offset)`.

### 2. Late start
- `clubtime.LATE_OK` is now 20 min, and `Timing.late_ok` is 20 min.
- A run that starts late gets `give_up = now + 240 s`.
- The commit loop starts its ticks from now, so there's no burst of catch-up presses.

### 3. Speed (evidence: the old system's logs under `%LOCALAPPDATA%\hermes\state\wac-saturday\runs\*\engine-*.log`)
- Every accepted booking in about 20 real windows was a `fast_path` press straight after a fresh load of the participants page that showed its rows switched on.
- Forced presses on a switched-off page were always refused ("None of the listed individuals are eligible"). One got no answer for 60 s.
- The old cycle also idled 8 s watching for rows after each reload.
- Now, `ClubSite.attempt(partners, force=False)`:
  - while the rows are off, it reloads the page back to back (`fresh_gap` 0.5 s, `row_watch` 2 s) and returns `NOT_READY` without sending anything;
  - it presses only once the rows are on.
- `Engine.commit_loop` passes `force=True` once every `force_every` (15 s) after `force_after` (W + 75 s), as a fallback.
- `runner.test_booking` forces from its fourth try.
- `FakeSite` models this, and `forced_only=True` keeps the old "every press is sent" model for the no-answer tests.
- A possible next step, not built and needing a real-window test with the owner's OK: a second page in the same session reloading out of phase with the first, so a switched-on render lands sooner (one login's renders took 12–18 s near W). Keep "never press over an unanswered commit" across both pages.

### 4a. Coordinated logins: what's in place
- `config.Member(login, partners)`, `Booking.also: list[Member]`, `Booking.members` (own login first), `Booking.for_member(m)`.
- Parsed from YAML:
  ```yaml
  also:
    - login: partner
      partners: [Kim Park]
  ```
  It's validated (partner count per play; no ball machines; no login twice; no person partnered with two logins) and written by `booking_to_map`.
- `config.check()` checks logins, overlaps and the 2-a-day cap per login across all members. It uses the new `Booking.span_end` and `Booking.reservations` properties, which back-to-back will extend.
- `paths.profile_dir(browser, tag)` and `ClubSite.start/close`: Edge/Chrome sessions each get a throwaway profile folder (`profiles/<browser>-<user>-<pid>-<n>`), deleted on close. This fixes two simultaneous runs fighting over one profile.
- No tests have been added for 4a yet.

## What's left

### 4b. Coordinated logins: engine and runner
1. **`wacbooker/group.py`** (new): `Group(size)` with `want: {idx: court}`, `chooser(idx)`, `release(idx)`.
   - `pick(idx, open_by_len, booking, tried)` goes through `booking.lengths` (longest first).
   - Courts are ordered by preference: named courts, then `any` by number. Drop courts in `tried` and courts other members want.
   - If other members already hold courts, take the best-ranked court next to one of them. Next to means the same bank, numbers one apart; the banks are (2,3,4,5,6) and (8,9,10).
   - Otherwise take the first court of the best block of k free courts in a row (k = members still without a court; lowest rank sum), falling back to the k best courts.
   - Record `want[idx]` and return the `Slot`.
   - Unit-test the cases: 5 and 6 open; 5, 8 and 9 open with prefs [5, any] (expect 8 and 9); one court open.
2. **`engine.Engine`**: an optional `chooser` argument, used in `choose()` in place of `pick`.
3. **`runner`**: `run_group(cfg, b, occ, clock, log, part)`.
   - For each member: `start_site` (that login), `Engine(b.for_member(m), ..., chooser=group.chooser(i))`, run all with `asyncio.gather`.
   - Wrap each member so an exception becomes a `RunResult("unsure", ...)`. Release the site and `group.release(i)` on not_booked. Run `keep_family` and close in `finally`.
   - Use it from `_run_async` (one shared `RealClock`) and `book_now`.
   - Check `creds.has_password` for every member's login.
   - Record one `results.record(...)` per member with `login=<nickname>`, and send one combined toast ("Booked: Ct 5 ... · Ct 6 ...").
   - `main_part_court(name, day)` must take a login. Results without `login` belong to the booking's own login.
   - The Prime Time part puts each login's own main court first.
4. **Web and form** (`web.py` `_form_booking`, booking JSON at about line 97; `index.html` form): "Also book for another login at the same time" lets you pick a login plus that login's partners (use the partner picker for that login's buddy list). Show it in the plain-words booking description on My bookings. Hide it for ball machines.
5. **Tests**: config parse/check for `also`, the group court choice, and a two-member run with two `FakeSite`s sharing one `FakeClock`, asserting different, side-by-side courts.

### 5. Back-to-back
- `Booking.then: 0|30|60|90` (YAML `then:`; 0 = off): a second session from `end` to `end + then`, on the same court if it's free.
- Add a part `"next"`. Its window opens `length` minutes after the main's.
- Only when neither session crosses a Prime Time edge for singles (refuse with a plain error otherwise). Sessions entirely inside Prime Time are fine, with a 24 h lead.
- `span_end` becomes `end + then`, and `reservations` +1.
- Scheduler: one more task per booking, `task_name(..., "next")` with the suffix " (second session)", `--part next`.
- Runner: like the `prime` part, put the court the main part got (per login) first. Unlike `prime`, still book if the main wasn't booked: playing the second session alone is still play.
- Book Now: book the second session after the first, if its window is open.
- Form: "Book a second session right after" with a length choice.
- Coordinated logins: each member books its own second session.

### 6. Blockers
- `Booking.blocker: bool`, for bookings whose main part has a 169 h lead (not Prime Time singles).
- The rule, from the old `wac_core.plan_blocker`: on the court the main will take, find the earliest start s in {main − 60, main − 30} such that [s, main) is free. Then the blocker is s → main (30 or 60 min). If neither is free, no blocker.
- Read the court sheet with `ClubSite.day_availability` (minutes per court), the same as `runner.courts_free`.
- Choose the main's court with `engine.pick`, or `Group` for coordinated logins, over the courts free for the main.
- Part `"blocker"`, with its task due at W_main − 60 min. The run signs in, plans the blocker, then runs an `Engine` with W = W_main − L for a `Booking` of that court only and length L. It uses the same play and partners, and skips if the login already has another reservation that day: the main needs the room (2 a day).
- The main run puts the blocker's court first, read from results by login. When the main's outcome is known (booked or not), cancel the blocker in the same session: find it in `site.reservations(date, date)` by start, end and court, then call `site.cancel_reservation(guid, row)`. It's a week out, so cancelling is free.
- The `next` part also cancels any leftover blocker before its day check: blocker + main + second session would be 3.
- If a cancel fails, toast "Cancel the blocker on the club site".
- Results: `kind "run", part "blocker"`.
- Form: a "Protect the start time with a blocker" checkbox, explained in plain words.

### 7. Email summary
- Settings: an email address to send to, plus an SMTP account. The default is Gmail with an app password, which goes into Windows Credential Manager through the app's own prompt, as the club passwords do (`creds`). Use `smtplib` with SSL on 465.
- One plain email per scheduled run, and per group, with the outcome, courts and times, and what to do. Logs go under a "details" divider. No member numbers.
- A "Send test email" button. Never put the password in `bookings.yaml` or the logs.

### 8. Finish
- DESIGN.md: how each new piece works.
- README: what a booking can be (together, second session, blocker, email), in install-and-use terms only.
- CHANGELOG, then bump the version (minor: 0.6.0) in `pyproject.toml` and `wacbooker/__init__.py`.
- Run the sandbox test, open a PR, merge, release, and install on the PC with a one-time task in `\WAC Court Booker\Test\`, deleted afterwards.
- Offer the owner one real-window test of the new press logic and of the group run, which books real courts, so only with their OK.
