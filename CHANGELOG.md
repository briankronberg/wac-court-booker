# Changelog

## 0.5.1

- **Reset** on the booking form, next to **Cancel**: clears every field back to the start. When you're changing a saved booking, it puts the fields back to how the booking was saved.

## 0.5.0

- **Book Now.** A new button next to **Save booking** books straight away when the club is already taking bookings for that time (from a week ahead, or a day ahead in Prime Time). It's greyed out until everything is chosen and the time is open, and the note above the buttons says when it opens. It asks you to confirm first. For a weekly booking it books the soonest such day if that's open, and **Save booking** still books every week after that.
- One-off dates can now be any day from today. **Save booking** is greyed out for a date the club has already opened, since there's nothing left to schedule.
- **See Available Courts** is there for weekly bookings too (it opens on the booking's next date).

## 0.4.3

- **Name the people booking courts.** In **See Available Courts**, press a booked court and type who it is. From then on the calendar shows that person's first initial and full last name on every booking of theirs, on any day. Names are kept on this PC only, and must fit the club's short form (for "Smi, A.", a first name starting with A and a last name starting with Smi), which catches typos. Leave the name empty to forget it.

## 0.4.2

- **See Available Courts shows who booked each court.** Instead of "Booked", a booked half hour shows the booker as a first initial and last name. The club gives only the first few letters of the last name, so you, your buddies and your family show in full and anyone else shows as the club gives it, such as "A. Smi…". Point at a cell for its full text.

## 0.4.1

- **A day you've already filled is caught.** The club allows 2 reservations per login per day and won't take one that overlaps your own. The club site turns such a booking away without saying why, so the app used to keep trying and end with a vague "didn't accept in time". Now a booking checks your reservations for that day first and, if the day is full or the time clashes, stops and says so. **Validate booking** warns about it too, and the menu's test booking skips such days.
- **Fix: after a cancel,** the app showed "The club site said: Do you want to cancel the service?", which was the club's question, not its answer. It now just says the reservation was cancelled.

## 0.4.0

- **Ball machines.** A booking can now be a ball machine instead of singles or doubles: the **Genie** (works with its phone app), the **regular** one, or **either** (Genie first). The app books the machine and a court that takes it (2, 3, 8, 9 or 10) together, at the time the booking opens; Prime Time ball machines book 24 hours ahead, like singles. **See Available Courts** shows each machine's free times and **Validate booking** checks the machine too.
- **My reservations.** A new page lists what's booked on the club site for the next 30 days (or dates you pick), optionally with your family members' reservations, and cancels one after asking. It warns when a cancel is inside 24 hours, when the club charges a fee. Cancels show in **What happened** and as a notification.
- A ball machine booking goes straight through the club's own booking request, instead of clicking through the club's machine, then time, then court pages.

## 0.3.2

- **Fix: the calendar showed the wrong day.** Opening it again for another date reused the window and kept the old day. It now follows the date you pick, and also has its own date box.
- **Fix: courts 8, 9 and 10 in the calendar.** Availability now comes straight from the club's own data for all 8 courts, the same data its court sheet is drawn from, instead of reading the sheet's list 15 rows at a time.
- **Much faster.** The calendar and the court check read a whole day in one request: a few seconds the first time (signing in), about a second after that.
- The calendar says why a court is taken (**Booked** by a member, or **Blocked** for a lesson, league, event or closing), shows when each ball machine is free, and greys out times already past. Press an open court to use that date, time and court in your booking.
- **Calendar view** is now **See Available Courts**, and opens on today if you haven't picked a date.
- **Are courts open?** is now **Validate booking**, next to **Save booking**. It also works for weekly bookings (it checks the next date).

## 0.3.1

- **Fix: courts 8, 9 and 10 were never seen.** The club's court sheet opens with only courts 2-6 selected, and the app read it as it opened. Every booking, the court check and the calendar missed courts 8-10 (a booking with "any other court" never got one of them). The app now selects every court before it reads the sheet, which also shows the 5:00 and 5:30 AM times on those courts.
- Calendar view: taken half hours now say "Taken" in a solid block, so they can't be mistaken for free courts.
- **A first install always puts the WAC Court Booker shortcut on the desktop** (it didn't when setup ran without anyone to answer its question). Setup no longer asks. Updates refresh the shortcut if it's there and don't bring it back if you deleted it; **Settings → Desktop shortcut** makes it again. `setup.cmd -DesktopShortcut No` installs without one.

## 0.3.0

- **Court availability for one-off bookings.** Next to **Just once**:
  - **Are courts open?** reads the club's court sheet and says which courts are free at your date and time right now (and for shorter lengths if you allow them), and whether your first-choice court is one of them.
  - **Calendar view** opens a window with all 8 courts for the day, half hour by half hour: open, taken, Prime Time marked, your time outlined. It has Refresh, Day before and Day after.
  - Both only read the court sheet; nothing goes in your cart.
- **Fix: family members weren't found** when one of them already had 2 reservations on the day the app looked at. The club site then shows that person's row without a member checkbox, and the app skipped the row. It now reads every row.

## 0.2.0

- **A window instead of the text menu.** The Start-menu and desktop shortcuts open the app in its own window, with three pages: My bookings, What happened and Settings. Booking a court is one form of big buttons (singles or doubles, names to click, day, time, length, courts in order). It reads the booking back in plain words before you save. Each booking has Change, Skip a week, Pause and Remove.
- **First run:** after setup, the window walks through signing in to the club, getting the PC ready (wake timers, clock, signed-out runs), finding family members and booking the first court.
- **Updates:** the window checks GitHub for a newer release each time it opens, and on **Check for updates**. When there is one, it shows the download link and the steps.
- Club-site checks (test sign-in, buddy list, family, court sheet, test booking) show their progress in the window. The test booking's questions are Yes/No buttons.
- The window is a page served only to this PC (127.0.0.1) and locked with a random key. It stops a few minutes after you close it, and setup closes it before updating.
- `wac-booker menu` still opens the text menu.
- **Settings → Desktop shortcut** puts a shortcut to the window on the desktop, or makes it again (for example if an old one opens the text menu).
- **Prime Time** (Monday-Friday 9:00-10:30 AM, Monday-Thursday 5:00-8:00 PM), where the club opens singles courts only 24 hours ahead:
  - Singles entirely in Prime Time are now booked 24 hours ahead instead of a week ahead. Doubles are unchanged.
  - Singles that run into or out of Prime Time are booked in two parts: the regular hours a week ahead, then the Prime Time part 24 hours ahead on the same court if it's free (only if the first part was booked). Each part counts toward the 2 reservations a day.
  - The booking form warns when a singles time touches Prime Time and offers nearby times that stay on one side. Each booking card says how Prime Time affects it.
- My bookings explains the booking limits and lists the Prime Time hours.
- About shows who made the app, with links to its GitHub page and the WAC Tennis FAQ.
- Sandbox test: the desktop-shortcut checks are gone; it checks the page server instead.

## 0.1.8

- **Desktop shortcut:** setup asks once whether to put a WAC Court Booker shortcut on the desktop as well as in the Start menu. The answer is remembered, so updates don't ask again, and an existing desktop shortcut is refreshed. `setup.cmd -DesktopShortcut Yes|No` answers without asking.
- DESIGN.md is in the download again.

## 0.1.7

- The release zip holds only what a user needs: README.md, setup.cmd, setup.ps1, get-pwsh.ps1, pyproject.toml and the app. Tests, design notes, this changelog and developer docs stay in the repo (`.gitattributes` export-ignore).
- README covers only installing and using the app. Developer notes (unit tests, the Windows Sandbox test, releasing) are in DEVELOPMENT.md. The second-PC test checklist is removed.

## 0.1.6

- Menu 1 says how often a booking runs: "Next runs, every week until you remove or pause it" for a weekly booking, or "Runs once" for a one-off. The two runs listed are only the next ones.

## 0.1.5

- **Clearer layout for menu 1 (Show my bookings):** each booking says what it books ("Every Tuesday, 6:00 to 6:30 AM, singles with ..."), its courts in order and its login. Under "Next runs (courts open 1 week + 1 hour ahead)", each line pairs the moment the app books with the court time it books, and when the PC must be on. That time shows its date when it falls on the day before. The task line says "Scheduled task".

## 0.1.4

- **Fix: reading family members found nobody.** Each member row on the participants page starts with a cell that holds only a checkbox. The reader took that empty cell as the name and skipped every row. It now reads the cells that have text, on rows with a member checkbox. If it still finds nothing, it logs the table's layout.
- **No booking name to type.** The name is made from the booking, for example "Tue 6:00 PM singles with Andrea" or "Sat 12/19 8:30 AM doubles with Pat, Sam, Kim", with " (2)" added if another booking already has it. When you edit a booking, a made-up name follows the changes; a name typed by hand in bookings.yaml stays.
- **Updating while the app is open:** setup used to fail with a pip "file in use" error. It now says to close the menu window, waits up to 5 minutes, and carries on by itself once it's closed. It never stops a running booking.
- **Sandbox test:** the test login ("test-no-password") and test bookings now live in a scratch app folder with their own task folder (`\WAC Court Booker\Test\`), so they never appear in the person's menu. A new check confirms the person's own bookings.yaml and tasks are untouched. Older runs' test entries are removed from it.
- **Singles is the default,** and "s" or "d" is enough as an answer.

## 0.1.3

- **Family members at the top of the partner list.** The club site lists family members (Spouse, Child, ...) only on the participants page, which opens once a court is in the cart. The app saves them each time it reaches that page (test booking, real booking). The wizard and menu 7 ("Read a login's family members") can also read them on purpose: they put a quiet 30-minute court in the cart for a few seconds, read the list, then press Back, which empties the cart. Nothing is booked. In the partner list, family members come first and are marked "(family)".
- **Partner picker:** partners are chosen from the buddy list with the arrow keys. Typing narrows the list, Enter chooses and Esc takes back the last pick. The last row, "Someone not on this list", lets you type a family member's full name. When input isn't a console (piped), partners are typed as before.
- **"Run while signed out?":** the question now explains both ways a scheduled task can run, and that the signed-out way stores your Windows user name and password with the task. The wizard and menu 7 use the same wording.
- **Fix: "list index out of range".** When a page script timed out, the error message came back empty, and building it raised IndexError instead of the app's own retryable error. That stopped the test booking on the first slow page, and a real booking would have stopped the same way. Now a slow page is a normal error and gets retried, and the "Booking Details" box is polled through brief page changes.
- **Test booking log:** everything the test booking shows, and any unexpected error with its details, now also goes to the log and to results. An error no longer stops the wizard.

## 0.1.2

- Setup works on a PC without winget, such as Windows Sandbox or some managed or older PCs:
  - **PowerShell 7:** `setup.cmd` downloads PowerShell 7.7.0 into the app's own folder (no admin needed), checked against Microsoft's published SHA-256. The app looks there for PowerShell too.
  - **Python:** setup installs the official Python 3.14.10 for the current user from python.org, checked by SHA-256 and by its Python Software Foundation signature.
- The python.org install shows its progress window and installs only what the app needs (no docs, Tcl/Tk, headers or tests), so it no longer looks hung for 15 minutes.
- `tests/sandbox/run-sandbox-test.ps1`: unattended clean-install test in Windows Sandbox. It never signs in to the club.

## 0.1.1 (ready for a second-PC test)

- Setup installs standard Python 3.13 for the current user when none is found (the Python Install Manager is now the fallback). It also finds a per-user Python that isn't on PATH yet, rebuilds the app's environment if its Python was removed, and clears the "downloaded from the internet" mark on the unzipped files.
- Partner picker: offers to read the buddy list if it hasn't been read yet, and accepts a family member's full name even though they aren't on the buddy list.
- docs/second-pc-test.md: install-and-test checklist for a new PC. README covers downloading from Releases and the SmartScreen prompt.

## 0.1.0 (first release, Windows)

- Menu app and commented `bookings.yaml`: add, edit, remove, skip dates, pause and resume bookings; logins with passwords in Windows Credential Manager; browser choice; signed-out runs; wake timers.
- One Task Scheduler task per booking under `\WAC Court Booker\`: wakes the PC, starts late if it was off, never two copies at once. Weekly tasks start 75 minutes before the window so daylight-saving weeks are still early. Optional "Password" logon for signed-out runs, falling back to "signed in" when the PC refuses.
- Booking engine: stage before W, keep the page fresh until W − 45 s, press from W + 1 s once a second, court and length fallback, no re-press over an unanswered commit (reservation report, then grid), give up at about W + 4 min.
- Singles look in both "2 Singles" and "3.1 Primetime Singles" (evening singles are Primetime); doubles use "1 Doubles".
- Test everything: login, clock, buddy list, read-only dry run, and a real test booking (30 min, more than 24 h away) with confirm and cancel.
- Toasts and a log for every run, plus "missed" toasts when the PC was off at W.
- Test booking checked live: booked on the first press (hidden browser, host plus a household partner), then cancelled. The cancel waits for the site's confirm box before pressing Yes; the Yes button sits hidden in the page beforehand and pressing it early does nothing.
- `setup.cmd` installs PowerShell 7 and Python if missing, the app, its Chromium and a Start-menu shortcut.
