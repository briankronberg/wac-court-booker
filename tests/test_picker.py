from wacbooker import picker
from wacbooker.picker import BACK, DOWN, END, ENTER, ESC, HOME, OTHER, PGDN, UP, PickState

NAMES = ["Andrea Kronberg", "Pat Lee", "Sam Ortiz", "Kim Park", "Lee Andrews"]


def keys(st, *ks):
    for k in ks:
        st.key(k)
    return st


def test_enter_picks_highlighted_name():
    st = keys(PickState(NAMES), DOWN, ENTER)
    assert st.done and st.result == "Pat Lee"


def test_up_stops_at_top_and_down_stops_at_other():
    st = keys(PickState(NAMES), UP, UP)
    assert st.cursor == 0
    st = keys(PickState(NAMES), *[DOWN] * 20, ENTER)
    assert st.result == OTHER


def test_typing_narrows_case_insensitive_and_by_words():
    st = keys(PickState(NAMES), *"lee")
    assert st.shown() == ["Pat Lee", "Lee Andrews", OTHER]
    st = keys(PickState(NAMES), *"and kro")
    assert st.shown() == ["Andrea Kronberg", OTHER]
    assert keys(st, ENTER).result == "Andrea Kronberg"


def test_backspace_widens_again():
    st = keys(PickState(NAMES), *"zz")
    assert st.shown() == [OTHER]
    keys(st, BACK, BACK)
    assert len(st.shown()) == len(NAMES) + 1


def test_no_match_still_offers_other():
    st = keys(PickState(NAMES), *"nobody", ENTER)
    assert st.result == OTHER


def test_esc_returns_none():
    st = keys(PickState(NAMES), DOWN, ESC)
    assert st.done and st.result is None


def test_scrolling_keeps_cursor_in_window():
    many = [f"Player {i:02d}" for i in range(40)]
    st = PickState(many, rows=10)
    keys(st, PGDN, PGDN)
    assert st.top <= st.cursor < st.top + st.rows
    keys(st, END)
    assert st.shown()[st.cursor] == OTHER and st.top + st.rows == len(st.shown())
    keys(st, HOME)
    assert st.cursor == 0 and st.top == 0


def test_not_available_when_piped(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    assert picker.available() is False
