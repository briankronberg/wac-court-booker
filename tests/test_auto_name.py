from datetime import date

from wacbooker.config import auto_name


def test_weekly_singles():
    assert auto_name("singles", ["Andrea Kronberg"], 1, None, 18 * 60) == "Tue 6:00 PM singles with Andrea"


def test_one_off_doubles_uses_first_names():
    name = auto_name("doubles", ["Pat Lee", "Sam Ortiz", "Kim Park"], None, date(2026, 12, 19), 8 * 60 + 30)
    assert name == "Sat 12/19 8:30 AM doubles with Pat, Sam, Kim"


def test_clash_gets_a_number_case_insensitively():
    taken = ["Tue 6:00 PM singles with Andrea", "tue 6:00 pm singles with andrea (2)"]
    assert auto_name("singles", ["Andrea Kronberg"], 1, None, 18 * 60, taken) == \
        "Tue 6:00 PM singles with Andrea (3)"


def test_no_partners_yet():
    assert auto_name("singles", [], 0, None, 7 * 60) == "Mon 7:00 AM singles"
