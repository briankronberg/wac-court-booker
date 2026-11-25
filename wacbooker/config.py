"""bookings.yaml: load, check, save.

The menu edits the file through ruamel.yaml's round-trip mode, so comments a
person adds by hand survive. `load()` returns both the raw document (for
editing) and a checked `Config`, with every mistake explained in plain words.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from . import clubtime, paths

COURTS = (2, 3, 4, 5, 6, 8, 9, 10)
LENGTHS = (30, 60, 90)
PARTNERS_FOR = {"singles": 1, "doubles": 3}
BROWSERS = ("hidden", "edge", "chrome")
PER_DAY_CAP = 2

TEMPLATE = """\
# WAC Court Booker. Edit with the menu, or by hand if you're comfortable.
# Times are club time (Central). Lengths: 30, 60 or 90 minutes.
#
# browser: hidden (the app's own Chromium, no window), edge or chrome.
# show_window: true shows the Edge/Chrome window (handy to watch a test).
# run_signed_out: true lets bookings run while nobody is signed in to Windows.

browser: hidden
show_window: false
run_signed_out: false

logins: []
#  - nickname: me          # the password is in Windows Credential Manager, not here
#    username: jsmith

bookings: []
#  - name: Tuesday doubles
#    login: me
#    play: doubles          # singles = 1 partner, doubles = 3
#    partners: [Pat Lee, Sam Ortiz, Kim Park]   # names exactly as in your buddy list
#    day: Tuesday           # weekly; or use  date: 2026-12-19  for a one-off
#    time: "6:00 PM"
#    length: 90
#    shorter_ok: true       # if no court has 90, try 60, then 30 (same start time)
#    courts: [5, 4, 3, any] # preference order; 'any' only at the end, optional
#    skip: [2026-12-22, 2026-12-29]
#    active: true
"""


def _yaml() -> YAML:
    y = YAML()  # round-trip
    y.indent(mapping=2, sequence=4, offset=2)
    y.preserve_quotes = True
    y.width = 120
    return y


@dataclass
class Login:
    nickname: str
    username: str


@dataclass
class Booking:
    name: str
    login: str
    play: str
    partners: list[str]
    time: int                    # minutes after midnight
    length: int
    courts: list[Any]            # ints, optionally ending in "any"
    day: int | None = None       # Monday = 0, weekly
    date: date | None = None     # one-off
    shorter_ok: bool = False
    skip: list[date] = field(default_factory=list)
    active: bool = True

    @property
    def lengths(self) -> list[int]:
        """Lengths to try, longest first."""
        out = [self.length]
        if self.shorter_ok:
            out += [x for x in (60, 30) if x < self.length]
        return out

    @property
    def end(self) -> int:
        return self.time + self.length

    def describe(self) -> str:
        when = (clubtime.DAYS[self.day] + "s") if self.day is not None else f"{self.date:%a %m/%d/%Y}"
        courts = ", ".join(str(c) for c in self.courts)
        extra = ", shorter ok" if self.shorter_ok else ""
        return (f"{when} {clubtime.fmt_time(self.time)}, {self.length} min{extra}, "
                f"{self.play} with {', '.join(self.partners)}; courts {courts}; login {self.login}")

    def occurrences(self, after: datetime, count: int = 1) -> list[clubtime.Occurrence]:
        return clubtime.occurrences(self.day, self.date, self.time, after, count)

    def next_runs(self, after: datetime, count: int = 1) -> list[clubtime.Occurrence]:
        """Upcoming occurrences that aren't skipped."""
        out: list[clubtime.Occurrence] = []
        for occ in self.occurrences(after, count + len(self.skip) + 1):
            if occ.day not in self.skip:
                out.append(occ)
            if len(out) >= count:
                break
        return out


@dataclass
class Config:
    browser: str = "hidden"
    show_window: bool = False
    run_signed_out: bool = False
    logins: list[Login] = field(default_factory=list)
    bookings: list[Booking] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def login(self, nickname: str) -> Login | None:
        return next((x for x in self.logins if x.nickname == nickname), None)

    def booking(self, name: str) -> Booking | None:
        return next((b for b in self.bookings if b.name == name), None)


# ---------------------------------------------------------------- reading

