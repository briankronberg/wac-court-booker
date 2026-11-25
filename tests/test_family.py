from wacbooker import runner
from wacbooker.site import family_from

# Cells as the participants page's member table gives them: Name, Relationship.
CELLS = [["Pat Member", "Main"], ["Alex Member", "Spouse"], ["Sam Member", "Child"],
         ["Lee Buddy", "Buddy"], ["Alex Member", "Buddy"], ["", "Buddy"]]


def test_family_is_everyone_but_main_and_buddies():
    assert family_from(CELLS, "Pat Member") == ["Alex Member", "Sam Member"]


def test_no_member_table_means_no_family():
    assert family_from([], "Pat Member") == []
    assert family_from(None, "") == []


def test_save_buddies_keeps_family_and_names_apart(tmp_path, monkeypatch):
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    runner.save_buddies("me", ["Lee Buddy"])
    assert runner.load_family("me") is None
    runner.save_buddies("me", family=["Alex Member"])
    runner.save_buddies("me", ["Lee Buddy", "Kim Buddy"])
    data = runner.load_buddies()["me"]
    assert data["names"] == ["Lee Buddy", "Kim Buddy"]
    assert runner.load_family("me") == ["Alex Member"]


class _Site:
    family = ["Alex Member"]


def test_keep_family_saves_what_a_session_saw(tmp_path, monkeypatch):
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    from wacbooker.config import Login
    runner.keep_family(Login("me", "u"), _Site())
    assert runner.load_family("me") == ["Alex Member"]
    runner.keep_family(Login("me", "u"), object())  # a session that never staged changes nothing
    assert runner.load_family("me") == ["Alex Member"]
