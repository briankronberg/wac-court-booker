# The club site and this app

What the member side of the club site (Spectrum NG, WAC Hartland) can do, what the app does with each part, and what it could do next. Surveyed read-only on a signed-in account.

## The club site

The member menu has four areas: **Make a Reservation**, **Account Information**, **Class Registration** and **Session Registration**. Reservations have one category, Tennis Courts, with these services:

| Service | What it is | Lead |
|---|---|---|
| 1 Doubles | a court, host + 3 | 1 week 1 hour |
| 2 Singles | a court, host + 1 | 1 week 1 hour |
| 3.1 Primetime Singles | singles in Prime Time | 24 hours |
| 3 Ball Machine / 3.2 Primetime Ball Machine | the regular machine on courts 2, 3, 8, 9, ten | 1 week 1 hour / 24 hours |
| 3.01 Genie Ball Machine / 3.22 Primetime Genie | the Genie (phone app) on the same courts | 1 week 1 hour / 24 hours |
| 3.0 Serves / 3.3 Primetime Serves | a court for serve practice | 1 week 1 hour / 24 hours |

Everything the court pages show comes from one JSON web service (`Library/OlsService.asmx`): services by category, service setup (lengths 30-90 in 30s, provider and resource required), resources (courts), providers (machines), and per-day availability for courts, machines, services and the club. The member's own items: the cart, the Reservation Report (any date range, optionally with family members, filtered by module), and each reservation's detail page (participants with **Remove**, **Add Member to this Schedule**, **Cancel Schedule**). The buddy list lives under Account Information.

## What the app covers

| Club site | App |
|---|---|
| Book doubles and singles | Yes, automatically the moment the window opens, weekly or one-off, with court preference, shorter fallback and Prime Time splits |
| Ball machines (both) | **Yes (0.4.0).** Genie, regular or either; the app pairs the machine with a court that takes it, in one step |
| Court availability for a day | **See Available Courts**: all 8 courts and both machines on one screen, booked vs blocked, press a court to use it |
| Check a time before booking | **Validate booking** |
| Reservation Report | **My reservations** (0.4.0), next 30 days by default, family optional |
| Cancel a reservation | **My reservations → Cancel** (0.4.0), with the 24-hour fee warning |
| Buddy list | Read and used to pick partners (family found through the participants page) |
| Serves (3.0, 3.3) | Not yet |
| Book something already open now (inside the week) | Not yet: the app books when the window opens, and sends sooner dates to the club site |
| Add or remove a participant on an existing reservation | Not yet |
| Edit the buddy list | No (read only) |
| Class and session registration | No (outside court booking) |
| Cart, payments, series sales | No (court bookings need none) |

## Worth doing next

1. **Book now.** For a date inside the week that's already open, book it immediately with the same engine (find, stage, press once). The club site needs about six clicks for this; the app would need one. Same rules: only on the person's press, never on its own.
2. **Swap a partner.** From **My reservations**, change who you're playing with: the detail page has Remove and Add Member. Useful when a partner drops out.
3. **Serves.** One more play type, like the ball machine (a court for one, its own Prime Time service).
4. **Waitlist a taken time.** Watch a taken time on the calendar and book it if a court frees up (someone cancels). Read-only polling every few minutes through the web service is cheap; the booking itself would use the engine.
5. **Ball machine with a partner.** The participants page may allow a second person; it hasn't been tried against a real window.
6. **Clash check.** Warn in the booking form when a family member or partner already has 2 reservations that day (the club turns the booking away then).
