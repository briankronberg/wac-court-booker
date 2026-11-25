# Changelog

## 0.1.4

- **Fix: reading family members found nobody.** Each member row on the participants page starts with a cell that holds only a checkbox. The reader took that empty cell as the name and skipped every row. It now reads the cells that have text, on rows with a member checkbox. If it still finds nothing, it logs the table's layout.
- **No booking name to type.** The name is made from the booking, for example "Tue 6:00 PM singles with Andrea" or "Sat 12/19 8:30 AM doubles with Pat, Sam, Kim", with " (2)" added if another booking already has it. When you edit a booking, a made-up name follows the changes; a name typed by hand in bookings.yaml stays.
- **Updating while the app is open:** setup used to fail with a pip "file in use" error. It now says to close the menu window, waits up to 5 minutes, and carries on by itself once it's closed. It never stops a running booking.
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
