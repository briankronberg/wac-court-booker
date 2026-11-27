"""The club site (Spectrum NG, WAC Hartland), driven with Playwright.

Selectors and flows come from the author's working system, where they were
proven on real booking mornings:
- login form fields and the "Welcome, <name> (<member #>)" line;
- the court grid (BookSchedule.aspx) and its time-of-day search, because the
  default view lists only the first few start times of the day;
- slot links matched on start, end and resource id (each row is duplicated in
  the page, so only the first match is clicked);
- the "Booking Details" dialog, then the participants page
  (AddFamilyMembersScheduler.aspx) where host and partner rows are ticked;
- "Continue to Cart" (the commit), the confirmation page
  (CurrentScheduleDetail.aspx) and the Reservation Report.

The password is fetched only when the login form needs it and is scrubbed
from every log line.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import Callable

from . import clubtime, paths
from .engine import (CONFIRMED, NO_POST, NOT_READY, OFFPAGE, REJECTED, UNKNOWN, Attempt, SiteError,
                     Slot)


def why(e: BaseException, n: int = 120) -> str:
    """First line of an error, never empty: a timeout's message is often blank, and
    an empty message once broke the error handling itself ("list index out of range")."""
    for line in str(e).splitlines():
        if line.strip():
            return line.strip()[:n]
    return "timed out" if isinstance(e, (asyncio.TimeoutError, TimeoutError)) else type(e).__name__


BASE ="https://hnd-p-ols.spectrumng.net/LCRAC"
LOGIN_URL = BASE + "/Login.aspx"
HOME_URL = BASE + "/Home.aspx"
BUDDY_URL = BASE + "/Members/Buddy/MemberBuddy.aspx?isKiosk=False&pname=Account%20Information@My%20Buddy%20List&pid=ACI,ABD"
REPORT_URL = (BASE + "/Members/Reports/ReservationReport.aspx"
              "?isKiosk=False&pname=Account%20Information@Reservation%20Report&pid=ACI,ARR")
GRID_URL = (BASE + "/Members/Scheduler/BookSchedule.aspx?siteid=758"
            "&catid=12da3b14-effb-4a17-8a40-3e3aac6de380&provid=0&serviceid={svc}&d={d}&du={du}")

# Services on the Tennis Courts page. Evening singles use "Primetime Singles",
# so singles looks in both and uses whichever lists the requested start.
SERVICES = {
    "doubles": [("1 Doubles", "a9c0c426-cfe9-458e-b598-8be39e874b09")],
    "singles": [("2 Singles", "6c670067-2e76-40ab-bff1-b37ab0ee6fb3"),
                ("3.1 Primetime Singles", "3b39d597-4202-4680-9120-73d3080a5201")],
}
RESOURCE_TO_COURT = {"1": 2, "92": 3, "93": 4, "94": 5, "95": 6, "96": 8, "97": 9, "98": 10}
COURT_TO_RESOURCE = {c: r for r, c in RESOURCE_TO_COURT.items()}
COURT_WORDS = {10: "ten"}

# The court sheet itself is built in the browser from the club's JSON web service
# (Library/OlsService.asmx). Reading it directly takes one call per day instead of
# paging through the list 15 rows at a time.
SITE_ID = "758"
API_PATH = "/LCRAC/Library/OlsService.asmx/"
DAY_MINUTES = 1440
FIRST_START, LAST_END = 5 * 60, 22 * 60  # the club's tennis hours

# Ball machines are "providers" on their own services, and only go on some courts.
# Prime Time has its own services, like singles.
MACHINES = {
    "genie": {"label": "Genie ball machine", "short": "Genie", "provider": "442",
              "services": [("3.01 Genie Ball Machine", "8f3e617f-fe3a-496b-8203-75c5dc6b4c93"),
                           ("3.22 Primetime Genie Ball Machine", "cad5296f-bcf2-415b-98b7-c8d4cc025f97")]},
    "regular": {"label": "regular ball machine", "short": "Regular", "provider": "121",
                "services": [("3 Ball Machine", "1b21354d-1408-49e1-9afa-3b91d7bdab8b"),
                             ("3.2 Primetime Ball Machine", "0914820e-799e-43f2-a07b-4310676ff317")]},
}
MACHINE_COURTS = (2, 3, 8, 9, 10)

JS_API = r"""async ([url, body]) => {
  const r = await fetch(url, {method: 'POST', credentials: 'same-origin',
    headers: {'Content-Type': 'application/json; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest'},
    body: JSON.stringify(body)});
  return {status: r.status, url: r.url, text: await r.text()}; }"""


def minutes(avail: list[dict] | None) -> list[bool]:
    """The web service's day (1440 {TimeId, IsAvailable}) as one flag per minute."""
    out = [False] * DAY_MINUTES
    for a in avail or []:
        t = a.get("TimeId")
        if isinstance(t, int) and 0 <= t < DAY_MINUTES:
            out[t] = bool(a.get("IsAvailable"))
    return out


def both(*days: list[bool]) -> list[bool]:
    """Free only where every day says free (as the club page combines them)."""
    return [all(d[i] for d in days) for i in range(DAY_MINUTES)]


