"""The page server: access rules and the booking API, offline (no Task Scheduler, no club site)."""
import http.client
import json
import threading
from datetime import timedelta

import pytest

from wacbooker import clubtime, config, creds, scheduler, web


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    synced = []
    monkeypatch.setattr(scheduler, "sync", lambda cfg, pw=None, **k: synced.append((cfg, pw)) or scheduler.SyncResult(
        True, "Password" if (pw and cfg.run_signed_out) else "InteractiveToken",
        [b.name for b in cfg.bookings], [], [], ""))
    monkeypatch.setattr(scheduler, "status", lambda *a, **k: [])
    monkeypatch.setattr(scheduler, "wake_timers_on", lambda: True)
    vault = {}
    monkeypatch.setattr(creds, "set_password", lambda u, p: vault.__setitem__(u, p))
    monkeypatch.setattr(creds, "has_password", lambda u: u in vault)
    monkeypatch.setattr(creds, "delete_password", lambda u: vault.pop(u, None))
    # Logins start a club-site job; make it do nothing here.
    monkeypatch.setattr(web.WebApp, "_job_work", lambda self, kind, job, cfg, login, body: (lambda: True))
    s = web.Server(0)
    t = threading.Thread(target=s.serve, kwargs={"stop_when_idle": False}, daemon=True)
    t.start()
    s.synced, s.vault = synced, vault
    yield s
    s.httpd.shutdown()


def call(s, path, body=None, token=True, host=None):
    c = http.client.HTTPConnection("127.0.0.1", s.port_ref[0], timeout=10)
    h = {"Host": host or f"127.0.0.1:{s.port_ref[0]}"}
    if token:
        h["X-WACB-Token"] = s.token
    if body is None:
        c.request("GET", path, headers=h)
    else:
        h["Content-Type"] = "application/json"
        c.request("POST", path, body=json.dumps(body), headers=h)
    r = c.getresponse()
    data = r.read()
    try:
        return r.status, json.loads(data)
    except ValueError:
        return r.status, data


def add_login(s):
    st, r = call(s, "/api/login", {"username": "jsmith", "password": "pw-not-real"})
    assert r["ok"], r
    return r


def booking(**kw):
    b = {"play": "singles", "partners": ["Andrea Kronberg"], "weekly": True, "day": 1, "time": 18 * 60,
         "length": 90, "shorter_ok": True, "courts": [5, 4, "any"]}
    b.update(kw)
    return b


def test_page_and_api_need_the_right_host_and_token(srv):
    st, body = call(srv, "/", token=False)
    assert st == 200 and b"WAC Court Booker" in body
    assert call(srv, "/api/state", token=False)[0] == 403
    assert call(srv, "/api/state", host="evil.example:80")[0] == 403
    assert call(srv, "/", host=f"rebind.example:{srv.port_ref[0]}", token=False)[0] == 403
    assert call(srv, "/api/booking", {"x": 1}, token=False)[0] == 403
    st, state = call(srv, "/api/state")
    assert st == 200 and state["logins"] == [] and state["bookings"] == []


def test_add_login_keeps_password_out_of_the_file(srv, tmp_path):
    add_login(srv)
    assert srv.vault == {"jsmith": "pw-not-real"}
    text = (tmp_path / "bookings.yaml").read_text(encoding="utf-8")
    assert "jsmith" in text and "pw-not-real" not in text
    _, state = call(srv, "/api/state")
    assert state["logins"][0]["nickname"] == "me" and state["logins"][0]["has_password"]
    assert "pw-not-real" not in json.dumps(state)


def test_save_edit_pause_skip_remove(srv):
    add_login(srv)
    _, r = call(srv, "/api/booking", booking())
    assert r["ok"], r
    assert r["name"] == "Tue 6:00 PM singles with Andrea"
    _, state = call(srv, "/api/state")
    b = state["bookings"][0]
    assert b["title"] == "Every Tuesday, 6:00 to 7:30 PM"
    assert b["who"] == "Singles with Andrea Kronberg"
    assert b["courts_text"].startswith("Court 5, then 4, then any court")
    assert len(b["runs"]) == 2 and len(b["upcoming"]) == 8

    # Edit: the made-up name follows the change.
    _, r = call(srv, "/api/booking", booking(old_name=b["name"], day=3, time=8 * 60))
    assert r["ok"] and r["name"] == "Thu 8:00 AM singles with Andrea"

    _, r = call(srv, "/api/booking/pause", {"name": r["name"], "active": False})
    assert r["ok"]
    _, state = call(srv, "/api/state")
    b = state["bookings"][0]
    assert b["active"] is False and "Paused" in b["task"]["text"]

    d = b["upcoming"][1]["date"]
    _, r = call(srv, "/api/booking/skip", {"name": b["name"], "date": d, "skip": True})
    assert r["ok"]
    _, state = call(srv, "/api/state")
    assert state["bookings"][0]["skip"] == [d]
    _, r = call(srv, "/api/booking/skip", {"name": b["name"], "date": d, "skip": False})
    _, state = call(srv, "/api/state")
    assert state["bookings"][0]["skip"] == []

    _, r = call(srv, "/api/booking/remove", {"name": b["name"]})
    assert r["ok"]
    _, state = call(srv, "/api/state")
    assert state["bookings"] == []


