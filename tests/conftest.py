import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from wacbooker import web  # noqa: E402

# The srv fixture (test_web) stubs WebApp._job_work for each test. Capturing the
# real method has to happen before any fixture runs: a conftest import is the
# only point guaranteed to run first. (A module-level capture in a test file only
# beats the stub if that file is collected before any test that imports it.)
REAL_JOB_WORK = web.WebApp._job_work
