"""The booking engine: stage before W, commit from W + 1 s, read every answer.

It talks to the club site only through the `Site` interface below, and to
time only through a `Clock`, so the whole run can be tested offline with a
fake site and a fake clock (tests/test_engine.py).

Lessons carried over from the author's system:
- Stage everything early; keep the staged page fresh until 45 s before W.
- The server turns commits away harmlessly until about W + 43-45 s, so press
  from W + 1 s once a second; early refusals cost nothing.
- Never press again over an unanswered commit: check the reservation report
  (and, failing that, the grid) first, so a run can't double-book.
- The site glitches for one login now and then (empty grid, a participants
  page that never loads): retry the whole staging sequence.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol

from . import clubtime
from .config import Booking

# Outcomes of one commit attempt (Site.attempt).
CONFIRMED = "CONFIRMED"   # reached the confirmation page
REJECTED = "REJECTED"     # the server re-rendered the participants page with a message
OFFPAGE = "OFFPAGE"       # the answer landed somewhere else (bounced, signed out)
NO_POST = "NO_POST"       # the press didn't send anything
UNKNOWN = "UNKNOWN"       # a commit was sent and no answer came back
NOT_READY = "NOT_READY"   # the page was still loading; nothing was sent

EARLY_MARKERS = ("advance", "eligible for enrollment")


def is_early_rejection(message: str) -> bool:
    """Turned away because the window/gate isn't open yet, not because the court went."""
    m = (message or "").lower()
    return any(k in m for k in EARLY_MARKERS)


@dataclass(frozen=True)
class Slot:
    date: str        # MM/DD/YYYY, the site's format
    start: int       # minutes after midnight
    length: int
    court: int
    resource: str = ""
    service: str = ""

    @property
    def end(self) -> int:
        return self.start + self.length

    def describe(self) -> str:
        m, d, y = self.date.split("/")
        day = datetime(int(y), int(m), int(d))
        return f"Ct {self.court}, {day:%a} {int(m)}/{int(d)} {clubtime.fmt_time(self.start)}, {self.length} min"


class SiteError(RuntimeError):
    """kind: 'taken' (the court isn't there any more), 'login' (bad sign-in),
    or 'glitch' (anything worth retrying)."""

    def __init__(self, message: str, kind: str = "glitch"):
        super().__init__(message)
        self.kind = kind


@dataclass
class Attempt:
    outcome: str
    detail: str = ""


class Site(Protocol):
    async def login(self) -> str: ...
    async def find_open(self, date: str, start: int, lengths: list[int], play: str) -> dict[int, dict[int, Slot]]: ...
    async def stage(self, slot: Slot) -> None: ...
    async def keepalive(self) -> None: ...
    async def is_staged(self) -> bool: ...
    async def attempt(self, partners: list[str]) -> Attempt: ...
    async def reservation_exists(self, slot: Slot) -> bool | None: ...
    async def slot_still_open(self, slot: Slot) -> bool | None: ...


class Clock(Protocol):
    def now(self) -> float: ...
    async def sleep(self, seconds: float) -> None: ...


class RealClock:
    """PC time plus a correction measured against internet time (seconds)."""

    def __init__(self, offset: float = 0.0):
        self.offset = offset

    def now(self) -> float:
        return time.time() + self.offset

    async def sleep(self, seconds: float) -> None:
        if seconds > 0:
            await asyncio.sleep(seconds)


@dataclass
class Timing:
    first_tick: float = 1.0      # first press at W + 1 s
    give_up: float = 240.0       # stop pressing about 4 minutes after W
    keepalive: float = 60.0      # reload the staged page this often
    freeze: float = 45.0         # no reloads in the last 45 s before W
    stage_by: float = 90.0       # staging retries stop at W - 90 s
    login_tries: int = 3


@dataclass
class RunResult:
    status: str                  # booked | not_booked | unsure
    message: str
    slot: Slot | None = None
    attempts: list[dict] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    @property
    def booked(self) -> bool:
        return self.status == "booked"


def pick(open_by_len: dict[int, dict[int, Slot]], booking: Booking,
         tried: set[tuple[int, int]]) -> Slot | None:
    """First choice by length (longest first), then court preference, then
    'any' (lowest court number first). Skips (court, length) pairs in `tried`."""
    named = [c for c in booking.courts if c != "any"]
    for length in booking.lengths:
        avail = {c: s for c, s in (open_by_len.get(length) or {}).items() if (c, length) not in tried}
        for c in named:
            if c in avail:
                return avail[c]
        if "any" in booking.courts:
            rest = sorted(c for c in avail if c not in named)
            if rest:
                return avail[rest[0]]
    return None


