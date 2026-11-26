# Web interface: plan

## Goal

Replace the numbered console menu with a page that someone who rarely uses a computer can follow without help. Booking a court should take a handful of clicks, with no typing beyond the club login.

## How a person uses it

1. **Install.** They double-click setup.cmd. When it finishes, the app opens in its own window (Edge in app mode, so there's no address bar or tabs).
2. **First visit.** The page shows a short welcome with three steps:
   - **Sign in to the club.** Type the club username and password. The app tests the login, reads the buddy list, then offers to read family members, explaining what that does and asking first.
   - **Keep the PC ready.** Turn on wake timers with one button. The clock check runs by itself. "Run while signed out" is an optional switch, explained in two sentences.
   - **Book your first court.**
3. **Booking a court** is one form, top to bottom, made of big buttons rather than typed answers:
   - Singles or Doubles.
   - Who's playing: a list of names, family first. A search box narrows it. "Someone else" takes a full name.
   - Every week, or just once (with a date).
   - The day: seven buttons.
   - The start time, from a list of times on the hour and half hour.
   - The length: 30, 60 or 90, plus "or shorter if needed".
   - Courts: click them in order of preference, plus "any other court" at the end.
   - A sentence at the bottom reads the booking back in plain words, for example "Every Tuesday, 6:00 to 7:30 PM, singles with Andrea. Court 5, then 4, then any court." Then one Save button.
4. **Home ("My bookings").** One card per booking, saying what it books and when the app books it next, with "keep the PC on by …". Each card has Edit, Skip a date, Pause or Resume, and Remove. A big "Book a court" button sits at the top.
5. **Results.** "What happened": booked, not booked and skipped, newest first, with a clear icon for each.
6. **Settings.** Logins (add, test, re-read buddies or family, remove), signed-out runs, wake timers, browser, a test booking (real, cancelled straight after, only on a click) and "Open the log".
7. **Updates.** On every visit the header checks the latest GitHub release against the installed version. A "Check for updates" link in the header does the same on demand. When a newer version exists, a banner says so and gives the steps: download, unzip, double-click setup.cmd.

## How it's built

- `wac-booker web` (and the windowless `wac-booker-web.exe`, which the Start-menu and desktop shortcuts now open) starts a small web server built into Python. It listens on 127.0.0.1 only, on a free port, and opens the page.
- If the app is already open, the shortcut reuses the running server instead of starting another (`web.json` in the app folder).
- **Security:**
  - Every API call carries a random token that's made at start-up and given to the page through its URL.
  - The server refuses requests whose Host isn't 127.0.0.1:port. This blocks other websites and DNS rebinding.
  - Passwords pass straight to Windows Credential Manager and are never logged or returned.
- The page sends a heartbeat. A few minutes after the window closes, the server stops by itself, unless a job (such as a test booking) is still running.
- Club-site jobs run one at a time in a background thread: test login, buddy list, family members, dry run and test booking. The page polls for their progress lines. The test booking's two questions ("Do you see it?", "Cancel it now?") show as Yes/No buttons.
- **The same rules as the menu apply:**
  - Every change goes through `config.from_doc` before it's saved, and the scheduled tasks are rebuilt.
  - A one-off date whose window has already opened is refused.
  - Names are made automatically.
- **No new dependencies:**
  - The server uses only Python's standard library.
  - The page is one HTML file with its own CSS and JS, and loads nothing from the internet.
  - The update check is the only internet call. It goes to `api.github.com`, with a generic User-Agent.
- The console menu stays available as `wac-booker menu`, for anyone who prefers it.
