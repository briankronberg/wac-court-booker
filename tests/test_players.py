"""Naming bookers in the calendar: the fit check, the saved names, the page's endpoint (offline)."""
import json

import pytest

from wacbooker import paths, runner

from test_web import call, srv  # noqa: F401  (fixture)


def test_name_fits():
    assert runner.name_fits("Smi, A.", "Alex Smithers")
    assert runner.name_fits("smi, a.", "alex SMITH Jr.")
    assert not runner.name_fits("Smi, A.", "Bea Smith")      # wrong initial
    assert not runner.name_fits("Smi, A.", "Alex Jones")     # wrong last name
    assert not runner.name_fits("Smi, A.", "Alex")           # one word
    assert not runner.name_fits("Not Shown", "Alex Smith")
    assert runner.initial_last("alex  van smith") == "A. smith"


def test_save_and_forget(tmp_path, monkeypatch):
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    assert runner.save_player(123, "Smi, A.", "  Alex   Smithers ") == "A. Smithers"
    assert runner.load_players() == {"123": "Alex Smithers"}
    with pytest.raises(ValueError, match="doesn't fit"):
        runner.save_player(123, "Smi, A.", "Bea Smith")
    assert runner.load_players() == {"123": "Alex Smithers"}  # a bad name changes nothing
    assert runner.save_player(123, "Smi, A.", "") == "A. Smi…"
    assert runner.load_players() == {}


def test_calendar_uses_saved_names():
    from datetime import date, datetime
    avail = {"courts": {}, "booked": {3: [(480, 540, "Smi, A.", 123)], 4: [(480, 540, "Smi, A.", 456)],
                                      5: [(480, 540, "Not Shown", 0)]}}
    out = runner.calendar_cells(avail, date(2026, 12, 4), datetime(2026, 12, 1, 9, 0), [], {"123": "Alex Smithers"})
    assert out["who"]["3"][480] == "A. Smithers" and out["hosts"]["3"][480] == [123, "Smi, A."]
    assert out["who"]["4"][480] == "A. Smi…" and out["hosts"]["4"][480] == [456, "Smi, A."]
    assert out["who"]["5"][480] == "Not Shown" and 480 not in out["hosts"]["5"]  # nothing to name


def test_page_names_a_player(srv):  # noqa: F811
    _, r = call(srv, "/api/player", {"id": 123, "club": "Smi, A.", "name": "Alex Smithers"})
    assert r == {"ok": True, "shown": "A. Smithers"}
    assert json.loads(paths.players_file().read_text(encoding="utf-8")) == {"123": "Alex Smithers"}
    _, r = call(srv, "/api/player", {"id": 123, "club": "Smi, A.", "name": "Bea Jones"})
    assert not r["ok"] and "doesn't fit" in r["errors"][0]
    _, r = call(srv, "/api/player", {"id": "x", "club": "Smi, A.", "name": "Alex Smithers"})
    assert not r["ok"]
