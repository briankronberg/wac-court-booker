# Testing on a second PC

A checklist for the first install on a PC other than the author's. It covers the parts that couldn't be tested on the build PC: a clean Python install, a different Windows account, and possibly a signed-out run.

Allow about 20 minutes. Steps 1–7 never book anything. Step 8 books a real court, then cancels it.

## Before you start

- Windows 10 or 11, signed in as the person who'll use it. Admin rights help but aren't needed.
- Internet access. Setup downloads PowerShell 7 and Python if they're missing, plus about 125 MB for the app's browser.
- The club username and password for the login you'll use.

## Steps

1. **Download.** On GitHub, open the repo's **Releases**, download `wac-court-booker-<version>.zip`, and unzip it. Downloads is fine; once setup has run, the folder can go.
2. **Run setup.** Double-click `setup.cmd`.
   - If Windows says "Windows protected your PC", choose **More info → Run anyway**. That happens because the file came from the internet.
   - Setup prints each step: Python, App environment, Browser, Notifications and Start menu. It takes 2–5 minutes.
   - ✅ It ends with "Installed WAC Court Booker <version>" and starts the wizard.
   - ❌ If it stops, the red line says why, and the full log is `%LOCALAPPDATA%\WAC Court Booker\logs\setup.log`.
3. **Wizard: add the login.** Type a nickname, the club username and the password (the password doesn't show as you type).
   - ✅ "Signed in to the club site as <name>", then "<n> buddies saved".
4. **Clock.** ✅ "That's fine" (under 2 s). Otherwise turn on Settings → Time & language → Set time automatically.
5. **Signed-out runs.** Answer **yes** once to try it. Windows asks for the Windows password.
   - ✅ Either the tasks save, or you see a plain note saying Windows wouldn't allow it and bookings will run while signed in. Both are fine; write down which.
6. **Wake timers.** ✅ "Wake timers are on" (or "already on").
7. **Add a booking.** Add a real weekly booking, then choose menu **1**.
   - ✅ It shows "Books <day> …: window opens … (the PC must be on by …)" and "Task: ready".
   - Open Task Scheduler and look in **WAC Court Booker**: there should be one task per booking.
   - Choose **8** and answer **no** at the test booking. ✅ The login test, clock, buddy list and dry run all report without errors.
8. **Test booking (real).** Choose **8** again, and this time answer **yes** at step 5.
   - ✅ "Booked Ct …", then check that it shows on the club site or app.
   - Answer **yes** to "Cancel this test booking now?". ✅ "Cancelled, and it's gone from your reservation report."
   - Check the club site again: it should be gone.
9. **First real run.** Leave the PC on (asleep is fine) when menu 1 says it must be on. Afterwards you should have a toast ("Booked: …" or "Not booked: …"), and menu **9** shows the result.

## What to send back

- Which steps passed, and the exact wording of anything that didn't.
- Step 5: did signed-out runs save, or did it fall back?
- `%LOCALAPPDATA%\WAC Court Booker\logs\setup.log` and `logs\wac-booker.log`. They never contain passwords, but they do contain names and the club username, so share them privately.

## Removing it

1. In the menu, remove each booking. That also deletes its scheduled task.
2. Under **7 → Remove a login**, remove each login. That deletes the saved password.
3. Delete `%LOCALAPPDATA%\WAC Court Booker` and the Start-menu shortcut.