def _as_bool(v: Any, what: str, errs: list[str]) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("yes", "true", "on"):
        return True
    if isinstance(v, str) and v.strip().lower() in ("no", "false", "off"):
        return False
    errs.append(f"{what} should be true or false, not '{v}'.")
    return False


def _as_date(v: Any, what: str, errs: list[str]) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v).strip(), "%Y-%m-%d").date()
    except ValueError:
        errs.append(f"{what}: '{v}' isn't a date like 2026-12-19.")
        return None


def parse_booking(raw: Any, idx: int, errs: list[str]) -> Booking | None:
    if not isinstance(raw, dict):
        errs.append(f"Booking {idx}: should be a set of 'key: value' lines.")
        return None
    name = str(raw.get("name") or "").strip()
    label = f"Booking '{name}'" if name else f"Booking {idx}"
    if not name:
        errs.append(f"{label}: needs a name.")
    known = {"name", "login", "play", "partners", "day", "date", "time", "length", "shorter_ok",
             "courts", "skip", "active"}
    for k in raw:
        if k not in known:
            errs.append(f"{label}: '{k}' isn't a setting I know. Check the spelling.")
    before = len(errs)

    login = str(raw.get("login") or "").strip()
    if not login:
        errs.append(f"{label}: say which login books it (login: ...).")

    play = str(raw.get("play") or "").strip().lower()
    if play not in PARTNERS_FOR:
        errs.append(f"{label}: play must be singles or doubles, not '{raw.get('play')}'.")

    partners_raw = raw.get("partners") or []
    if isinstance(partners_raw, str):
        partners_raw = [partners_raw]
    partners = [" ".join(str(p).split()) for p in partners_raw if str(p).strip()]
    if play in PARTNERS_FOR and len(partners) != PARTNERS_FOR[play]:
        n = PARTNERS_FOR[play]
        errs.append(f"{label}: {play} needs {n} partner{'s' if n > 1 else ''}, "
                    f"but {len(partners)} {'is' if len(partners) == 1 else 'are'} listed.")
    if len({p.lower() for p in partners}) != len(partners):
        errs.append(f"{label}: a partner is listed twice.")

    day = one_off = None
    if raw.get("day") is not None and raw.get("date") is not None:
        errs.append(f"{label}: use either day (weekly) or date (one-off), not both.")
    elif raw.get("day") is not None:
        try:
            day = clubtime.parse_day(raw["day"])
        except ValueError as e:
            errs.append(f"{label}: {e}.")
    elif raw.get("date") is not None:
        one_off = _as_date(raw["date"], label, errs)
    else:
        errs.append(f"{label}: needs a day (weekly, e.g. day: Tuesday) or a date (one-off).")

    minutes = 0
    try:
        minutes = clubtime.parse_time(raw.get("time", ""))
        if minutes % 30:
            errs.append(f"{label}: courts start on the hour or half hour, not {raw.get('time')}.")
    except ValueError as e:
        errs.append(f"{label}: {e}.")

    length = raw.get("length")
    try:
        length = int(length)
    except (TypeError, ValueError):
        pass
    if length not in LENGTHS:
        errs.append(f"{label}: length must be 30, 60 or 90 (minutes), not '{raw.get('length')}'.")
        length = 60

    shorter_ok = _as_bool(raw.get("shorter_ok", False), f"{label}: shorter_ok", errs)
    active = _as_bool(raw.get("active", True), f"{label}: active", errs)

    courts_raw = raw.get("courts")
    if isinstance(courts_raw, (str, int)):
        courts_raw = [courts_raw]
    courts: list[Any] = []
    if not courts_raw:
        errs.append(f"{label}: list at least one court, e.g. courts: [5, 4, any].")
    else:
        for i, c in enumerate(courts_raw):
            if str(c).strip().lower() == "any":
                if i != len(courts_raw) - 1:
                    errs.append(f"{label}: 'any' can only come last in the court list.")
                courts.append("any")
                continue
            try:
                n = int(str(c).strip())
            except ValueError:
                errs.append(f"{label}: '{c}' isn't a court number.")
                continue
            if n not in COURTS:
                errs.append(f"{label}: there's no court {n}. Courts are "
                            f"{', '.join(map(str, COURTS))}.")
            elif n in courts:
                errs.append(f"{label}: court {n} is listed twice.")
            else:
                courts.append(n)

    skip_raw = raw.get("skip") or []
    if not isinstance(skip_raw, list):
        skip_raw = [skip_raw]
    skip = [d for d in (_as_date(s, f"{label} skip", errs) for s in skip_raw) if d]

    if len(errs) > before:
        return None
    return Booking(name=name, login=login, play=play, partners=partners, time=minutes,
                   length=length, courts=courts, day=day, date=one_off, shorter_ok=shorter_ok,
                   skip=skip, active=active)


