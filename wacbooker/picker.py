"""Arrow-key list picker for the Windows console.

Up/Down (and PgUp/PgDn, Home/End) move, typing narrows the list, Backspace un-types,
Enter chooses, Esc goes back. The last row is always "Someone not on this list", for
partners who aren't on the buddy list, such as family members on the club account.

The picking logic (PickState) is separate from the drawing and keys, so it's unit-tested
without a console. available() is False when input isn't a real console (piped or
redirected); callers then fall back to typed answers.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

OTHER = "Someone not on this list (type their full name)"
ROWS = 12

# Keys, as PickState understands them.
UP, DOWN, PGUP, PGDN, HOME, END, ENTER, BACK, ESC = (
    "up", "down", "pgup", "pgdn", "home", "end", "enter", "back", "esc")


@dataclass
class PickState:
    names: list[str]
    typed: str = ""
    cursor: int = 0
    top: int = 0
    rows: int = ROWS
    done: bool = False
    result: str | None = field(default=None)  # a name, OTHER, or None (Esc)

    def shown(self) -> list[str]:
        """The rows on offer: names containing every typed word, then OTHER."""
        words = self.typed.lower().split()
        hits = [n for n in self.names if all(w in n.lower() for w in words)]
        return hits + [OTHER]

    def key(self, k: str) -> None:
        shown = self.shown()
        last = len(shown) - 1
        if k == UP:
            self.cursor = max(0, self.cursor - 1)
        elif k == DOWN:
            self.cursor = min(last, self.cursor + 1)
        elif k == PGUP:
            self.cursor = max(0, self.cursor - self.rows)
        elif k == PGDN:
            self.cursor = min(last, self.cursor + self.rows)
        elif k == HOME:
            self.cursor = 0
        elif k == END:
            self.cursor = last
        elif k == ENTER:
            self.done, self.result = True, shown[self.cursor]
        elif k == ESC:
            self.done, self.result = True, None
        elif k == BACK:
            self.typed = self.typed[:-1]
            self.cursor = 0
        elif len(k) == 1 and k.isprintable():
            self.typed += k
            self.cursor = 0
        # Keep the cursor on screen.
        if self.cursor < self.top:
            self.top = self.cursor
        elif self.cursor >= self.top + self.rows:
            self.top = self.cursor - self.rows + 1
        self.top = max(0, min(self.top, max(0, len(self.shown()) - self.rows)))


# ---------------------------------------------------------------- console side

_vt_ready: bool | None = None


def _enable_vt() -> bool:
    """Turn on ANSI cursor codes for this console (Windows 10 and later)."""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not k32.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        return bool(k32.SetConsoleMode(h, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:  # noqa: BLE001
        return False


def available() -> bool:
    global _vt_ready
    if os.environ.get("WACB_NO_PICKER") or os.name != "nt":
        return False
    try:
        import msvcrt  # noqa: F401
    except ImportError:
        return False
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    if _vt_ready is None:
        _vt_ready = _enable_vt()
    return _vt_ready


_SPECIAL = {"H": UP, "P": DOWN, "I": PGUP, "Q": PGDN, "G": HOME, "O": END}


def _read_key() -> str:
    import msvcrt
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        return _SPECIAL.get(msvcrt.getwch(), "")
    if ch == "\x03":
        raise KeyboardInterrupt
    return {"\r": ENTER, "\x08": BACK, "\x1b": ESC}.get(ch, ch)


def pick(title: str, names: list[str], note: str = "") -> str | None:
    """Show the picker; returns a name, OTHER, or None if the person pressed Esc."""
    st = PickState(list(names))
    height = 0
    out = sys.stdout
    out.write("\x1b[?25l")  # hide the cursor while drawing
    try:
        while not st.done:
            shown = st.shown()
            lines = [title,
                     f"  Type to narrow: {st.typed}_" if st.typed else
                     "  Up/Down to move, type letters to narrow, Enter to choose, Esc to go back",
                     ""]
            window = shown[st.top:st.top + st.rows]
            for i, n in enumerate(window, st.top):
                mark = ">" if i == st.cursor else " "
                text = f" {mark} {n}"
                lines.append(f"\x1b[7m{text}\x1b[0m" if i == st.cursor else text)
            lines += [""] * (st.rows - len(window))
            more = len(shown) - (st.top + len(window))
            lines.append(f"   ... {more} more below" if more > 0 else "")
            if note:
                lines.append(f"  {note}")
            if height:
                out.write(f"\x1b[{height}F")  # back to the top of the last drawing
            for ln in lines:
                out.write("\x1b[2K" + ln + "\n")
            out.flush()
            height = len(lines)
            st.key(_read_key())
    finally:
        out.write("\x1b[?25h")
        out.flush()
    return st.result
