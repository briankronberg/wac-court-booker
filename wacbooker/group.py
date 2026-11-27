"""Coordinated logins: one court per login, side by side when the sheet allows."""
from __future__ import annotations

from .config import COURTS, Booking
from .engine import Slot


class Group:
    """Hands out the open courts to a booking's logins, one per member.

    `want` records which court each member (index into Booking.members) has
    been handed, so the others don't take it.
    """

    def __init__(self, size: int):
        self.want: dict[int, int] = {}
        self.size = size

    def chooser(self, idx: int):
        """A callable for Engine.choose: member `idx`'s turn to pick."""
        return lambda open_by_len, booking, tried: self.pick(idx, open_by_len, booking, tried)

    def release(self, idx: int) -> None:
        self.want.pop(idx, None)

    @staticmethod
    def _rank(booking: Booking) -> dict[int, int]:
        """Lower is better: the named courts in listed order, then the rest by number."""
        named = [c for c in booking.courts if c != "any"]
        return {c: i for i, c in enumerate(named + [c for c in COURTS if c not in named])}

    @staticmethod
    def _runs(courts: list[int]) -> list[list[int]]:
        """Maximal blocks of consecutive court numbers, e.g. [2, 9, 10] -> [[2], [9, 10]]."""
        runs: list[list[int]] = []
        for c in sorted(courts):
            if runs and c == runs[-1][-1] + 1:
                runs[-1].append(c)
            else:
                runs.append([c])
        return runs

    def pick(self, idx: int, open_by_len: dict, booking: Booking, tried) -> Slot | None:
        """The court for member `idx` among the open ones, or None: none left."""
        others = {c for i, c in self.want.items() if i != idx}
        rank = self._rank(booking)
        for L in booking.lengths:
            avail = {c: s for c, s in (open_by_len.get(L) or {}).items()
                     if (c, L) not in tried and c not in others}
            if not avail:
                continue
            if others:
                # the group is already on the sheet: sit next to them (same bank, one apart)
                for c in sorted(avail, key=lambda c: rank[c]):
                    if any(abs(c - o) == 1 for o in others):
                        self.want[idx] = c
                        return avail[c]
            # no one else is here (or no seat next to them): the best block of k in a row,
            # k = the members still without a court (this one included); the k best if the
            # sheet has no such block
            k = self.size - len([i for i in self.want if i != idx])  # members without a court, this one included
            blocks = [run[i:i + k] for run in self._runs(sorted(avail))
                      for i in range(len(run) - k + 1)]
            best = min(blocks, key=lambda blk: sum(rank[c] for c in blk), default=None)
            if best is None:
                best = sorted(avail, key=lambda c: rank[c])[:k]
            c = min(best, key=lambda c: rank[c])
            self.want[idx] = c
            return avail[c]
        return None
