import asyncio

import pytest

from wacbooker.engine import SiteError
from wacbooker.site import ClubSite, why


def test_why_never_empty():
    assert why(asyncio.TimeoutError()) == "timed out"
    assert why(TimeoutError()) == "timed out"
    assert why(RuntimeError("")) == "RuntimeError"
    assert why(RuntimeError("\n\nsecond line\nthird")) == "second line"
    assert why(RuntimeError("x" * 500), 10) == "x" * 10


class _HangingPage:
    async def evaluate(self, *a):
        await asyncio.sleep(5)


def test_js_timeout_is_a_site_error_and_wait_for_retries():
    """A page script that times out used to raise IndexError (from an empty message),
    which skipped wait_for's retries and stopped the booking."""
    s = ClubSite("u", lambda: "", browser="hidden")
    s.page = _HangingPage()

    async def go():
        with pytest.raises(SiteError, match="timed out"):
            await s.js("1", timeout=0.05)
        # wait_for swallows the SiteError and keeps polling until its own timeout.
        orig = s.js
        s.js = lambda expr, arg=None: orig(expr, arg, timeout=0.05)
        assert await s.wait_for("1", 0.3, 0.05) is None

    asyncio.run(go())