def free_for(day: list[bool], start: int, length: int) -> bool:
    return 0 <= start and start + length <= DAY_MINUTES and all(day[start:start + length])


def open_starts(day: list[bool], length: int = 30, step: int = 30) -> list[int]:
    return [m for m in range(FIRST_START, LAST_END - length + 1, step) if free_for(day, m, length)]

SHIM = ("window.confirm=()=>true;window.alert=(m)=>{};window.prompt=()=>'yes';"
        "window.__wacShim=Date.now();'shim'")

JS_SLOTS = r"""() => { const seen = new Set(), out = [];
  for (const a of document.querySelectorAll('a[key=B_ADD_TO_CART]')) {
    const k = [a.getAttribute('st'), a.getAttribute('et'), a.getAttribute('r'), a.getAttribute('d')].join('|');
    if (seen.has(k)) continue; seen.add(k);
    const tr = a.closest('tr');
    out.push({st: +a.getAttribute('st'), et: +a.getAttribute('et'), r: a.getAttribute('r'),
              d: a.getAttribute('d'), row: tr ? tr.innerText.replace(/\s+/g, ' ').trim().slice(0, 120) : ''});
  } return out; }"""

JS_GRID_MESSAGE = r"""() => { const t = document.body ? document.body.innerText : '';
  const m = t.match(/[^\n]*(?:is not available|not available on the selected date)[^\n]*/i);
  return m ? m[0].trim().slice(0, 200) : ''; }"""

# The court list (lstResource) starts with only courts 2-6 selected, so courts 8, 9
# and ten never show unless every court is selected before searching.
JS_ALL_COURTS = r"""() => { const r = document.querySelector('select[id$="lstResource"]');
  return !r || Array.from(r.options).every(o => o.selected); }"""

# Search with every court selected, from the latest listed start at or before `want`
# (null: the whole day). Returns the start searched from (-1 for the whole day).
JS_TOD_SEARCH = r"""(want) => {
  const s = document.querySelector('#ctl00_pageContentHolder_ddlTimeOfDay');
  const a = document.querySelector('#ancSchSearch');
  if (!s || !a) return null;
  let best = null;
  if (want === null) best = -1;
  else for (const o of s.options) { const v = parseInt(o.value, 10);
    if (v >= 0 && v <= want && (best === null || v > best)) best = v; }
  if (best === null) return 'none';
  const all = document.querySelector('#ancSchSelectAll');
  if (all) all.click();
  const r = document.querySelector('select[id$="lstResource"]');
  if (r) for (const o of r.options) o.selected = true;
  document.querySelectorAll('a[key=B_ADD_TO_CART]').forEach(x => x.setAttribute('data-wac-old', '1'));
  s.value = String(best); s.dispatchEvent(new Event('change', {bubbles: true}));
  a.click(); return best; }"""

JS_DIALOG = r"""(court) => {
  const want = new RegExp('Tennis court ' + court + '\\b', 'i');
  for (const b of document.querySelectorAll('input#btnContinue')) {
    const parent = b.closest('div.dialogParent'); if (!parent) continue;
    const dlg = parent.querySelector('div.dialogPopupRound'); if (!dlg) continue;
    const txt = dlg.innerText || '';
    if (/Booking Details/i.test(txt) && !/Loading\.\.\./.test(txt)) {
      if (!want.test(txt) || !/Date:/.test(txt)) return 'wrong: ' + txt.replace(/\s+/g, ' ').slice(0, 160);
      b.click(); return 'continued';
    }
  } return 'waiting'; }"""

# The participants page's member table: one row per person, cells Name, Relationship
# (Main = the signed-in member, Spouse/Child/... = family on the account, Buddy).
# Every data row counts, whatever its inputs: a family member who already has 2
# reservations that day shows only a disabled host button and no member checkbox.
# Each row gives its cells that have text, so a leading checkbox-only cell doesn't
# shift the columns: [name, relationship, ...].
JS_PARTICIPANTS = r"""() => { const g = document.querySelector('table[id$="ctrlMemberBuddy_gridViewMembers"]');
  if (!g) return null;
  return Array.from(g.querySelectorAll('tr')).filter(tr => tr.querySelector('td') && !tr.querySelector('th'))
    .map(tr => Array.from(tr.querySelectorAll('td')).map(td => (td.innerText || '').replace(/\s+/g, ' ').trim())
      .filter(t => t)).filter(c => c.length >= 2); }"""


def family_from(cells: list[list[str]], me: str = "") -> list[str]:
    """Family members on the account: participant rows whose relationship isn't
    Main (the member) or Buddy. Keeps the page's order."""
    out = []
    for c in cells or []:
        name, rel = " ".join(c[0].split()), c[1].strip().lower()
        if not name or rel in ("main", "buddy", "") or name.lower() == (me or "").lower():
            continue
        if name not in out:
            out.append(name)
    return out


JS_FAMILY_ROWS = r"""() => { const out = [];
  for (const tr of document.querySelectorAll('tr')) {
    const cb = tr.querySelector('input[id*="chkMember" i]');
    const rd = tr.querySelector('input[id*="rdoHost" i]');
    if (!cb && !rd) continue;
    const txt = tr.innerText.replace(/\s+/g, ' ').trim();
    if (txt.length > 150) continue;
    out.push({t: txt, cb: cb ? {id: cb.id, dis: !!cb.disabled, chk: !!cb.checked} : null,
              rd: rd ? {id: rd.id, dis: !!rd.disabled, chk: !!rd.checked} : null});
  } return out; }"""

