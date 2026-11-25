"""results.jsonl: one line per run (booked, not booked, skipped, missed, test)."""
from __future__ import annotations

import json
from datetime import datetime

from . import paths


def record(kind: str, booking: str, status: str, message: str, **extra) -> dict:
    rec = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), "kind": kind,
           "booking": booking, "status": status, "message": message, **extra}
    paths.ensure()
    with open(paths.results_file(), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return rec


def recent(n: int = 15) -> list[dict]:
    p = paths.results_file()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines()[-n:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
