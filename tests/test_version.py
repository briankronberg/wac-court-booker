import re
from pathlib import Path

import wacbooker


def test_versions_match():
    text = (Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "([^"]+)"', text, re.M).group(1) == wacbooker.__version__