JS_SELECT_AND_COMMIT = r"""(ids) => {
  for (const id of ids.check) { const el = document.getElementById(id); if (el && !el.checked) el.click(); }
  const rd = document.getElementById(ids.host); if (rd && !rd.checked) rd.click();
  const b = document.querySelector('#ctl00_pageContentHolder_btnContinueCart');
  if (!b) return 'no commit button'; if (b.disabled) return 'commit disabled';
  b.click(); return 'clicked'; }"""

JS_FORCE_COMMIT = r"""(ids) => {
  for (const id of ids) { const el = document.getElementById(id); if (el) { try { el.checked = true; } catch (e) {} } }
  const b = document.querySelector('#ctl00_pageContentHolder_btnContinueCart');
  if (b && !b.disabled) { b.click(); return 'clicked'; }
  if (typeof __doPostBack === 'function') { __doPostBack('ctl00$pageContentHolder$btnContinueCart', ''); return 'postback'; }
  return 'no commit path'; }"""

JS_PAGE_MESSAGE = r"""() => { const out = [];
  for (const el of document.querySelectorAll('[class*="error" i], [id*="error" i], [id*="lblMessage" i], .validation-summary-errors')) {
    const t = (el.innerText || '').replace(/\s+/g, ' ').trim();
    if (t && t.length < 300 && !out.includes(t)) out.push(t);
    if (out.length >= 3) break;
  } return out.join(' | '); }"""

JS_REPORT_ROWS = r"""() => Array.from(document.querySelectorAll('a[id$=hlkScheduleName]')).map(a => {
  const tr = a.closest('tr'); return tr ? tr.innerText.replace(/\s+/g, ' ').trim() : ''; })"""

WELCOME_RE = re.compile(r"Welcome,\s*(.+?)\s*\(\s*([A-Za-z0-9-]+)\s*\)")


def court_label(court: int) -> str:
    return COURT_WORDS.get(court, str(court))


def court_from(resource: str, row: str) -> int | None:
    if resource in RESOURCE_TO_COURT:
        return RESOURCE_TO_COURT[resource]
    m = re.search(r"Tennis court (\d+|ten)\b", row, re.I)
    if not m:
        return None
    return 10 if m.group(1).lower() == "ten" else int(m.group(1))


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def row_matches(row_text: str, name: str) -> bool:
    """The participant row is this person: the row starts with their name and
    the name isn't just the front of a longer one (Ed Kass vs Ed Kassel)."""
    t = " ".join((row_text or "").split()).lower()
    n = " ".join((name or "").split()).lower()
    if not t.startswith(n):
        return False
    rest = t[len(n):]
    return not rest or not rest[0].isalnum()


def match_rows(rows: list[dict], host: str, partners: list[str]) -> dict:
    """Find the host row and each partner row in the participants table."""
    host_row = next((r for r in rows if r.get("rd") and row_matches(r["t"], host)), None)
    found = {}
    for p in partners:
        found[p] = next((r for r in rows if r.get("cb") and row_matches(r["t"], p)), None)
    return {"host": host_row, "partners": found}


def rows_enabled(m: dict) -> bool:
    h = m["host"]
    if not (h and h["cb"] and not h["cb"]["dis"] and h["rd"] and not h["rd"]["dis"]):
        return False
    return all(r and r["cb"] and not r["cb"]["dis"] for r in m["partners"].values())


def report_has(rows: list[str], slot: Slot) -> bool:
    want_time = f"{clubtime.fmt_time(slot.start)} to {clubtime.fmt_time(slot.end)}"
    labels = {f"tennis court {slot.court}", f"tennis court {court_label(slot.court)}"}
    for r in rows:
        r = (r or "").replace("\xa0", " ")
        low = r.lower()
        if slot.date in r and want_time in r and any(re.search(re.escape(x) + r"\b", low) for x in labels):
            return True
    return False