def test_mistakes_come_back_in_plain_words(srv):
    add_login(srv)
    _, r = call(srv, "/api/booking", booking(partners=[]))
    assert not r["ok"] and "singles needs 1 partner" in r["errors"][0]
    _, r = call(srv, "/api/booking", booking(play="doubles"))
    assert not r["ok"] and "doubles needs 3 partners" in r["errors"][0]
    _, r = call(srv, "/api/booking", booking(time=18 * 60 + 15))
    assert not r["ok"] and "half hour" in r["errors"][0]
    soon = (clubtime.now_central() + timedelta(days=2)).date().isoformat()
    _, r = call(srv, "/api/booking", booking(weekly=False, date=soon))
    assert not r["ok"] and "Book Now" in r["errors"][0]
    # Two bookings at the same time on one login overlap.
    assert call(srv, "/api/booking", booking())[1]["ok"]
    _, r = call(srv, "/api/booking", booking(partners=["Pat Lee"]))
    assert not r["ok"] and "overlap" in r["errors"][0]


def test_no_booking_without_a_login(srv):
    _, r = call(srv, "/api/booking", booking())
    assert not r["ok"] and "login" in r["errors"][0]


def test_signed_out_runs_ask_for_the_windows_password(srv):
    add_login(srv)
    _, r = call(srv, "/api/settings", {"run_signed_out": True})
    assert r["ok"] and r["need_windows_password"]
    _, r = call(srv, "/api/windows-password", {"password": "win-not-real"})
    assert r["ok"] and r["signed_out"]
    assert srv.synced[-1][1] == "win-not-real"
    _, r = call(srv, "/api/booking", booking())
    assert r["ok"] and not r["need_windows_password"]
    _, state = call(srv, "/api/state")
    assert "win-not-real" not in json.dumps(state)


def test_remove_login_refused_while_bookings_use_it(srv):
    add_login(srv)
    call(srv, "/api/booking", booking())
    _, r = call(srv, "/api/login/remove", {"login": "me"})
    assert not r["ok"] and "use it" in r["errors"][0]


def test_also_login_saves_shows_and_cleans(srv):
    """'Also book for another login at the same time': its login and partners are saved,
    the My-bookings description says so, and leaving it out of an edit takes them out."""
    add_login(srv)
    st, r = call(srv, "/api/login", {"username": "jdoe", "password": "***"})
    assert st == 200 and r["ok"], r
    _, r = call(srv, "/api/booking", booking(play="doubles",
                                             partners=["Pat Lee", "Sam Ortiz", "Kim Park"],
                                             also="jdoe", also_partners=["A B", "C D", "E F"]))
    assert r["ok"], r
    _, state = call(srv, "/api/state")
    b = state["bookings"][0]
    assert b["who"] == "Doubles with Pat Lee, Sam Ortiz and Kim Park; also jdoe with A B, C D and E F"
    assert b["also"] == [{"login": "jdoe", "partners": ["A B", "C D", "E F"]}]
    _, r = call(srv, "/api/booking", booking(old_name=b["name"], play="doubles",
                                             partners=["Pat Lee", "Sam Ortiz", "Kim Park"]))
    assert r["ok"], r
    _, state = call(srv, "/api/state")
    b = state["bookings"][0]
    assert b["also"] == [] and b["who"] == "Doubles with Pat Lee, Sam Ortiz and Kim Park"


def test_also_not_saved_for_ball_machines(srv):
    add_login(srv)
    call(srv, "/api/login", {"username": "jdoe", "password": "***"})
    _, r = call(srv, "/api/booking", booking(play="machine", partners=[], courts=[2, 3, "any"],
                                             also="jdoe", also_partners=[]))
    assert not r["ok"] and "ball machine" in " ".join(r["errors"])


