import os
import time

from wacbooker import site


def test_sweep_removes_only_old_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("WACB_HOME", str(tmp_path))
    root = tmp_path / "profiles"
    old = root / "edge-old"
    new = root / "edge-new"
    old.mkdir(parents=True)
    new.mkdir()
    two_days_ago = time.time() - 2 * 86400
    os.utime(old, (two_days_ago, two_days_ago))

    assert site.sweep_profiles() == 1
    assert not old.exists()
    assert new.exists()
