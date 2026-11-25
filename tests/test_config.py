from datetime import date

from wacbooker import config
from wacbooker.config import Booking, Login

GOOD = """\
# my own comment, keep me
browser: hidden
show_window: false
run_signed_out: false
logins:
  - nickname: me
    username: jsmith
  - nickname: partner
    username: asmith
bookings:
  - name: Tuesday doubles
    login: me
    play: doubles
    partners: [Pat Lee, Sam Ortiz, Kim Park]
    day: Tuesday
    time: "6:00 PM"
    length: 90
    shorter_ok: true
    courts: [5, 4, 3, any]
    skip: [2027-12-22]
    active: true
"""


def load_text(tmp_path, text):
    p = tmp_path / "bookings.yaml"
    p.write_text(text, encoding="utf-8")
    return p, *config.load(p)


def test_good_file_loads(tmp_path):
    _, doc, cfg = load_text(tmp_path, GOOD)
    assert cfg.ok, cfg.errors
    b = cfg.bookings[0]
    assert (b.day, b.time, b.length, b.courts) == (1, 1080, 90, [5, 4, 3, "any"])
    assert b.lengths == [90, 60, 30]
    assert b.skip == [date(2027, 12, 22)]


def test_template_loads_clean(tmp_path):
    doc, cfg = config.load(tmp_path / "missing.yaml")
    assert cfg.ok and not cfg.bookings and not cfg.logins


def errors_for(tmp_path, old, new):
    _, _, cfg = load_text(tmp_path, GOOD.replace(old, new))
    return " | ".join(cfg.errors)


def test_plain_word_errors(tmp_path):
    assert "'any' can only come last" in errors_for(tmp_path, "[5, 4, 3, any]", "[5, any, 3]")
    assert "no court 7" in errors_for(tmp_path, "[5, 4, 3, any]", "[7]")
    assert "doubles needs 3 partners" in errors_for(tmp_path, "[Pat Lee, Sam Ortiz, Kim Park]", "[Pat Lee]")
    assert "length must be 30, 60 or 90" in errors_for(tmp_path, "length: 90", "length: 45")
    assert "isn't a day" in errors_for(tmp_path, "day: Tuesday", "day: Funday")
    assert "half hour" in errors_for(tmp_path, '"6:00 PM"', '"6:15 PM"')
    assert "isn't a setting I know" in errors_for(tmp_path, "active: true", "actve: true")
    assert "no login called" in errors_for(tmp_path, "login: me", "login: nobody")
    assert "not both" in errors_for(tmp_path, "day: Tuesday", "day: Tuesday\n    date: 2027-01-05")


def test_yaml_syntax_error_is_explained(tmp_path):
    _, doc, cfg = load_text(tmp_path, "bookings: [\n  - x: : :\n")
    assert doc is None and "can't be read" in cfg.errors[0]


def test_overlap_on_same_login_is_an_error(tmp_path):
    extra = GOOD + """\
  - name: Tuesday singles
    login: me
    play: singles
    partners: [Pat Lee]
    day: Tuesday
    time: "7:00 PM"
    length: 60
    courts: [5]
"""
    _, _, cfg = load_text(tmp_path, extra)
    assert any("overlap" in e for e in cfg.errors)
    _, _, cfg = load_text(tmp_path, extra.replace("login: me\n    play: singles", "login: partner\n    play: singles"))
    assert cfg.ok, cfg.errors


def test_more_than_two_a_day_is_a_warning(tmp_path):
    text = GOOD
    for i, t in enumerate(("8:00 AM", "10:00 AM")):
        text += f"""\
  - name: extra {i}
    login: me
    play: singles
    partners: [Pat Lee]
    day: Tuesday
    time: "{t}"
    length: 60
    courts: [5]
"""
    _, _, cfg = load_text(tmp_path, text)
    assert cfg.ok
    assert any("2 per login per day" in w for w in cfg.warnings)


def test_edits_keep_comments_and_round_trip(tmp_path):
    p, doc, cfg = load_text(tmp_path, GOOD)
    b = cfg.bookings[0]
    b2 = Booking(**{**b.__dict__, "name": "Thu singles", "play": "singles", "partners": ["Pat Lee"],
                    "day": 3, "courts": [8, "any"], "skip": []})
    config.put_booking(doc, b2)
    b.length = 60
    config.put_booking(doc, b, replace="Tuesday doubles")
    config.put_login(doc, Login("third", "csmith"))
    config.save(doc, p)
    text = p.read_text(encoding="utf-8")
    assert "# my own comment, keep me" in text
    _, cfg2 = config.load(p)
    assert cfg2.ok, cfg2.errors
    assert [x.name for x in cfg2.bookings] == ["Tuesday doubles", "Thu singles"]
    assert cfg2.bookings[0].length == 60
    assert cfg2.login("third").username == "csmith"
    assert config.remove_booking(doc, "Thu singles")
    assert config.remove_login(doc, "third")
    config.save(doc, p)
    _, cfg3 = config.load(p)
    assert [x.name for x in cfg3.bookings] == ["Tuesday doubles"]


def test_next_runs_skip_dates(tmp_path):
    from wacbooker import clubtime
    _, _, cfg = load_text(tmp_path, GOOD.replace("[2027-12-22]", "[2026-12-15]"))
    b = cfg.bookings[0]
    runs = b.next_runs(clubtime.slot_start(date(2026, 12, 1), 0), count=2)
    assert [r.day for r in runs] == [date(2026, 12, 8), date(2026, 12, 22)]