def test_then_booking_warns_when_the_second_task_is_missing(srv, monkeypatch):
    """The second session is its own scheduled task; without it nothing would ever book it."""
    add_login(srv)
    _, r = call(srv, "/api/booking", booking(day=4, then=60))
    assert r["ok"], r
    name = r["name"]
    main = {"name": scheduler.task_name(name), "logon": "InteractiveToken"}
    nxt = {"name": scheduler.task_name(name, "next"), "logon": "InteractiveToken"}
    monkeypatch.setattr(scheduler, "status", lambda *a, **k: [main])
    _, state = call(srv, "/api/state")
    b = state["bookings"][0]
    assert ", second session 60 min right after" in b["title"]
    assert b["task"]["ok"] is False and "Rebuild" in b["task"]["text"]
    monkeypatch.setattr(scheduler, "status", lambda *a, **k: [main, nxt])
    _, state = call(srv, "/api/state")
    b = state["bookings"][0]
    assert b["task"]["ok"] is True and "Scheduled" in b["task"]["text"]


def test_quit_stops_the_server(srv):
    _, r = call(srv, "/api/quit", {})
    assert r["ok"] and srv.app.stop_requested


def test_version_compare():
    assert web.parse_version("v0.1.10") > web.parse_version("0.1.9")
    assert web.parse_version("0.2.0") > web.parse_version("0.1.99")
    assert not web.parse_version("0.1.8") > web.parse_version("0.1.8")


def test_update_check_reads_the_latest_release(srv, monkeypatch):
    class R:
        def __init__(self, data):
            self.data = data

        def read(self):
            return json.dumps(self.data).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(web.urllib.request, "urlopen", lambda req, timeout=0: R({
        "tag_name": "v9.9.9", "html_url": "https://github.com/x/y/releases/tag/v9.9.9",
        "assets": [{"name": "wac-court-booker-9.9.9.zip", "browser_download_url": "https://example.invalid/z.zip"}]}))
    _, u = call(srv, "/api/update?force=1")
    assert u["newer"] and u["latest"] == "9.9.9" and u["download"].endswith(".zip")

    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(web.urllib.request, "urlopen", boom)
    _, u = call(srv, "/api/update?force=1")
    assert u["checked"] is False and u["newer"] is False and "GitHub" in u["error"]


def test_job_questions_wait_for_the_page(srv, monkeypatch):
    import time
    answers = []

    def work(self, kind, job, cfg, login, body):
        def run():
            job.say("Booked Ct 2.")
            answers.append(job.ask("Cancel this test booking now?", True))
            job.say("Cancelled.")
            return True
        return run
    monkeypatch.setattr(web.WebApp, "_job_work", work)
    # Adding a login starts a job; here it asks a question and waits.
    job_id = add_login(srv)["job"]["id"]
    for _ in range(50):
        _, j = call(srv, f"/api/job?id={job_id}")
        if j["job"]["question"]:
            break
        time.sleep(0.05)
    assert j["job"]["question"]["text"] == "Cancel this test booking now?"
    _, busy = call(srv, "/api/job", {"kind": "clock"})
    assert not busy["ok"] and "still running" in busy["errors"][0]
    call(srv, "/api/job/answer", {"id": job_id, "yes": False})
    for _ in range(50):
        _, j = call(srv, f"/api/job?id={job_id}")
        if j["job"]["done"]:
            break
        time.sleep(0.05)
    assert j["job"]["done"] and j["job"]["ok"] and answers == [False]
    assert j["job"]["lines"] == ["Booked Ct 2.", "Cancelled."]


def test_desktop_shortcut_points_at_the_window(srv, monkeypatch, tmp_path):
    exe = tmp_path / "Scripts" / "wac-booker-web.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    link = tmp_path / "Desktop" / "WAC Court Booker.lnk"
    link.parent.mkdir()
    monkeypatch.setattr(web, "web_exe", lambda: exe)
    monkeypatch.setattr(web, "desktop_shortcut_path", lambda: link)
    seen = {}

    def fake_run(cmd, env=None, **k):
        seen.update(env)
        link.write_bytes(b"lnk")
        return web.subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(web.subprocess, "run", fake_run)
    monkeypatch.setattr(scheduler, "pwsh", lambda: "pwsh")
    assert call(srv, "/api/state")[1]["settings"]["desktop_shortcut"] is False
    _, r = call(srv, "/api/desktop-shortcut", {})
    assert r["ok"], r
    assert seen["WACB_TARGET"] == str(exe) and seen["WACB_LNK"] == str(link)
    assert (tmp_path / "desktop-shortcut.txt").read_text().strip() == "Yes"
    assert call(srv, "/api/state")[1]["settings"]["desktop_shortcut"] is True
