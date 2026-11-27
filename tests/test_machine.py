"""Ball machine bookings: the setting, Prime Time, finding a machine and a court, staging (offline)."""
import asyncio
import json
from datetime import timedelta

from wacbooker import config, engine, site as S

from test_availability import FakeApi, table
from test_web import add_login, call, srv  # noqa: F401  (fixture)


def parse(**kw):
    raw = {"name": "m", "login": "me", "play": "machine", "partners": [], "day": "Saturday",
           "time": "7:00 AM", "length": 60, "courts": [8, "any"]}
    raw.update(kw)
    errs = []
    return config.parse_booking(raw, 1, errs), errs


def test_machine_setting():
    b, errs = parse(machine="genie")
    assert not errs and b.machine == "genie" and b.what == "Genie ball machine" and b.site_play == "machine:genie"
    b, errs = parse()
    assert not errs and b.machine == "either" and b.site_play == "machine:either"
    assert parse(machine="robot")[1]
    assert "just you" in parse(partners=["Pat Lee"])[1][0]
    assert "doesn't take a ball machine" in parse(courts=[4])[1][0]
    assert "only for play: machine" in parse(play="singles", partners=["Pat Lee"], machine="genie")[1][0]
    b, _ = parse(machine="regular")
    m = config.booking_to_map(b)
    assert m["machine"] == "regular" and list(m["partners"]) == []
    assert config.auto_name("machine", [], 5, None, 420, [], "genie") == "Sat 7:00 AM Genie ball machine"
    assert config.auto_name("machine", [], 5, None, 420, [], "either") == "Sat 7:00 AM ball machine"


def test_machine_prime_time_books_a_day_ahead():
    b, _ = parse(day="Tuesday", time="6:00 PM")
    assert b.prime_kind == "all" and b.part().lead == timedelta(hours=24)
    b, _ = parse(day="Monday", time="8:30 AM", length=60)
    assert b.prime_kind == "split"
    assert parse()[0].prime_kind == "none"


def test_find_machine_prefers_the_genie():
    site = FakeApi(table())
    got = asyncio.run(site.find_open("12/04/2026", 600, [60], "machine:either"))
    assert sorted(got[60]) == [2, 3, 8, 9, 10]
    assert {s.provider for s in got[60].values()} == {"442"}
    # 7:00 AM: the Genie is out, so "either" takes the regular machine; "genie" finds nothing.
    got = asyncio.run(site.find_open("12/04/2026", 420, [30], "machine:either"))
    assert {s.provider for s in got[30].values()} == {"121"}
    assert asyncio.run(site.find_open("12/04/2026", 420, [30], "machine:genie"))[30] == {}


def test_machine_service_follows_prime_time():
    # 12/04/2026 is a Friday: 9:00-10:30 AM is Prime Time, the evening isn't.
    assert S.machine_service("genie", "12/04/2026", 540, 60)[1] == S.MACHINES["genie"]["services"][1][1]
    assert S.machine_service("genie", "12/04/2026", 1080, 60)[1] == S.MACHINES["genie"]["services"][0][1]
    assert S.machine_service("regular", "12/05/2026", 540, 60)[2] == 113  # Saturday


def test_stage_machine_sends_what_the_club_page_sends():
    site = FakeApi({**table(), "SetScheduleInformation": None})
    went = []

    async def goto(url, timeout=90):
        went.append(url)

    async def loaded(slot, timeout):
        return True
    site.goto, site._family_loaded = goto, loaded
    slot = asyncio.run(site.find_open("12/04/2026", 600, [60], "machine:genie"))[60][10]
    asyncio.run(site.stage(slot))
    payload = [p for m, p in site.calls if m == "SetScheduleInformation"][0]
    info = json.loads(payload["scheduleInformation"])
    assert payload["startTime"] == "600"
    assert info == {"ScheduleDate": "12/04/2026", "Duration": 60, "Resource": "Tennis court ten",
                    "Provider": "Genie M.", "SiteId": "758", "ProviderId": "442", "ResourceId": "98",
                    "ServiceId": 1064, "ServiceName": "3.01 Genie Ball Machine",
                    "ServiceUniqueIdentifier": "8f3e617f-fe3a-496b-8203-75c5dc6b4c93"}
    assert went == [S.FAMILY_URL] and site.staged == slot and "Genie" in slot.describe()


def test_stage_machine_refuses_a_taken_machine():
    site = FakeApi({**table(), "SetScheduleInformation": None})
    slot = engine.Slot("12/04/2026", 420, 30, 8, "96", S.MACHINES["genie"]["services"][0][1], "442")
    try:
        asyncio.run(site.stage(slot))
    except engine.SiteError as e:
        assert e.kind == "taken"
    else:
        raise AssertionError("staged a taken machine")
    assert not [m for m, _ in site.calls if m == "SetScheduleInformation"]


def test_save_a_machine_booking_from_the_page(srv):  # noqa: F811
    add_login(srv)
    body = {"play": "machine", "machine": "genie", "partners": [], "weekly": True, "day": 5, "time": 420,
            "length": 60, "shorter_ok": False, "courts": [8, "any"]}
    _, r = call(srv, "/api/booking", body)
    assert r["ok"], r
    _, st = call(srv, "/api/state")
    b = st["bookings"][0]
    assert b["name"] == "Sat 7:00 AM Genie ball machine" and b["machine"] == "genie" and b["who"] == "Genie ball machine"
    _, r = call(srv, "/api/booking", {**body, "courts": [4]})
    assert not r["ok"] and "doesn't take a ball machine" in r["errors"][0]


def test_engine_asks_the_site_for_the_machine():
    b, _ = parse(machine="genie")
    seen = []

    class Site:
        async def find_open(self, date, start, lengths, play):
            seen.append(play)
            return {}
    from fakes import occurrence
    eng = engine.Engine(b, occurrence(), Site(), engine.RealClock())
    assert asyncio.run(eng.choose()) is None and seen == ["machine:genie"]