class Engine:
    def __init__(self, booking: Booking, occ: clubtime.Occurrence, site: Site, clock: Clock,
                 timing: Timing | None = None, log: Callable[[str], None] | None = None):
        self.b = booking
        self.occ = occ
        self.site = site
        self.clock = clock
        self.t = timing or Timing()
        self._log = log or (lambda m: None)
        self.W = occ.window.timestamp()
        self.date = occ.day.strftime("%m/%d/%Y")
        self.tried: set[tuple[int, int]] = set()
        self.slot: Slot | None = None
        self.lines: list[str] = []
        self.attempts: list[dict] = []

    # ------------------------------------------------------------ helpers
    def log(self, msg: str) -> None:
        rel = self.clock.now() - self.W
        line = f"W{rel:+.1f}s {msg}"
        self.lines.append(line)
        self._log(line)

    def rel(self) -> float:
        return self.clock.now() - self.W

    async def sleep_until(self, t: float) -> None:
        d = t - self.clock.now()
        if d > 0:
            await self.clock.sleep(d)

    def result(self, status: str, message: str) -> RunResult:
        return RunResult(status, message, self.slot, self.attempts, self.lines)

    def _none_open_msg(self) -> str:
        return (f"Not booked: no court open at {clubtime.fmt_time(self.b.time)} "
                f"{self.occ.day:%a %m/%d}. Book on the club site.")

    # ------------------------------------------------------------ steps
    async def login(self, deadline: float) -> None:
        last: Exception | None = None
        for n in range(1, self.t.login_tries + 1):
            try:
                who = await self.site.login()
                self.log(f"signed in as {who}")
                return
            except SiteError as e:
                last = e
                self.log(f"sign-in try {n} failed: {e}")
                if e.kind == "login":
                    raise
                if self.clock.now() + 10 > deadline:
                    break
                await self.clock.sleep(5 * n)
        raise SiteError(f"couldn't sign in: {last}", "login")

    async def choose(self) -> Slot | None:
        open_by_len = await self.site.find_open(self.date, self.b.time, self.b.lengths, self.b.play)
        summary = {L: sorted(v) for L, v in open_by_len.items()}
        self.log(f"open courts by length: {summary}")
        return pick(open_by_len, self.b, self.tried)

    async def stage_best(self, deadline: float) -> bool:
        """Stage the best open slot, retrying glitches until `deadline` and
        moving down the list when a court turns out to be taken."""
        attempt = 0
        while True:
            slot = None
            try:
                slot = await self.choose()
                if slot is None:
                    self.slot = None
                    return False
                self.log(f"staging {slot.describe()}")
                await self.site.stage(slot)
                self.slot = slot
                self.log("staged")
                return True
            except SiteError as e:
                if e.kind == "taken" and slot is not None:
                    self.tried.add((slot.court, slot.length))
                    self.log(f"Ct {slot.court} ({slot.length} min) is taken; next court")
                    continue
                if e.kind == "login":
                    raise
                attempt += 1
                wait = min(5 * attempt, 20)
                if self.clock.now() + wait + 30 > deadline:
                    self.log(f"staging failed, out of time: {e}")
                    raise
                self.log(f"staging try {attempt} failed ({e}); again in {wait}s")
                await self.clock.sleep(wait)
                if attempt >= 2:
                    await self.login(deadline)

    async def hold(self) -> None:
        """Keep the staged page alive until W - freeze."""
        freeze_at = self.W - self.t.freeze
        while True:
            nxt = self.clock.now() + self.t.keepalive
            if nxt >= freeze_at:
                return
            await self.sleep_until(nxt)
            try:
                await self.site.keepalive()
            except SiteError as e:
                self.log(f"keep-alive failed ({e}); re-staging")
                await self.restage(deadline=freeze_at)

    async def restage(self, deadline: float) -> bool:
        """Get back onto a staged participants page: same slot if it's still
        open, otherwise the next choice."""
        if self.slot is not None:
            try:
                await self.site.stage(self.slot)
                self.log("re-staged")
                return True
            except SiteError as e:
                if e.kind == "taken":
                    self.tried.add((self.slot.court, self.slot.length))
                    self.log(f"{self.slot.describe()} is gone; next choice")
                elif e.kind == "login":
                    raise
                else:
                    self.log(f"re-stage failed ({e}); signing in again")
                    try:
                        await self.login(deadline)
                    except SiteError:
                        return False
        try:
            return await self.stage_best(deadline)
        except SiteError:
            return False

    async def reconcile(self) -> bool | None:
        """After an unanswered commit: True = booked, False = not booked, None = can't tell."""
        exists = None
        for _ in range(2):
            try:
                exists = await self.site.reservation_exists(self.slot)
            except SiteError as e:
                self.log(f"reservation report failed: {e}")
            if exists is not None:
                break
        if exists is not None:
            self.log(f"reservation report: {'FOUND' if exists else 'not there'}")
            return exists
        try:
            still_open = await self.site.slot_still_open(self.slot)
        except SiteError:
            still_open = None
        if still_open:
            self.log("report unreadable, but the slot is still open on the grid: not booked")
            return False
        return None

    # ------------------------------------------------------------ the run
    async def run(self) -> RunResult:
        give_up = self.W + self.t.give_up
        if self.clock.now() > give_up:
            return self.result("not_booked", "Not booked: the run started too late for this window.")
        # Wait until the staging lead (the task starts early to absorb DST).
        await self.sleep_until(self.W - clubtime.STAGE_LEAD.total_seconds())
        self.log(f"run for {self.b.name}: {self.b.describe()}")
        stage_deadline = max(self.W - self.t.stage_by, self.clock.now() + 120)
        try:
            await self.login(stage_deadline)
        except SiteError as e:
            return self.result("not_booked", f"Not booked: couldn't sign in ({e}). Book on the club site.")
        try:
            staged = await self.stage_best(stage_deadline if self.rel() < 0 else give_up)
        except SiteError as e:
            staged = False
            self.log(f"staging gave up: {e}")
        if not staged and self.slot is None and self.rel() < 0:
            # Pre-window every free court should show; nothing means nothing to win.
            if not await self._any_open():
                return self.result("not_booked", self._none_open_msg())
        if self.rel() < -self.t.freeze:
            await self.hold()
        return await self.commit_loop(give_up)

    async def _any_open(self) -> bool:
        try:
            return (await self.choose()) is not None
        except SiteError:
            return True  # can't tell: keep trying in the commit loop

    async def commit_loop(self, give_up: float) -> RunResult:
        n = self.t.first_tick
        while self.clock.now() < give_up:
            await self.sleep_until(self.W + n)
            n += 1
            if self.slot is None or not await self._staged():
                if not await self.restage(deadline=give_up):
                    if self.slot is None and not await self._any_open():
                        return self.result("not_booked", self._none_open_msg())
                    await self.clock.sleep(2)
                    continue
            a = await self.site.attempt(self.b.partners)
            rec = {"t": round(self.rel(), 1), "outcome": a.outcome, "detail": a.detail[:120],
                   "court": self.slot.court, "length": self.slot.length}
            self.attempts.append(rec)
            self.log(f"press -> {a.outcome} {a.detail[:100]}")
            if a.outcome == CONFIRMED:
                return await self.confirmed()
            if a.outcome in (NOT_READY, NO_POST):
                continue
            if a.outcome == REJECTED and is_early_rejection(a.detail):
                continue
            if a.outcome == UNKNOWN:
                booked = await self.reconcile()
                if booked:
                    return await self.confirmed(from_report=True)
                if booked is None:
                    return self.result(
                        "unsure",
                        f"Not sure: the club site didn't answer for {self.slot.describe()}. "
                        f"Check your reservations on the club site before booking by hand.")
            # Turned away for another reason, bounced, or not in the report:
            # was the court taken?
            try:
                still_open = await self.site.slot_still_open(self.slot)
            except SiteError:
                still_open = None
            if still_open is False:
                self.tried.add((self.slot.court, self.slot.length))
                self.log(f"{self.slot.describe()} was taken; next choice")
                self.slot = None
        return self.result("not_booked",
                           f"Not booked: the club site didn't accept {clubtime.fmt_time(self.b.time)} "
                           f"{self.occ.day:%a %m/%d} in time. Book on the club site.")

    async def _staged(self) -> bool:
        try:
            return await self.site.is_staged()
        except SiteError:
            return False

    async def confirmed(self, from_report: bool = False) -> RunResult:
        how = " (found in the reservation report)" if from_report else ""
        self.log(f"BOOKED {self.slot.describe()}{how}")
        try:
            gone = await self.site.slot_still_open(self.slot)
            self.log("grid check: court now shows taken" if gone is False
                     else f"grid check: inconclusive ({gone})")
        except SiteError as e:
            self.log(f"grid check failed: {e}")
        return self.result("booked", f"Booked: {self.slot.describe()}")
