"""Club time (Central), booking windows and run times.

A slot opens exactly 169 hours before it starts (window W). The arithmetic is
done in UTC so a daylight-saving change inside that week doesn't shift W.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
OPEN_LEAD = timedelta(hours=169)
# The scheduled task starts this long before W. It's 75 minutes, not 15, so a
# weekly trigger (fixed local clock time) is still early in the weeks where
# daylight saving moves W by an hour. The run then waits until STAGE_LEAD.
TASK_LEAD = timedelta(minutes=75)
STAGE_LEAD = timedelta(minutes=15)
# A run looks for a window in [now - LATE_OK, now + EARLY_OK].
LATE_OK = timedelta(minutes=4)
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


def slot_start(d: date, minutes: int) -> datetime:
    return datetime.combine(d, time(minutes // 60, minutes % 60), tzinfo=CENTRAL)


def window_open(start: datetime) -> datetime:
    """W = start - 169 h, in absolute time (never wall-clock arithmetic)."""
    return (start.astimezone(timezone.utc) - OPEN_LEAD).astimezone(CENTRAL)


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
                after: datetime, count: int = 1) -> list[Occurrence]:
    """The next `count` occurrences whose window W is at or after `after`."""
    out: list[Occurrence] = []
    if one_off is not None:
        st = slot_start(one_off, minutes)
        w = window_open(st)
        if w >= after:
            out.append(Occurrence(one_off, st, w))
        return out
    if weekday is None:
        return out
    d = after.astimezone(CENTRAL).date()
    d += timedelta(days=(weekday - d.weekday()) % 7)
    while len(out) < count:
        st = slot_start(d, minutes)
        w = window_open(st)
        if w >= after:
            out.append(Occurrence(d, st, w))
        d += timedelta(days=7)
    return out


def due_occurrence(weekday: int | None, one_off: date | None, minutes: int,
                   now: datetime) -> Occurrence | None:
    """The occurrence a run started at `now` should book: W within
    [now - LATE_OK, now + EARLY_OK]."""
    for occ in occurrences(weekday, one_off, minutes, now - LATE_OK, count=2):
        if occ.window <= now + EARLY_OK:
            return occ
    return None
