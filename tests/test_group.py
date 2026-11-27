"""Coordinated logins: Group hands every member a court, side by side when the sheet allows."""
from fakes import booking as fake_booking

from wacbooker.config import Booking
from wacbooker.engine import Slot
from wacbooker.group import Group


def slot(court, length=90):
    return Slot("12/15/2026", 18 * 60, length, court)


def open_map(*courts, length=90):
    return {length: {c: slot(c, length) for c in courts}}


def b(courts=None):
    if courts is None:
        return fake_booking()
    return Booking(**{**fake_booking().__dict__, "courts": courts})


def test_two_members_take_a_block_of_two():
    g = Group(2)
    got = [g.chooser(i)(open_map(5, 6), b(), set()) for i in range(2)]
    assert [x.court for x in got] == [5, 6]
    assert g.want == {0: 5, 1: 6}


def test_a_pair_beats_a_lone_named_court():
    # 5, 8 and 9 open with prefs [5, any]: the side-by-side pair 8+9 beats the lone 5
    g = Group(2)
    got = [g.chooser(i)(open_map(5, 8, 9), b([5, "any"]), set()) for i in range(2)]
    assert sorted(x.court for x in got) == [8, 9]


def test_one_court_open_only_one_books():
    g = Group(2)
    got0 = g.chooser(0)(open_map(4), b(), set())
    got1 = g.chooser(1)(open_map(4), b(), set())
    assert got0.court == 4
    assert got1 is None
    assert g.want == {0: 4}


def test_three_members_take_a_block_of_three():
    g = Group(3)
    got = [g.chooser(i)(open_map(3, 4, 5), b(), set()) for i in range(3)]
    assert sorted(x.court for x in got) == [3, 4, 5]


def test_a_member_takes_a_court_next_to_the_others():
    g = Group(2)
    first = g.chooser(0)(open_map(2, 4, 5), b(), set())
    second = g.chooser(1)(open_map(2, 4, 5), b(), set())
    assert (first.court, second.court) == (5, 4)


def test_tried_pairs_are_dropped():
    g = Group(1)
    got = g.chooser(0)(open_map(5, 4), b([5, 4, "any"]), {(5, 90)})
    assert got.court == 4


def test_falls_back_to_a_shorter_length():
    g = Group(1)
    ob = {90: {}, 60: {4: slot(4, 60)}}
    got = g.chooser(0)(ob, b(), set())
    assert (got.court, got.length) == (4, 60)


def test_release_gives_the_court_back():
    g = Group(2)
    g.chooser(0)(open_map(5, 6), b(), set())
    g.release(0)
    got = g.chooser(0)(open_map(5, 6), b(), set())
    assert got.court == 5
    assert g.want == {0: 5}
