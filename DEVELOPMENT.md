# Developing WAC Court Booker

For working on the app. None of this is in the release zip; users get only the app, setup and README.md.

## Setup and unit tests

```powershell
pwsh -NoProfile -File setup.ps1 -Dev -NoWizard     # editable install into %LOCALAPPDATA%\WAC Court Booker
& "$env:LOCALAPPDATA\WAC Court Booker\venv\Scripts\python.exe" -m pip install pytest
& "$env:LOCALAPPDATA\WAC Court Booker\venv\Scripts\python.exe" -m pytest
```

The tests run offline: the booking engine is tested against a fake club site and a fake clock (`tests/fakes.py`).

To test a clean install, use Windows Sandbox (the Windows feature must be on):

```powershell
pwsh -NoProfile -File tests\sandbox\run-sandbox-test.ps1
```

It zips the working tree the way a release is laid out, then starts a throwaway sandbox that has no PowerShell 7, Python or winget. There it runs `setup.cmd -NoWizard` in a visible window, followed by the self-test (browser and toast), `check`, `rebuild-tasks`, a run started by Task Scheduler, the console menu, the app's page server (page, token check, booking list, quit), a second setup with the Start-menu shortcut's target, and the unit tests. It never signs in to the club: the sandbox's only login has no password. Results go to `.sandbox\<time>\out\`, with a summary in `report.json`. `-Zip <file>` tests a downloaded release instead, and `-KeepOpen` leaves the sandbox open afterwards. `-Reuse` updates a sandbox that a `-KeepOpen` or `-HandsOn` run left open: it installs the new build with `setup.cmd`, then reruns the checks (including the signed-in ones if a login was typed in). That takes about a minute instead of 11, but it doesn't retest a first install, so do a clean run before a release. `-HandsOn` runs setup without -NoWizard, so the app's page opens in the sandbox; when it prints READY, a person adds a club login there; it then also runs the signed-in checks, all read-only (sign-in, buddy list, clock, and a dry run on a paused booking). The password stays in the sandbox's own Credential Manager and is gone when the sandbox closes. The logs in `out\` hold names, so keep them private. The test harness may only do what a user would do: anything a clean PC needs belongs in setup. Set `WACB_HOME` to use a scratch folder and `WACB_TASK_FOLDER` (for example `\WAC Court Booker\Test\`) to keep test tasks apart from real ones.

Release: bump the version, record it in CHANGELOG.md, merge to `main`, then `git archive --format=zip --prefix=wac-court-booker-<version>/ -o dist\wac-court-booker-<version>.zip v<version>` on the tag, and attach the zip to a GitHub release (`gh release create`). The zip leaves out what .gitattributes marks export-ignore (tests, docs, this file, CHANGELOG.md), so users see only the app, setup, README.md and DESIGN.md. Release notes say what changed for the user: install steps and features, nothing about testing.

Rules: never run a real booking or cancel without the account holder's OK for that run; never print or log passwords. Keep `pyproject.toml` and `wacbooker/__init__.py` on the same version and record changes in [CHANGELOG.md](CHANGELOG.md).

## The app's page

`wacbooker/web.py` is a small server on 127.0.0.1 (Python's standard library only) and `wacbooker/web/index.html` is the whole page. The plan and its reasoning are in docs/web-ui.md. To work on it with made-up data, use a scratch folder and a test task folder:

```powershell
$env:WACB_TASK_FOLDER = '\WAC Court Booker\Test\'
python -m wacbooker --home .sandbox\webdemo web --no-open --port 8765
```

It prints the address to open (the key is in the `#t=` part). Delete the tasks in `\WAC Court Booker\Test\` afterwards. `tests/test_web.py` covers the API offline.