def _days_overlap(a: Booking, b: Booking) -> bool:
    if a.day is not None and b.day is not None:
        return a.day == b.day
    if a.date and b.date:
        return a.date == b.date
    weekly, once = (a, b) if a.day is not None else (b, a)
    return once.date.weekday() == weekly.day and once.date not in weekly.skip


def check(cfg: Config, now: datetime | None = None) -> None:
    """Cross-booking rules. Appends to cfg.errors / cfg.warnings."""
    now = now or clubtime.now_central()
    nick = [x.nickname for x in cfg.logins]
    for n in set(nick):
        if nick.count(n) > 1:
            cfg.errors.append(f"Two logins are called '{n}'. Nicknames must be different.")
    names = [b.name for b in cfg.bookings]
    for n in set(names):
        if names.count(n) > 1:
            cfg.errors.append(f"Two bookings are called '{n}'. Names must be different.")
    for b in cfg.bookings:
        if not cfg.login(b.login):
            cfg.errors.append(f"Booking '{b.name}': there's no login called '{b.login}'.")
    active = [b for b in cfg.bookings if b.active]
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            if a.login != b.login or not _days_overlap(a, b):
                continue
            if a.time < b.end and b.time < a.end:
                cfg.errors.append(f"Bookings '{a.name}' and '{b.name}' overlap on the same login.")
    # The club allows 2 reservations per login per day.
    seen: set[tuple] = set()
    for b in active:
        key = (b.login, b.day, b.date)
        if key in seen:
            continue
        same = [x for x in active if x.login == b.login and _days_overlap(x, b)]
        if len(same) > PER_DAY_CAP:
            seen.add(key)
            when = clubtime.DAYS[b.day] if b.day is not None else f"{b.date:%m/%d/%Y}"
            cfg.warnings.append(
                f"Login '{b.login}' has {len(same)} bookings on {when}; the club allows "
                f"{PER_DAY_CAP} per login per day, so the later ones will be turned away.")
    for b in active:
        if b.date and clubtime.window_open(clubtime.slot_start(b.date, b.time)) < now:
            cfg.warnings.append(f"Booking '{b.name}' ({b.date:%m/%d/%Y}) is past its booking "
                                f"window, so it won't run. Remove it or book on the club site.")


def from_doc(doc: Any) -> Config:
    cfg = Config()
    if doc is None:
        doc = {}
    if not isinstance(doc, dict):
        cfg.errors.append("The file should be a list of 'key: value' settings.")
        return cfg
    for k in doc:
        if k not in ("browser", "show_window", "run_signed_out", "logins", "bookings"):
            cfg.errors.append(f"'{k}' isn't a setting I know. Check the spelling.")
    br = str(doc.get("browser", "hidden")).strip().lower()
    if br not in BROWSERS:
        cfg.errors.append(f"browser must be hidden, edge or chrome, not '{doc.get('browser')}'.")
    else:
        cfg.browser = br
    cfg.show_window = _as_bool(doc.get("show_window", False), "show_window", cfg.errors)
    cfg.run_signed_out = _as_bool(doc.get("run_signed_out", False), "run_signed_out", cfg.errors)
    for i, raw in enumerate(doc.get("logins") or [], 1):
        if not isinstance(raw, dict) or not raw.get("nickname") or not raw.get("username"):
            cfg.errors.append(f"Login {i}: needs a nickname and a username.")
            continue
        cfg.logins.append(Login(str(raw["nickname"]).strip(), str(raw["username"]).strip()))
    for i, raw in enumerate(doc.get("bookings") or [], 1):
        b = parse_booking(raw, i, cfg.errors)
        if b:
            cfg.bookings.append(b)
    if cfg.ok:
        check(cfg)
    return cfg


