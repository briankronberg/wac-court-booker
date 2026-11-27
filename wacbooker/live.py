"""A signed-in club session the app's window keeps warm for read-only looks:
the court calendar, court checks and the reservation list.

Signing in takes 10-20 seconds; after that each look is one call to the club's web
service. The session runs on its own event loop thread (Playwright objects belong to
the loop that made them) and closes after IDLE seconds unused, or when the window's
server stops. Scheduled bookings never use it: they run in their own process."""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Awaitable, Callable

from .config import Config, Login
from .engine import SiteError

IDLE = 10 * 60


class Live:
    def __init__(self, idle: float = IDLE):
        self.idle = idle
        self.loop = asyncio.new_event_loop()
        self.sessions: dict[str, tuple] = {}  # username -> (site, browser setting, last used)
        self._lock: asyncio.Lock | None = None
        threading.Thread(target=self._run_loop, daemon=True, name="club-live").start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self._lock = asyncio.Lock()
        self.loop.create_task(self._reaper())
        self.loop.run_forever()

    def run(self, cfg: Config, login: Login, fn: Callable[..., Awaitable], say: Callable[[str], None],
            timeout: float = 600, retry: bool = True):
        """Run `fn(site)` with a signed-in session for `login`; blocks this thread. A read
        that fails is tried once more on a new session; anything that changes something
        on the club site (retry=False) is not."""
        while self._lock is None:
            time.sleep(0.01)
        fut = asyncio.run_coroutine_threadsafe(self._use(cfg, login, fn, say, retry), self.loop)
        return fut.result(timeout)

    async def _use(self, cfg: Config, login: Login, fn, say, retry: bool = True):
        from . import runner
        async with self._lock:
            for attempt in ((1, 2) if retry else (2,)):
                site = await self._session(cfg, login, say, runner)
                try:
                    out = await fn(site)
                    self.sessions[login.username] = (site, cfg.browser, time.monotonic())
                    return out
                except SiteError as e:
                    # A dead page or a lost sign-in: start over once with a new session.
                    await self._drop(login.username)
                    if attempt == 2 or e.kind == "login":
                        raise
                    runner._log(f"live {login.nickname}")(f"session failed ({e}); starting a new one")

    async def _session(self, cfg: Config, login: Login, say, runner):
        held = self.sessions.get(login.username)
        if held and held[1] == cfg.browser and time.monotonic() - held[2] < self.idle:
            return held[0]
        if held:
            await self._drop(login.username)
        say("Signing in to the club site…")
        site = await runner.start_site(cfg, login, runner._log(f"live {login.nickname}"))
        try:
            await site.login()
        except BaseException:
            await site.close()
            raise
        self.sessions[login.username] = (site, cfg.browser, time.monotonic())
        return site

    async def _drop(self, username: str) -> None:
        held = self.sessions.pop(username, None)
        if held:
            try:
                await held[0].close()
            except Exception:  # noqa: BLE001
                pass

    async def _reaper(self) -> None:
        while True:
            await asyncio.sleep(30)
            if self._lock.locked():
                continue
            for u, held in list(self.sessions.items()):
                if time.monotonic() - held[2] >= self.idle:
                    await self._drop(u)

    def forget(self, username: str) -> None:
        """Close one login's session (its password or browser changed)."""
        if self._lock is not None:
            asyncio.run_coroutine_threadsafe(self._drop(username), self.loop)

    def close(self, timeout: float = 20) -> None:
        if self._lock is None:
            return

        async def all_():
            for u in list(self.sessions):
                await self._drop(u)
        try:
            asyncio.run_coroutine_threadsafe(all_(), self.loop).result(timeout)
        except Exception:  # noqa: BLE001
            pass
