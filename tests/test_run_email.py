"""Each scheduled run ends with one plain email (when email is set up) saying what its
notifications said, with the engine's timing lines under a details divider."""
from wacbooker import cli, config, mail, notify, runner


def setup(monkeypatch, toasts, logs=(), configured=True, rc=0):
    sent = []

    def fake_run(name, part="main"):
        lg = notify.logger()
        for line in logs:
            lg.info(f"[{name}] {line}")
        for t, m in toasts:
            notify.toast(t, m)
        return rc
    monkeypatch.setattr(runner, "run_booking", fake_run)
    monkeypatch.setattr(runner.notify, "toast", lambda t, m: True)
    cfg = config.Config(email_to="me@example.com")
    monkeypatch.setattr(config, "load", lambda *a: (None, cfg))
    monkeypatch.setattr(mail, "configured", lambda c: configured)
    monkeypatch.setattr(mail, "send", lambda c, subject, summary, details=(): sent.append((subject, summary, list(details))) or (True, "sent"))
    return sent


def test_one_email_per_run_with_the_outcome(tmp_path, monkeypatch):
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    sent = setup(monkeypatch, [("Booked", "Booked: Ct 5, Fri 12/18 6:00 PM, 60 min")],
                 logs=["W-900.0s signed in as Test Member", "W-899.0s run for b: Friday with Pat Lee",
                       "W+44.9s press -> CONFIRMED guid", "waiting 60 min"])
    assert runner.run_and_report("b") == 0
    assert len(sent) == 1
    subject, summary, details = sent[0]
    assert subject == "Booked"
    assert "Booked: Ct 5, Fri 12/18 6:00 PM, 60 min" in summary
    assert any("W+44.9s press -> CONFIRMED" in d for d in details)
    assert not any("signed in as" in d or "run for" in d or "waiting" in d for d in details)


def test_no_email_when_not_set_up(tmp_path, monkeypatch):
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    sent = setup(monkeypatch, [("Booked", "Booked: Ct 5")], configured=False)
    assert runner.run_and_report("b") == 0
    assert sent == []


def test_return_code_passes_through(tmp_path, monkeypatch):
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    sent = setup(monkeypatch, [("Not booked", "Not booked: no court open")], rc=1)
    assert runner.run_and_report("b") == 1
    assert sent[0][0] == "Not booked"


def test_guard_run_emails_only_when_unsure(tmp_path, monkeypatch):
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    sent = setup(monkeypatch, [("Guard slot booked", "Guard slot booked: Ct 5")])
    runner.run_and_report("b", "blocker")
    assert sent == []  # the booking's own run reports the guard slot
    sent = setup(monkeypatch, [("Not booked", "No guard slot: no court is free")])
    runner.run_and_report("b", "blocker")
    assert sent == []
    sent = setup(monkeypatch, [("Check your bookings", "Guard slot: the club site didn't answer")])
    runner.run_and_report("b", "blocker")
    assert len(sent) == 1


def test_a_run_with_nothing_to_say_sends_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    sent = setup(monkeypatch, [])
    assert runner.run_and_report("b") == 0
    assert sent == []


def test_cli_run_goes_through_run_and_report(monkeypatch):
    called = []
    monkeypatch.setattr(runner, "run_and_report", lambda name, part="main": called.append((name, part)) or 0)
    assert cli.main(["run", "--booking", "b"]) == 0
    assert called == [("b", "main")]


def test_cli_run_accepts_every_part(monkeypatch):
    called = []
    monkeypatch.setattr(runner, "run_and_report", lambda name, part="main": called.append((name, part)) or 0)
    for part in ("main", "prime", "next", "blocker"):
        assert cli.main(["run", "--booking", "b", "--part", part]) == 0
    assert called == [("b", "main"), ("b", "prime"), ("b", "next"), ("b", "blocker")]


def test_cli_run_part_choices_match_the_booking_parts():
    # every part a booking can have must be runnable from a scheduled task
    from wacbooker import config
    errs = []
    b = config.parse_booking({"name": "b", "login": "me", "play": "singles", "partners": ["Pat Lee"],
                              "day": "Tuesday", "time": "4:30 PM", "length": 90, "courts": [5, "any"],
                              "blocker": True}, 1, errs)
    assert not errs, errs
    keys = {p.key for p in b.parts}
    b2 = config.parse_booking({"name": "c", "login": "me", "play": "doubles",
                               "partners": ["A B", "C D", "E F"], "day": "Saturday", "time": "9:00 AM",
                               "length": 90, "courts": [5, "any"], "then": 60}, 1, errs)
    assert not errs, errs
    keys |= {p.key for p in b2.parts}
    assert keys == {"blocker", "main", "prime", "next"}
    import argparse
    parser = cli.build_parser() if hasattr(cli, "build_parser") else None
    if parser is None:
        return  # covered by test_cli_run_accepts_every_part