class ClubSite:
    """One sign-in, one browser page. Implements engine.Site."""

    def __init__(self, username: str, password: Callable[[], str], browser: str = "hidden",
                 show_window: bool = False, log: Callable[[str], None] | None = None):
        self.username = username
        self._password = password
        self._secret: str | None = None
        self.browser = browser
        self.show_window = show_window
        self._log = log or (lambda m: None)
        self.member_name = ""
        self.family: list[str] | None = None  # set once a participants page was read
        self.member_number = ""
        self.pw = None
        self.ctx = None
        self.br = None
        self.page = None
        self.posts: list[float] = []
        self.family_url = ""
        self.staged: Slot | None = None
        self.last_fresh = 0.0
        self.fresh_gap = 3.0
        self.row_watch = 8.0
        self.confirm_wait = 60.0

    # ---------------------------------------------------------------- plumbing
    def log(self, msg: str) -> None:
        if self._secret:
            msg = msg.replace(self._secret, "[hidden]")
        self._log(msg)

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def start(self) -> None:
        if self.browser == "hidden" and "PLAYWRIGHT_BROWSERS_PATH" not in os.environ \
                and paths.browsers_dir().exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(paths.browsers_dir())
        from playwright.async_api import async_playwright
        self.pw = await async_playwright().start()
        try:
            if self.browser == "hidden":
                self.br = await self.pw.chromium.launch(headless=True)
                ua = await self._plain_user_agent()
                self.ctx = await self.br.new_context(user_agent=ua, viewport={"width": 1440, "height": 900})
                self.page = await self.ctx.new_page()
            else:
                channel = {"edge": "msedge", "chrome": "chrome"}[self.browser]
                prof = paths.profile_dir(self.browser)
                prof.mkdir(parents=True, exist_ok=True)
                self.ctx = await self.pw.chromium.launch_persistent_context(
                    str(prof), channel=channel, headless=not self.show_window,
                    viewport={"width": 1440, "height": 900})
                self.page = self.ctx.pages[0] if self.ctx.pages else await self.ctx.new_page()
        except Exception as e:
            await self.close()
            raise SiteError(f"the {self.browser} browser didn't start: {why(e, 160)}") from e
        self.page.set_default_timeout(30_000)
        self.page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        self.page.on("request", self._on_request)
        await self.ctx.add_init_script(SHIM)
        self.log(f"browser started ({self.browser})")

    async def _plain_user_agent(self) -> str:
        p = await self.br.new_page()
        ua = await p.evaluate("navigator.userAgent")
        await p.close()
        return ua.replace("HeadlessChrome", "Chrome")

    def _on_request(self, req) -> None:
        if req.method == "POST" and "spectrumng" in req.url:
            self.posts.append(time.time())

    async def close(self) -> None:
        for obj in (self.ctx, self.br):
            try:
                if obj:
                    await obj.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            if self.pw:
                await self.pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self.pw = self.ctx = self.br = self.page = None

    async def js(self, expr: str, arg=None, timeout: float = 15):
        try:
            if arg is None:
                return await asyncio.wait_for(self.page.evaluate(expr), timeout)
            return await asyncio.wait_for(self.page.evaluate(expr, arg), timeout)
        except Exception as e:  # noqa: BLE001 -- navigation in flight, page gone, timeout
            raise SiteError(f"page script failed: {why(e, 120)}") from e

    async def goto(self, url: str, timeout: float = 90) -> None:
        try:
            await self.page.goto(url, wait_until="load", timeout=timeout * 1000)
        except Exception as e:  # noqa: BLE001
            raise SiteError(f"page didn't load: {why(e, 120)}") from e
        try:
            await self.page.evaluate(SHIM)  # the site's own scripts replace window.confirm
        except Exception:  # noqa: BLE001
            pass

    async def url(self) -> str:
        try:
            return self.page.url
        except Exception:  # noqa: BLE001
            return ""

    async def body(self, n: int = 600) -> str:
        try:
            return await self.js(f"document.body ? document.body.innerText.slice(0, {n}) : ''") or ""
        except SiteError:
            return ""

    async def wait_for(self, expr: str, timeout: float, interval: float = 0.5, arg=None):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            try:
                last = await self.js(expr, arg)
                if last:
                    return last
            except SiteError:
                pass
            await asyncio.sleep(interval)
        return last

    # ---------------------------------------------------------------- sign in
    async def login(self) -> str:
        await self.goto(LOGIN_URL, timeout=60)
        head = await self.body(400)
        m = WELCOME_RE.search(head)
        if m and "Login.aspx" not in await self.url():
            return self._signed_in(m)
        field = await self.wait_for("!!document.querySelector('#ctl00_pageContentHolder_loginControl_UserName')", 30)
        if not field:
            raise SiteError("the club sign-in page didn't show its form")
        self._secret = self._password()
        try:
            await self.page.fill("#ctl00_pageContentHolder_loginControl_UserName", self.username)
            await self.page.fill("#ctl00_pageContentHolder_loginControl_Password", self._secret)
            await self.page.click("#ctl00_pageContentHolder_loginControl_Login", no_wait_after=True)
        except Exception as e:  # noqa: BLE001
            raise SiteError(f"couldn't fill in the sign-in form: {why(e, 100)}") from e
        end = time.time() + 120
        while time.time() < end:
            await asyncio.sleep(1)
            u = await self.url()
            if "Login.aspx" not in u:
                break
            msg = await self.body(3000)
            if re.search(r"not successful|invalid|incorrect|locked", msg, re.I):
                raise SiteError("the club site says the username or password is wrong", "login")
        else:
            raise SiteError("still on the sign-in page after 2 minutes")
        for _ in range(3):
            m = WELCOME_RE.search(await self.body(400))
            if m:
                return self._signed_in(m)
            await asyncio.sleep(3)
        raise SiteError("signed in, but the welcome line didn't show")

    def _signed_in(self, m) -> str:
        self.member_name = " ".join(m.group(1).split())
        self.member_number = m.group(2)
        self.log(f"signed in as {self.member_name}")
        return self.member_name

    # ---------------------------------------------------------------- buddies
    async def buddies(self) -> list[str]:
        await self.goto(BUDDY_URL, timeout=60)
        rows = await self.wait_for(r"""() => { const t = document.querySelector('#ctl00_pageContentHolder_gvMemberBuddies');
            if (!t) return null; return Array.from(t.querySelectorAll('tr')).map(tr => {
              const cells = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.replace(/\s+/g, ' ').trim());
              return cells.find(c => c && c.indexOf('@') < 0) || ''; })
              .filter(Boolean); }""", 30)
        if rows is None:
            body = await self.body(2000)
            if "My Buddy List" in body:
                return []
            raise SiteError("the buddy list page didn't load")
        return list(dict.fromkeys(rows))

    # ---------------------------------------------------------------- grid
    async def load_grid(self, svc: str, date: str, length: int, start: int | None) -> list[dict]:
        """Open the grid and bring `start` into view. Returns the open slots
        shown (deduplicated), each with its court number."""
        await self.goto(GRID_URL.format(svc=svc, d=date, du=length), timeout=90)
        await self.wait_for("document.querySelectorAll('a[key=B_ADD_TO_CART]').length > 0 || "
                            "/not available/i.test(document.body ? document.body.innerText : '')", 30)
        # Courts 8-10 aren't selected when the page opens: always search once with
        # every court selected (and again if `start` still isn't in view).
        all_courts = bool(await self.js(JS_ALL_COURTS))
        if start is not None or not all_courts:
            for _ in range(2):
                slots = await self.js(JS_SLOTS) or []
                sts = [s["st"] for s in slots]
                # The list shows 15 rows a page, sorted by time: every court at
                # `start` is on this page only if a later start time shows too.
                if all_courts and (start is None or (sts and min(sts) <= start < max(sts))):
                    break
                picked = await self.js(JS_TOD_SEARCH, start)
                all_courts = True
                if picked in (None, "none"):
                    break
                if not sts:
                    # Nothing listed before the search (courts 2-6 all taken), so there
                    # are no old rows to watch disappear: wait for new rows or a message.
                    await self.wait_for("document.querySelectorAll('a[key=B_ADD_TO_CART]').length > 0 || "
                                        "/not available/i.test(document.body ? document.body.innerText : '')", 10)
                end = time.time() + 45
                while time.time() < end:
                    await asyncio.sleep(0.5)
                    try:
                        if not await self.js("document.querySelectorAll('a[data-wac-old]').length"):
                            break
                    except SiteError:
                        pass
                await asyncio.sleep(0.8)
                slots = await self.js(JS_SLOTS) or []
                sts = [s["st"] for s in slots]
                if (sts and min(sts) >= picked) or await self.js(JS_GRID_MESSAGE):
                    break  # the search took effect
        out = []
        for s in await self.js(JS_SLOTS) or []:
            c = court_from(s["r"], s["row"])
            if c is not None:
                s["court"] = c
                out.append(s)
        return out

    async def find_open(self, date: str, start: int, lengths: list[int], play: str) -> dict[int, dict[int, Slot]]:
        result: dict[int, dict[int, Slot]] = {}
        for length in lengths:
            result[length] = {}
            for name, svc in SERVICES[play]:
                shown = await self.load_grid(svc, date, length, start)
                hits = {s["court"]: Slot(date, start, length, s["court"], s["r"], svc)
                        for s in shown if s["st"] == start and s["et"] == start + length}
                if hits:
                    result[length] = hits
                    break
        return result

    async def list_open(self, date: str, length: int, play: str) -> list[Slot]:
        """Open slots in each service's default view (the earliest times of the day)."""
        out: list[Slot] = []
        for _, svc in SERVICES[play]:
            for s in await self.load_grid(svc, date, length, None):
                if s["et"] - s["st"] == length:
                    out.append(Slot(date, s["st"], length, s["court"], s["r"], svc))
        return out

    # ---------------------------------------------------------------- web service (read-only)
    async def api(self, method: str, payload: dict, timeout: float = 60):
        """Call the club's scheduler web service with this sign-in. Returns its Value.
        Signs in again once if the session has run out."""
        for attempt in (1, 2):
            if "spectrumng" not in (await self.url()).lower():
                await self.goto(HOME_URL, timeout=60)
            r = await self.js(JS_API, [API_PATH + method, payload], timeout)
            text = (r or {}).get("text") or ""
            if (r or {}).get("status") == 200 and text.lstrip().startswith("{"):
                try:
                    d = json.loads(text).get("d") or {}
                except ValueError:
                    d = None
                if isinstance(d, dict):
                    if d.get("IsException"):
                        raise SiteError(f"the club site said: {str(d.get('Message') or 'error')[:160]}")
                    return d.get("Value")
            if attempt == 1 and ("login" in str((r or {}).get("url", "")).lower() or "<html" in text[:300].lower()):
                self.log("web service needs a fresh sign-in")
                await self.login()
                continue
            raise SiteError(f"the club's web service didn't answer ({method}: HTTP {(r or {}).get('status')})")
        raise SiteError("the club's web service didn't answer")

    async def day_availability(self, date: str, svc: str | None = None, machines: bool = False) -> dict:
        """Every court's free minutes on `date` (m/d/Y), as the court sheet works them out:
        court free AND the service offered then AND the club open. With `machines`, also
        each ball machine's free minutes (its own service, any Prime Time variant, and
        the club's hours). Booked times (no names) come back too."""
        svc = svc or SERVICES["doubles"][0][1]
        site_day = minutes(await self.api("GetSiteAvailability", {"siteId": SITE_ID, "selectedDate": date}))
        svc_day = minutes(await self.api("GetServiceAvailability", {"serviceUniqueId": svc, "selectedDate": date}))
        res = await self.api("GetSchedulerResourceAvailability",
                             {"siteId": SITE_ID, "resourceIds": list(RESOURCE_TO_COURT), "selectedDate": date}) or []
        courts, booked = {}, {}
        for x in res:
            c = RESOURCE_TO_COURT.get(str(x.get("Id")))
            if c is None:
                continue
            courts[c] = both(minutes(x.get("Availability")), svc_day, site_day)
            booked[c] = [(int(b.get("FromMinutes", 0)), int(b.get("ToMinutes", 0))) for b in x.get("BookingDetails") or []]
        out = {"courts": courts, "booked": booked, "machines": {}}
        if machines:
            pids = [m["provider"] for m in MACHINES.values()]
            prov = {str(x.get("Id")): minutes(x.get("Availability")) for x in await self.api(
                "GetSchedulerProviderAvailability", {"siteId": SITE_ID, "providerIds": pids, "selectedDate": date}) or []}
            for key, m in MACHINES.items():
                offered = [False] * DAY_MINUTES
                for _, g in m["services"]:
                    s = minutes(await self.api("GetServiceAvailability", {"serviceUniqueId": g, "selectedDate": date}))
                    offered = [a or b for a, b in zip(offered, s)]
                out["machines"][key] = both(prov.get(m["provider"], [False] * DAY_MINUTES), offered, site_day)
        return out

    def _slot_selector(self, slot: Slot) -> str:
        return (f'a[key=B_ADD_TO_CART][st="{slot.start}"][et="{slot.end}"]'
                f'[r="{slot.resource}"][d="{slot.date}"]')

    async def slot_still_open(self, slot: Slot) -> bool | None:
        shown = await self.load_grid(slot.service, slot.date, slot.length, slot.start)
        if any(s["st"] == slot.start and s["et"] == slot.end and s["court"] == slot.court for s in shown):
            return True
        if shown or await self.js(JS_GRID_MESSAGE):
            return False
        return None  # empty grid: can't tell

    # ---------------------------------------------------------------- staging
    async def stage(self, slot: Slot) -> None:
        """Grid -> slot -> Booking Details -> participants page with the
        booking loaded. Raises SiteError('taken') if the slot isn't offered."""
        if self.staged == slot and self.family_url:
            # Same slot again: its participants page usually still works, which
            # avoids adding the slot to the cart a second time.
            try:
                await self.goto(self.family_url, timeout=60)
                if await self._family_loaded(slot, 30):
                    self.last_fresh = time.time()
                    self.log("back on the staged participants page")
                    return
            except SiteError:
                pass
        shown = await self.load_grid(slot.service, slot.date, slot.length, slot.start)
        if not shown:
            shown = await self.load_grid(slot.service, slot.date, slot.length, slot.start)
            if not shown and not await self.js(JS_GRID_MESSAGE):
                raise SiteError("the court grid came up empty")
        sel = self._slot_selector(slot)
        label = court_label(slot.court)
        clicked = await self.js(
            r"""([sel, label]) => { const a = document.querySelector(sel); if (!a) return 'not found';
                const tr = a.closest('tr');
                if (tr && !new RegExp('Tennis court ' + label + '\\b', 'i').test(tr.innerText)) return 'row mismatch';
                a.click(); return 'clicked'; }""", [sel, label])
        if clicked == "not found":
            e = SiteError(f"{slot.describe()} isn't offered", "taken")
            raise e
        if clicked != "clicked":
            raise SiteError(f"slot click failed: {clicked}")
        res = None
        end = time.time() + 120
        while time.time() < end:
            try:
                res = await self.js(JS_DIALOG, label)
            except SiteError as e:  # a slow moment or a page change in flight; look again
                res = f"waiting ({e})"
            if not str(res).startswith("waiting"):
                break
            await asyncio.sleep(0.5)
        if res != "continued":
            raise SiteError(f"the Booking Details box didn't load ({str(res)[:80]})")
        if not await self.wait_for("location.href.indexOf('AddFamilyMembers') >= 0", 120):
            raise SiteError("the participants page didn't open")
        self.family_url = await self.url()
        if not await self._family_loaded(slot, 60):
            self.log("participants page has no booking details yet; reloading it")
            await self.goto(self.family_url, timeout=90)
            if not await self._family_loaded(slot, 60):
                raise SiteError("the participants page never loaded the booking")
        self.staged = slot
        self.last_fresh = time.time()
        self.log(f"staged {slot.describe()}")
        if self.family is None:  # once per session: a re-stage near W must stay fast
            await self._note_family()

    async def _note_family(self, wait: float = 5) -> None:
        """Remember the family members the participants page lists (the only page
        on the club site that shows them). Never fails the caller."""
        try:
            cells = await self.wait_for(JS_PARTICIPANTS, wait, 0.5)
            if cells:
                self.family = family_from(cells, self.member_name)
                self.log(f"member table: {len(cells)} rows; family on the account: {len(self.family)}")
            else:
                shape = await self.js(r"""() => { const g = document.querySelector('table[id$="ctrlMemberBuddy_gridViewMembers"]');
                    if (!g) return 'no member table';
                    const tr = Array.from(g.querySelectorAll('tr'))[1];
                    return 'member table, ' + g.querySelectorAll('tr').length + ' rows; row 2 cells: ' +
                      (tr ? Array.from(tr.children).map(c => c.tagName + '[' + (c.innerText || '').trim().length + ']').join(' ') : 'none'); }""")
                self.log(f"no member rows read ({shape})")
        except Exception as e:  # noqa: BLE001
            self.log(f"couldn't read family members: {why(e)}")

    async def _family_loaded(self, slot: Slot, timeout: float) -> bool:
        return bool(await self.wait_for(
            "(d) => location.href.indexOf('AddFamilyMembers') >= 0 && !!document.body && "
            "document.body.innerText.indexOf('Current Schedule Details') >= 0 && "
            "document.body.innerText.indexOf(d) >= 0", timeout, 0.25, arg=slot.date))

    async def is_staged(self) -> bool:
        if not self.staged or "AddFamilyMembers" not in await self.url():
            return False
        return await self._family_loaded(self.staged, 2)

    async def keepalive(self) -> None:
        if not self.staged:
            raise SiteError("nothing staged")
        await self.goto(self.family_url, timeout=90)
        if not await self._family_loaded(self.staged, 60):
            raise SiteError("the participants page lost its booking")
        self.last_fresh = time.time()

    async def back_out(self) -> None:
        """Leave the participants page with Back, which drops the cart item."""
        r = await self.js("() => { const b = document.querySelector('#ctl00_pageContentHolder_btnBack');"
                          " if (!b) return 'none'; b.click(); return 'ok'; }")
        if r != "ok":
            raise SiteError("no Back button on the participants page")
        end = time.time() + 90
        while time.time() < end:
            await asyncio.sleep(1)
            if "AddFamilyMembers" not in await self.url():
                self.staged = None
                return
        raise SiteError("still on the participants page after Back")

    async def release(self) -> None:
        """Best effort: drop a staged, unbooked cart item."""
        try:
            if "AddFamilyMembers" in await self.url():
                await self.back_out()
        except SiteError as e:
            self.log(f"couldn't leave the participants page: {e}")

    # ---------------------------------------------------------------- commit
    async def _rows(self) -> list[dict]:
        try:
            return await self.js(JS_FAMILY_ROWS) or []
        except SiteError:
            return []

    async def attempt(self, partners: list[str]) -> Attempt:
        """One press of Continue to Cart from the staged page, then wait for
        the server's answer without leaving the page."""
        try:
            loading = await self.js("document.readyState !== 'complete'", timeout=5)
        except SiteError:
            loading = True
        if loading:
            return Attempt(NOT_READY, "page still loading")
        m = match_rows(await self._rows(), self.member_name, partners)
        on_family = "AddFamilyMembers" in await self.url()
        if not rows_enabled(m) and on_family and time.time() - self.last_fresh >= self.fresh_gap:
            # Before the window the participants page is an offline render; only a
            # fresh load re-checks eligibility. Partner rows arrive a little after
            # the page itself, so watch it for a few seconds.
            try:
                await self.goto(self.family_url, timeout=60)
                await self._family_loaded(self.staged, 60)
                end = time.time() + self.row_watch
                while time.time() < end:
                    m = match_rows(await self._rows(), self.member_name, partners)
                    if rows_enabled(m):
                        break
                    await asyncio.sleep(0.5)
            except SiteError as e:
                self.log(f"fresh load failed: {e}")
            self.last_fresh = time.time()
        req_at = time.time()
        if rows_enabled(m):
            ids = {"check": [m["host"]["cb"]["id"]] + [r["cb"]["id"] for r in m["partners"].values()],
                   "host": m["host"]["rd"]["id"]}
            how = await self.js(JS_SELECT_AND_COMMIT, ids)
            if how != "clicked":
                return Attempt(NOT_READY, how)
            how = "ticked"
        else:
            ids = []
            if m["host"]:
                ids += [x["id"] for x in (m["host"]["cb"], m["host"]["rd"]) if x]
            ids += [r["cb"]["id"] for r in m["partners"].values() if r and r["cb"]]
            how = await self.js(JS_FORCE_COMMIT, ids)
            if how == "no commit path":
                return Attempt(NOT_READY, how)
        outcome, detail = await self.wait_outcome(req_at)
        return Attempt(outcome, detail if outcome != CONFIRMED else f"{detail} ({how})")

    async def wait_outcome(self, req_at: float, no_post_s: float = 4.0) -> tuple[str, str]:
        """CONFIRMED / REJECTED / OFFPAGE / NO_POST / UNKNOWN. Never navigates."""
        end = req_at + self.confirm_wait
        req_ms = req_at * 1000.0
        while time.time() < end:
            try:
                st = await asyncio.wait_for(self.page.evaluate(
                    "() => ({loc: location.href, rs: document.readyState, origin: performance.timeOrigin})"), 5)
            except Exception:  # noqa: BLE001 -- mid-navigation
                st = None
            if st:
                loc = st.get("loc") or ""
                if "CurrentScheduleDetail" in loc:
                    q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
                    return CONFIRMED, q.get("scheduleGuid", [""])[0]
                if (st.get("origin") or 0) > req_ms and st.get("rs") == "complete":
                    if "AddFamilyMembers" in loc:
                        try:
                            msg = await self.js(JS_PAGE_MESSAGE)
                        except SiteError:
                            msg = ""
                        self.last_fresh = time.time()
                        return REJECTED, str(msg or "")[:200]
                    return OFFPAGE, loc[:160]
            if time.time() - req_at > no_post_s and not any(t >= req_at - 0.25 for t in self.posts):
                return NO_POST, ""
            await asyncio.sleep(0.1)
        return UNKNOWN, ""

    # ---------------------------------------------------------------- report
    async def reservation_rows(self, date: str, require_rows: bool = False) -> list[str]:
        """Row texts of the Reservation Report around `date`. With
        require_rows, an empty report after 60 s raises (unknown, not absent)."""
        d = datetime.strptime(date, "%m/%d/%Y")
        frm, to = (d - timedelta(days=1)).strftime("%m/%d/%Y"), (d + timedelta(days=1)).strftime("%m/%d/%Y")
        await self.goto(REPORT_URL, timeout=90)
        ok = await self.js(r"""([f, t]) => {
            const a = document.querySelector('#ctl00_pageContentHolder_ctrlFromDate_txtDate');
            const b = document.querySelector('#ctl00_pageContentHolder_ctrlToDate_txtDate');
            const go = document.querySelector('#ctl00_pageContentHolder_btnShowReport');
            if (!a || !b || !go) return 'missing';
            for (const [el, v] of [[a, f], [b, t]]) { el.value = v;
              el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); }
            go.click(); return 'ok'; }""", [frm, to])
        if ok != "ok":
            raise SiteError("the reservation report page didn't show its date boxes")
        settle, end = 20.0, time.time() + (60.0 if require_rows else 25.0)
        empty_since = None
        while True:
            await asyncio.sleep(1)
            try:
                rows = await self.js(JS_REPORT_ROWS) or []
            except SiteError:
                rows = []
            if rows:
                return rows
            empty_since = empty_since or time.time()
            if not require_rows and time.time() - empty_since >= settle:
                return []
            if time.time() >= end:
                if require_rows:
                    raise SiteError("the reservation report stayed empty")
                return []

    async def reservation_exists(self, slot: Slot) -> bool | None:
        try:
            rows = await self.reservation_rows(slot.date, require_rows=True)
        except SiteError:
            return None
        return report_has(rows, slot)

    async def cancel(self, slot: Slot, tries: int = 3) -> None:
        """Cancel one reservation via the Reservation Report. Only the test
        booking ever calls this."""
        want_time = f"{clubtime.fmt_time(slot.start)} to {clubtime.fmt_time(slot.end)}"
        last = ""
        for n in range(1, tries + 1):
            try:
                await self.reservation_rows(slot.date)
                r = await self.js(r"""([date, time, labels]) => {
                    for (const a of document.querySelectorAll('a[id$=hlkScheduleName]')) {
                      const tr = a.closest('tr'); const t = (tr ? tr.innerText : '').replace(/\s+/g, ' ');
                      if (t.indexOf(date) >= 0 && t.indexOf(time) >= 0 &&
                          labels.some(l => new RegExp('Tennis court ' + l + '\\b', 'i').test(t))) { a.click(); return 'ok'; }
                    } return 'row not found'; }""",
                                  [slot.date, want_time, [str(slot.court), court_label(slot.court)]])
                if r != "ok":
                    raise SiteError(f"cancel: {r}")
                if not await self.wait_for("!!document.querySelector('#ctl00_pageContentHolder_btnCancelSchedule')", 60, 1):
                    raise SiteError("cancel: no Cancel button on the reservation")
                await self.js("() => { document.querySelector('#ctl00_pageContentHolder_btnCancelSchedule').click(); return 1; }")
                # The Yes button is always in the page, hidden; clicking it before the
                # confirm box opens does nothing. Wait until it's actually showing.
                await asyncio.sleep(2)
                yes = await self.wait_for(
                    "() => { const b = document.querySelector('#ctl00_pageContentHolder_ctrlPopup_btnYes');"
                    " if (!b || !b.offsetParent || getComputedStyle(b).visibility === 'hidden') return null;"
                    " b.click(); return 'yes'; }", 20, 0.5)
                if yes != "yes":
                    raise SiteError("cancel: the 'are you sure' box didn't appear")
                end = time.time() + 60
                while time.time() < end:
                    if "CANCELED" in (await self.url()).upper():
                        self.log(f"cancelled {slot.describe()}")
                        return
                    await asyncio.sleep(1)
                raise SiteError("cancel: the site didn't confirm the cancellation")
            except SiteError as e:
                last = str(e)
                self.log(f"cancel try {n} failed: {e}")
                await asyncio.sleep(3)
        raise SiteError(f"couldn't cancel: {last}")
