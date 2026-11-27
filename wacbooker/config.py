"""bookings.yaml: load, check, save.

The menu edits the file through ruamel.yaml's round-trip mode, so comments a
person adds by hand survive. `load()` returns both the raw document (for
editing) and a checked `Config`, with every mistake explained in plain words.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from . import clubtime, paths

COURTS = (2, 3, 4, 5, 6, 8, 9, 10)
LENGTHS = (30, 60, 90)
PARTNERS_FOR = {"singles": 1, "doubles": 3, "machine": 0}
# Ball machines: which one to book. "either" tries the Genie first (it works with a
# phone app), then the regular one.
MACHINES = ("genie", "regular", "either")
MACHINE_TEXT = {"genie": "Genie ball machine", "regular": "regular ball machine",
                "either": "ball machine (Genie first)"}
MACHINE_COURTS = (2, 3, 8, 9, 10)  # the courts a ball machine goes on
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
#    then: 60               # a second session right after the first (30, 60 or 90 minutes)
#    blocker: true          # a short guard court right before the first session, cancelled once it's booked
#    courts: [5, 4, 3, any] # preference order; 'any' only at the end, optional
#    skip: [2026-12-22, 2026-12-29]
#  A ball machine:  play: machine,  machine: genie (or regular, or either),  partners: []
#  (courts 2, 3, 8, 9 and 10 take a ball machine)
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


@dataclass(frozen=True)
class Part:
    """What one scheduled run books. Most bookings are one part ("main"). A singles
    booking that runs into or out of Prime Time is two: the regular hours ("main",
    1 week and 1 hour ahead) and the Prime Time hours ("prime", 24 hours ahead)."""
    key: str
    time: int
    length: int
    prime: bool

    @property
    def lead(self) -> timedelta:
        return clubtime.PRIME_LEAD if self.prime else clubtime.OPEN_LEAD


@dataclass
class Member:
    """One login in a booking and the partners it books with. A booking's first member
    is its own `login` and `partners`; `also` adds more logins that book at the same
    time, each on its own court, side by side when the courts allow."""
    login: str
    partners: list[str]


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
    then: int = 0                # a second session right after the first: 30, 60 or 90 minutes
    blocker: bool = False        # a guard slot right before the main part, cancelled once it's booked
    skip: list[date] = field(default_factory=list)
    active: bool = True
    machine: str | None = None   # play: machine only
    also: list[Member] = field(default_factory=list)  # more logins booking together

    @property
    def members(self) -> list[Member]:
        """Every login this booking books for, its own login first."""
        return [Member(self.login, list(self.partners))] + list(self.also)

    def for_member(self, m: Member) -> "Booking":
        """This booking as one login books it."""
        return replace(self, login=m.login, partners=list(m.partners), also=[])

    @property
    def what(self) -> str:
        """'Singles', 'Doubles' or 'Genie ball machine'..., for people."""
        if self.play == "machine":
            t = MACHINE_TEXT.get(self.machine or "either", "ball machine")
            return t[0].upper() + t[1:]
        return self.play.capitalize()

    @property
    def site_play(self) -> str:
        """What the club site books: 'singles', 'doubles' or 'machine:<which>'."""
        return f"machine:{self.machine or 'either'}" if self.play == "machine" else self.play

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

    @property
    def span_end(self) -> int:
        """When the whole booking is over (with a second session, its end)."""
        return self.end + self.then

    @property
    def reservations(self) -> int:
        """How many reservations each login gets on the day (the club allows 2).
        A blocker is a guard slot cancelled in the same session, so it doesn't count."""
        return sum(1 for p in self.parts if p.key != "blocker")

    @property
    def weekday(self) -> int | None:
        return self.day if self.day is not None else (self.date.weekday() if self.date else None)

    @property
    def parts(self) -> list[Part]:
        """Prime Time limits singles and ball machines; doubles is always one part.
        A blocker is one more part ("blocker"), the hour before the main part's start.
        A second session (`then`) is one more part ("next"), right after the first."""
        if self.play not in ("singles", "machine") or self.weekday is None:
            out = [Part("main", self.time, self.length, False)]
        else:
            pieces = clubtime.split_prime(self.weekday, self.time, self.length)
            if len(pieces) == 1:
                out = [Part("main", self.time, self.length, pieces[0].prime)]
            else:
                regular = next(p for p in pieces if not p.prime)
                prime = next(p for p in pieces if p.prime)
                out = [Part("main", regular.start, regular.length, False),
                       Part("prime", prime.start, prime.length, True)]
        if self.blocker and not out[0].prime:
            out.insert(0, Part("blocker", out[0].time - 60, 60, False))
        if self.then:
            prime = False
            if self.play in ("singles", "machine") and self.weekday is not None:
                prime = clubtime.split_prime(self.weekday, self.end, self.then)[0].prime
            out.append(Part("next", self.end, self.then, prime))
        return out

    @property
    def prime_kind(self) -> str:
        """'none', 'all' (books 24 hours ahead) or 'split' (crosses Prime Time)."""
        ps = self.parts
        if all(p.prime for p in ps):
            return "all"
        if any(p.prime for p in ps):
            return "split"
        return "none"

    def part(self, key: str = "main") -> Part:
        return next(p for p in self.parts if p.key == key)

    def for_part(self, key: str = "main") -> "Booking":
        """This booking cut down to one part, for the engine."""
        p = self.part(key)
        return replace(self, time=p.time, length=p.length)

    def describe(self) -> str:
        when = (clubtime.DAYS[self.day] + "s") if self.day is not None else f"{self.date:%a %m/%d/%Y}"
        courts = ", ".join(str(c) for c in self.courts)
        extra = ", shorter ok" if self.shorter_ok else ""
        who = f" with {', '.join(self.partners)}" if self.partners else ""
        more = "".join(f"; also login {m.login}" + (f" with {', '.join(m.partners)}" if m.partners else "")
                       for m in self.also)
        return (f"{when} {clubtime.fmt_time(self.time)}, {self.length} min{extra}, "
                f"{self.what.lower() if self.play != 'machine' else self.what}{who}; courts {courts}; "
                f"login {self.login}{more}")

    def occurrences(self, after: datetime, count: int = 1, part: str = "main") -> list[clubtime.Occurrence]:
        p = self.part(part)
        return clubtime.occurrences(self.day, self.date, p.time, after, count, lead=p.lead)

    def due(self, now: datetime, part: str = "main") -> clubtime.Occurrence | None:
        p = self.part(part)
        return clubtime.due_occurrence(self.day, self.date, p.time, now, lead=p.lead)

    def next_runs(self, after: datetime, count: int = 1, part: str = "main") -> list[clubtime.Occurrence]:
        """Upcoming occurrences that aren't skipped."""
        out: list[clubtime.Occurrence] = []
        for occ in self.occurrences(after, count + len(self.skip) + 1, part):
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
             "courts", "skip", "active", "machine", "also", "then", "blocker"}
    for k in raw:
        if k not in known:
            errs.append(f"{label}: '{k}' isn't a setting I know. Check the spelling.")
    before = len(errs)

    login = str(raw.get("login") or "").strip()
    if not login:
        errs.append(f"{label}: say which login books it (login: ...).")

    play = str(raw.get("play") or "").strip().lower()
    if play in ("ball machine", "ball_machine", "ballmachine"):
        play = "machine"
    if play not in PARTNERS_FOR:
        errs.append(f"{label}: play must be singles, doubles or machine, not '{raw.get('play')}'.")
    machine = None
    if play == "machine":
        machine = str(raw.get("machine") or "either").strip().lower()
        if machine not in MACHINES:
            errs.append(f"{label}: machine must be genie, regular or either, not '{raw.get('machine')}'.")
    elif raw.get("machine") is not None:
        errs.append(f"{label}: 'machine' is only for play: machine.")

    partners_raw = raw.get("partners") or []
    if isinstance(partners_raw, str):
        partners_raw = [partners_raw]
    partners = [" ".join(str(p).split()) for p in partners_raw if str(p).strip()]
    if play == "machine" and partners:
        errs.append(f"{label}: a ball machine booking is just you; leave partners empty.")
    elif play in PARTNERS_FOR and len(partners) != PARTNERS_FOR[play]:
        n = PARTNERS_FOR[play]
        errs.append(f"{label}: {play} needs {n} partner{'s' if n > 1 else ''}, "
                    f"but {len(partners)} {'is' if len(partners) == 1 else 'are'} listed.")
    if len({p.lower() for p in partners}) != len(partners):
        errs.append(f"{label}: a partner is listed twice.")

    also: list[Member] = []
    also_raw = raw.get("also") or []
    if isinstance(also_raw, dict):
        also_raw = [also_raw]
    if not isinstance(also_raw, list):
        errs.append(f"{label}: 'also' should be a list of logins, each with its partners.")
        also_raw = []
    if also_raw and play == "machine":
        errs.append(f"{label}: a ball machine booking is for one login; take 'also' out.")
        also_raw = []
    for j, a in enumerate(also_raw, 1):
        if not isinstance(a, dict) or not str(a.get("login") or "").strip():
            errs.append(f"{label}: 'also' entry {j} needs a login.")
            continue
        for k in a:
            if k not in ("login", "partners"):
                errs.append(f"{label}: 'also' entry {j}: '{k}' isn't a setting I know.")
        ap = a.get("partners") or []
        if isinstance(ap, str):
            ap = [ap]
        ap = [" ".join(str(p).split()) for p in ap if str(p).strip()]
        al = str(a["login"]).strip()
        if play in PARTNERS_FOR and len(ap) != PARTNERS_FOR[play]:
            n = PARTNERS_FOR[play]
            errs.append(f"{label}: login '{al}' plays {play} too, so it needs {n} partner{'s' if n > 1 else ''}, "
                        f"but {len(ap)} {'is' if len(ap) == 1 else 'are'} listed.")
        also.append(Member(al, ap))
    logins_in = [login] + [m.login for m in also]
    if len({x.lower() for x in logins_in}) != len(logins_in):
        errs.append(f"{label}: a login is listed twice. Each login books its own court once.")
    people = [p.lower() for p in partners] + [p.lower() for m in also for p in m.partners]
    if len(set(people)) != len(people):
        errs.append(f"{label}: someone is a partner for two logins. Each person can be on one court only.")

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
    blocker = _as_bool(raw.get("blocker", False), f"{label}: blocker", errs)

    then = raw.get("then", 0)
    if then is None:
        then = 0
    try:
        then = int(then)
    except (TypeError, ValueError):
        then = -1
    if then not in (0, 30, 60, 90):
        errs.append(f"{label}: 'then' is 30, 60 or 90 minutes right after the first session "
                    f"(leave it out to turn it off), not '{raw.get('then')}'.")
        then = 0

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
            elif play == "machine" and n not in MACHINE_COURTS:
                errs.append(f"{label}: court {n} doesn't take a ball machine. Those courts are "
                            f"{', '.join(map(str, MACHINE_COURTS))}.")
            elif n in courts:
                errs.append(f"{label}: court {n} is listed twice.")
            else:
                courts.append(n)

    skip_raw = raw.get("skip") or []
    if not isinstance(skip_raw, list):
        skip_raw = [skip_raw]
    skip = [d for d in (_as_date(s, f"{label} skip", errs) for s in skip_raw) if d]

    if then:
        if minutes + length + then >= 1440:
            errs.append(f"{label}: with a second session, the booking would run past midnight. "
                        f"Pick an earlier time or a shorter session.")
        weekday = day if day is not None else (one_off.weekday() if one_off else None)
        if weekday is not None and play in ("singles", "machine"):
            for start, ln, which in ((minutes, length, "the first session"),
                                     (minutes + length, then, "the second session")):
                if len(clubtime.split_prime(weekday, start, ln)) > 1:
                    errs.append(f"{label}: {which} would run into Prime Time, and back-to-back "
                                f"sessions can't be split. Pick a time that stays out of Prime Time.")

    if len(errs) > before:
        return None
    weekday = day if day is not None else (one_off.weekday() if one_off else None)
    if blocker and play in ("singles", "machine") and weekday is not None \
            and len(pieces := clubtime.split_prime(weekday, minutes, length)) == 1 and pieces[0].prime:
        errs.append(f"{label}: a blocker can't protect a Prime Time start: "
                    f"{clubtime.fmt_time(minutes)} books 24 hours ahead, not a week ahead. "
                    "Choose a time outside Prime Time, or turn the blocker off.")
        blocker = False
    if len(errs) > before:
        return None
    return Booking(name=name, login=login, play=play, partners=partners, time=minutes,
                   length=length, courts=courts, day=day, date=one_off, shorter_ok=shorter_ok,
                   then=then, blocker=blocker, skip=skip, active=active, machine=machine, also=also)


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
        for m in b.members:
            if not cfg.login(m.login):
                cfg.errors.append(f"Booking '{b.name}': there's no login called '{m.login}'.")
    active = [b for b in cfg.bookings if b.active]

    def logins_of(x: Booking) -> set[str]:
        return {m.login for m in x.members}
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            shared = logins_of(a) & logins_of(b)
            if not shared or not _days_overlap(a, b):
                continue
            if a.time < b.span_end and b.time < a.span_end:
                cfg.errors.append(f"Bookings '{a.name}' and '{b.name}' overlap on the same login "
                                  f"('{sorted(shared)[0]}').")
    # The club allows 2 reservations per login per day.
    seen: set[tuple] = set()
    for b in active:
        for lg in sorted(logins_of(b)):
            key = (lg, b.day, b.date)
            if key in seen:
                continue
            same = [x for x in active if lg in logins_of(x) and _days_overlap(x, b)]
            # A booking split at Prime Time, or with a second session, makes two reservations.
            n = sum(x.reservations for x in same)
            if n > PER_DAY_CAP:
                seen.add(key)
                when = clubtime.DAYS[b.day] if b.day is not None else f"{b.date:%m/%d/%Y}"
                cfg.warnings.append(
                    f"Login '{lg}' has {n} reservations on {when}; the club allows {PER_DAY_CAP} "
                    f"per login per day, so the later ones will be turned away.")
    for b in active:
        if b.date and not b.next_runs(now - clubtime.LATE_OK, 1):
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
              taken: list[str] = (), machine: str | None = None) -> str:
    """A booking's name, made from what it books: 'Tue 6:00 PM singles with Andrea', or
    'Sat 12/19 6:00 PM doubles with Pat, Sam, Kim' for a one-off. Partners by first name.
    Gets ' (2)', ' (3)' ... if another booking already has that name."""
    when = clubtime.DAYS[day][:3] if day is not None else (
        f"{one_off:%a} {one_off.month}/{one_off.day}" if one_off else "")
    firsts = [p.split()[0] for p in partners if p.split()]
    what = MACHINE_TEXT.get(machine or "either", "ball machine") if play == "machine" else play
    if play == "machine" and what.startswith("ball machine"):
        what = "ball machine"
    base = " ".join(x for x in (when, clubtime.fmt_time(minutes), what) if x)
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
    if b.play == "machine":
        m["machine"] = b.machine or "either"
    m["partners"] = _flow(b.partners)
    if b.also:
        seq = CommentedSeq()
        for x in b.also:
            e = CommentedMap()
            e["login"] = x.login
            e["partners"] = _flow(x.partners)
            seq.append(e)
        m["also"] = seq
    if b.day is not None:
        m["day"] = clubtime.DAYS[b.day]
    else:
        m["date"] = b.date
    m["time"] = clubtime.fmt_time(b.time)
    m["length"] = b.length
    m["shorter_ok"] = b.shorter_ok
    if b.then:
        m["then"] = b.then
    if b.blocker:
        m["blocker"] = True
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
