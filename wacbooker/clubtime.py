"""Club time (Central), booking windows and run times.

A slot opens exactly 169 hours before it starts (window W). The arithmetic is
done in UTC so a daylight-saving change inside that week doesn't shift W.

Prime Time (the club's tennis FAQ): Monday-Friday 9:00-10:30 AM and
Monday-Thursday 5:00-8:00 PM. Singles in those hours can only be booked 24 hours
ahead; doubles still book 1 week and 1 hour ahead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
OPEN_LEAD = timedelta(hours=169)
PRIME_LEAD = timedelta(hours=24)
# (weekdays, start, end) in minutes after midnight; Monday = 0.
PRIME_TIME = (((0, 1, 2, 3, 4), 9 * 60, 10 * 60 + 30), ((0, 1, 2, 3), 17 * 60, 20 * 60))
PRIME_TEXT = "Monday-Friday 9:00-10:30 AM and Monday-Thursday 5:00-8:00 PM"
# The scheduled task starts this long before W. It's 75 minutes, not 15, so a
# weekly trigger (fixed local clock time) is still early in the weeks where
# daylight saving moves W by an hour. The run then waits until STAGE_LEAD.
TASK_LEAD = timedelta(minutes=75)
STAGE_LEAD = timedelta(minutes=15)
# A run looks for a window in [now - LATE_OK, now + EARLY_OK]. A run that starts late
# (the PC was off or asleep) still books whatever is open, up to 20 minutes after W.
LATE_OK = timedelta(minutes=20)
EARLY_OK = timedelta(hours=3)

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_TIME_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?\s*[Mm]?\.?\s*$")
_TIME24_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")


def parse_time(text: str) -> int:
    """'6:00 PM', '6 pm', '18:00' -> minutes after midnight. Raises ValueError."""
    s = str(text).strip()
    m = _TIME_RE.match(s)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
        if not 1 <= h <= 12 or mi > 59:
            raise ValueError(f"'{text}' isn't a time")
        h = h % 12 + (12 if ap == "p" else 0)
        return h * 60 + mi
    m = _TIME24_RE.match(s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            raise ValueError(f"'{text}' isn't a time")
        return h * 60 + mi
    raise ValueError(f"'{text}' isn't a time like 6:00 PM")


def fmt_time(minutes: int) -> str:
    h, mi = divmod(int(minutes), 60)
    return f"{(h % 12) or 12}:{mi:02d} {'AM' if h < 12 else 'PM'}"


def parse_day(text: str) -> int:
    """'Tuesday', 'tue' -> 1 (Monday = 0)."""
    s = str(text).strip().lower()
    for i, d in enumerate(DAYS):
        if len(s) >= 3 and d.lower().startswith(s):
            return i
    raise ValueError(f"'{text}' isn't a day of the week")


@dataclass(frozen=True)
class Piece:
    """Part of a booked span: all inside Prime Time or all outside it."""
    start: int
    length: int
    prime: bool


def prime_spans(weekday: int) -> list[tuple[int, int]]:
    return [(a, z) for days, a, z in PRIME_TIME if weekday in days]


def split_prime(weekday: int, start: int, length: int) -> list[Piece]:
    """The span cut where it enters or leaves Prime Time, in time order."""
    cuts = {start, start + length}
    for a, z in prime_spans(weekday):
        cuts |= {c for c in (a, z) if start < c < start + length}
    edges = sorted(cuts)
    out: list[Piece] = []
    for a, z in zip(edges, edges[1:]):
        prime = any(pa <= a and z <= pz for pa, pz in prime_spans(weekday))
        if out and out[-1].prime == prime:
            out[-1] = Piece(out[-1].start, z - out[-1].start, prime)
        else:
            out.append(Piece(a, z - a, prime))
    return out


def slot_start(d: date, minutes: int) -> datetime:
    return datetime.combine(d, time(minutes // 60, minutes % 60), tzinfo=CENTRAL)


def window_open(start: datetime, lead: timedelta = OPEN_LEAD) -> datetime:
    """W = start - 169 h (or 24 h), in absolute time (never wall-clock arithmetic)."""
    return (start.astimezone(timezone.utc) - lead).astimezone(CENTRAL)


def now_central() -> datetime:
    return datetime.now(timezone.utc).astimezone(CENTRAL)


def fmt_when(dt: datetime) -> str:
    """'Tue 12/15 6:00 PM' in club time."""
    c = dt.astimezone(CENTRAL)
    return f"{c:%a} {c.month}/{c.day} {fmt_time(c.hour * 60 + c.minute)}"


@dataclass(frozen=True)
class Occurrence:
    """One concrete play date of a booking."""
    day: date
    start: datetime   # slot start, Central
    window: datetime  # W, Central

    @property
    def run_at(self) -> datetime:
        return self.window - TASK_LEAD


def occurrences(weekday: int | None, one_off: date | None, minutes: int,
                after: datetime, count: int = 1, lead: timedelta = OPEN_LEAD) -> list[Occurrence]:
    """The next `count` occurrences whose window W is at or after `after`."""
    out: list[Occurrence] = []
    if one_off is not None:
        st = slot_start(one_off, minutes)
        w = window_open(st, lead)
        if w >= after:
            out.append(Occurrence(one_off, st, w))
        return out
    if weekday is None:
        return out
    d = after.astimezone(CENTRAL).date()
    d += timedelta(days=(weekday - d.weekday()) % 7)
    while len(out) < count:
        st = slot_start(d, minutes)
        w = window_open(st, lead)
        if w >= after:
            out.append(Occurrence(d, st, w))
        d += timedelta(days=7)
    return out


def due_occurrence(weekday: int | None, one_off: date | None, minutes: int,
                   now: datetime, lead: timedelta = OPEN_LEAD) -> Occurrence | None:
    """The occurrence a run started at `now` should book: W within
    [now - LATE_OK, now + EARLY_OK]."""
    for occ in occurrences(weekday, one_off, minutes, now - LATE_OK, count=2, lead=lead):
        if occ.window <= now + EARLY_OK:
            return occ
    return None