def load(path: Path | None = None) -> tuple[Any, Config]:
    """(raw document, checked Config). A missing file loads the template."""
    path = path or paths.config_file()
    text = path.read_text(encoding="utf-8") if path.exists() else TEMPLATE
    try:
        doc = _yaml().load(text)
    except Exception as e:  # noqa: BLE001 -- any YAML syntax error
        cfg = Config()
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark else ""
        cfg.errors.append(f"bookings.yaml can't be read{where}: {getattr(e, 'problem', e)}. "
                          f"Check the indentation and colons there.")
        return None, cfg
    if doc is None:
        doc = _yaml().load(TEMPLATE)
    return doc, from_doc(doc)


def dump(doc: Any) -> str:
    buf = io.StringIO()
    _yaml().dump(doc, buf)
    return buf.getvalue()


def save(doc: Any, path: Path | None = None) -> None:
    path = path or paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(dump(doc), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- editing

def _seq(doc: Any, key: str) -> CommentedSeq:
    cur = doc.get(key)
    if not isinstance(cur, list):
        cur = CommentedSeq()
        doc[key] = cur
    return cur


def auto_name(play: str, partners: list[str], day: int | None, one_off: date | None, minutes: int,
              taken: list[str] = ()) -> str:
    """A booking's name, made from what it books: 'Tue 6:00 PM singles with Andrea', or
    'Sat 12/19 6:00 PM doubles with Pat, Sam, Kim' for a one-off. Partners by first name.
    Gets ' (2)', ' (3)' ... if another booking already has that name."""
    when = clubtime.DAYS[day][:3] if day is not None else (
        f"{one_off:%a} {one_off.month}/{one_off.day}" if one_off else "")
    firsts = [p.split()[0] for p in partners if p.split()]
    base = " ".join(x for x in (when, clubtime.fmt_time(minutes), play) if x)
    if firsts:
        base += " with " + ", ".join(firsts)
    used = {t.lower() for t in taken}
    name, n = base, 2
    while name.lower() in used:
        name, n = f"{base} ({n})", n + 1
    return name


def booking_to_map(b: Booking) -> CommentedMap:
    m = CommentedMap()
    m["name"] = b.name
    m["login"] = b.login
    m["play"] = b.play
    m["partners"] = _flow(b.partners)
    if b.day is not None:
        m["day"] = clubtime.DAYS[b.day]
    else:
        m["date"] = b.date
    m["time"] = clubtime.fmt_time(b.time)
    m["length"] = b.length
    m["shorter_ok"] = b.shorter_ok
    m["courts"] = _flow(b.courts)
    m["skip"] = _flow(sorted(b.skip))
    m["active"] = b.active
    return m


def _flow(items: list) -> CommentedSeq:
    s = CommentedSeq(items)
    s.fa.set_flow_style()
    return s


def put_booking(doc: Any, b: Booking, replace: str | None = None) -> None:
    """Add booking `b`, or replace the one called `replace` in place."""
    seq = _seq(doc, "bookings")
    new = booking_to_map(b)
    if replace is not None:
        for i, raw in enumerate(seq):
            if isinstance(raw, dict) and str(raw.get("name", "")).strip() == replace:
                for k in list(raw.keys()):
                    if k not in new:
                        del raw[k]
                for k, v in new.items():
                    raw[k] = v
                return
    seq.append(new)


def remove_booking(doc: Any, name: str) -> bool:
    seq = _seq(doc, "bookings")
    for i, raw in enumerate(seq):
        if isinstance(raw, dict) and str(raw.get("name", "")).strip() == name:
            del seq[i]
            return True
    return False


def put_login(doc: Any, login: Login) -> None:
    seq = _seq(doc, "logins")
    for raw in seq:
        if isinstance(raw, dict) and raw.get("nickname") == login.nickname:
            raw["username"] = login.username
            return
    m = CommentedMap()
    m["nickname"] = login.nickname
    m["username"] = login.username
    seq.append(m)


def remove_login(doc: Any, nickname: str) -> bool:
    seq = _seq(doc, "logins")
    for i, raw in enumerate(seq):
        if isinstance(raw, dict) and raw.get("nickname") == nickname:
            del seq[i]
            return True
    return False


def set_setting(doc: Any, key: str, value: Any) -> None:
    doc[key] = value


def prune_skips(b: Booking, today: date) -> list[date]:
    """Skip dates that are still ahead (old ones can be dropped)."""
    return [d for d in b.skip if d >= today - timedelta(days=1)]
