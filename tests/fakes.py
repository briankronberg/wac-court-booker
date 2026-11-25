"""Offline stand-ins for the club site and the clock."""
from __future__ import annotations

from datetime import date

from wacbooker import clubtime, engine
from wacbooker.config import Booking
from wacbooker.engine import Attempt, Slot, SiteError


class FakeClock:
    def __init__(self, t: float):
        self.t = t
        self.slept = 0.0

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self.t += seconds
            self.slept += seconds


class FakeSite:
    """A club site with a commit gate at W + gate_s.

    open_courts: {length: [courts]} free before W.
    taken_at: {(court, length): rel_s} someone else books it at W + rel_s.
    unknown_on: set of press numbers (1-based) that get no answer.
    report: what the reservation report says after an unanswered press
            (True / False / None = unreadable).
    """

    def __init__(self, clock: FakeClock, W: float, *, gate_s: float = 44.0,
                 open_courts: dict[int, list[int]] | None = None, taken_at=None,
                 answer_s: float = 2.0, unknown_on=(), report=None, grid_after_unknown=None,
                 stage_glitches: int = 0, login_fails: int = 0, bad_password: bool = False):
        self.clock = clock
        self.W = W
        self.gate_s = gate_s
        self.open_courts = open_courts or {90: [3, 4, 5], 60: [3, 4, 5], 30: [3, 4, 5]}
        self.taken_at = dict(taken_at or {})
        self.answer_s = answer_s
        self.unknown_on = set(unknown_on)
        self.report = report
        self.grid_after_unknown = grid_after_unknown
        self.stage_glitches = stage_glitches
        self.login_fails = login_fails
        self.bad_password = bad_password
        self.staged: Slot | None = None
        self.presses = 0
        self.press_times: list[float] = []
        self.booked: list[Slot] = []
        self.calls: list[str] = []
        self.pending_unknown = False

    def rel(self) -> float:
        return self.clock.now() - self.W

    def _is_open(self, court: int, length: int) -> bool:
        if court not in self.open_courts.get(length, []):
            return False
        t = self.taken_at.get((court, length))
        if t is not None and self.rel() >= t:
            return False
        return not any(s.court == court for s in self.booked)

    async def login(self) -> str:
        self.calls.append("login")
        await self.clock.sleep(5)
        if self.bad_password:
            raise SiteError("the club site says the username or password is wrong", "login")
        if self.login_fails > 0:
            self.login_fails -= 1
            raise SiteError("login page didn't load")
        return "Test Member"

    async def find_open(self, date, start, lengths, play):
        self.calls.append("find_open")
        await self.clock.sleep(3)
        return {L: {c: Slot(date, start, L, c) for c in self.open_courts.get(L, [])
                    if self._is_open(c, L)} for L in lengths}

    async def stage(self, slot: Slot) -> None:
        self.calls.append(f"stage:{slot.court}/{slot.length}")
        await self.clock.sleep(10)
        if self.stage_glitches > 0:
            self.stage_glitches -= 1
            raise SiteError("participants page never loaded")
        if not self._is_open(slot.court, slot.length):
            raise SiteError("not in grid", "taken")
        self.staged = slot

    async def keepalive(self) -> None:
        self.calls.append("keepalive")
        await self.clock.sleep(2)

    async def is_staged(self) -> bool:
        return self.staged is not None

    async def attempt(self, partners) -> Attempt:
        assert not self.pending_unknown, "pressed again over an unanswered commit"
        self.presses += 1
        self.press_times.append(self.rel())
        slot = self.staged
        await self.clock.sleep(self.answer_s)
        if self.presses in self.unknown_on:
            self.pending_unknown = True
            if self.report is True:
                self.booked.append(slot)
            return Attempt(engine.UNKNOWN)
        if self.rel() < self.gate_s:
            return Attempt(engine.REJECTED, "None of the listed individuals are eligible for enrollment.")
        if not self._is_open(slot.court, slot.length):
            self.staged = None
            return Attempt(engine.REJECTED, "This time slot is no longer available.")
        self.booked.append(slot)
        return Attempt(engine.CONFIRMED, "guid-1")

    async def reservation_exists(self, slot):
        self.calls.append("report")
        self.pending_unknown = False
        await self.clock.sleep(5)
        return self.report

    async def release(self) -> None:
        self.calls.append("release")
        self.staged = None

    async def slot_still_open(self, slot):
        self.calls.append("grid")
        self.pending_unknown = False
        await self.clock.sleep(3)
        if self.grid_after_unknown is not None and self.report is None:
            return self.grid_after_unknown
        return self._is_open(slot.court, slot.length)


def booking(**kw) -> Booking:
    base = dict(name="Tue doubles", login="me", play="doubles",
                partners=["Pat Lee", "Sam Ortiz", "Kim Park"], time=18 * 60, length=90,
                courts=[5, 4, 3, "any"], day=1, shorter_ok=True)
    base.update(kw)
    return Booking(**base)


def occurrence(d: date = date(2026, 12, 15), minutes: int = 18 * 60) -> clubtime.Occurrence:
    st = clubtime.slot_start(d, minutes)
    return clubtime.Occurrence(d, st, clubtime.window_open(st))
