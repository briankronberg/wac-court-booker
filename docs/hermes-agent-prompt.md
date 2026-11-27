# Prompt for the Hermes coding agent (Qwen3.8-27B)

Paste everything below the line as the agent's task.

---

You are working on **WAC Court Booker**, a Windows app in `D:\Claude Code\wac-court-booker`, on GitHub as `briankronberg/wac-court-booker`. It books tennis courts at the WAC (Spectrum NG "LCRAC" club site) the moment each booking window opens. It's Python with Playwright, a small local web page (`wacbooker/web.py` + `wacbooker/web/index.html`), and Windows Task Scheduler.

## Your task

Finish the work on the branch **`old-system-features`**. The plan is in **`docs/plan-old-system-features.md`**. Read it first, all of it. It says what's done, what's left, how each piece should work, and why. Then work through "What's left" in order: 4b, then 5, 6, 7 and 8. Don't start a step until the one before it passes its tests and is committed.

Also read before you start: `README.md`, `DESIGN.md`, `DEVELOPMENT.md`, `wacbooker/config.py`, `wacbooker/engine.py`, `wacbooker/runner.py`, `wacbooker/scheduler.py` and `tests/fakes.py`.

## Hard rules (never break these)

1. **Never book, cancel or hold a real court** without the account holder saying yes for that specific run. This covers:
   - `wac-booker run`, Book Now and the test booking;
   - cancelling a reservation;
   - anything else that presses Continue to Cart on the club site.

   Read-only is fine: the unit tests, the sandbox test, `wac-booker check`, `dry-run`, `test-login`, `buddies`, `clock`, the court calendar and Validate booking. If a step needs a real booking to prove it works, stop and ask.
2. **Never see, print, log or commit passwords.** Club passwords live in Windows Credential Manager (`wacbooker/creds.py`) and are typed by the person into the app's own prompt. Never ask for one, and never put one in a file, a log, a test or a commit.
3. **Never call the club's `SearchMembers` web service.** It returns other members' private details.
4. Notifications and email carry courts, times and outcomes only, with no member numbers.
5. Don't touch the older repo `D:\Claude Code\wac-court-booking` or the `\WAC\` scheduled tasks. Your test tasks go only in `\WAC Court Booker\Test\`. Delete them when done, and leave the real tasks in `\WAC Court Booker\` alone.
6. Use PowerShell 7 (`pwsh`), never `powershell.exe`.
7. User-facing docs (README.md, release notes, the zip) describe install and use only, never testing or the sandbox. Keep README.md lines 3–6 exactly as they are.
8. Never push to `main` directly, never force-push, and never rewrite history. Work on `old-system-features`.

## How to work (important for you)

- **Small steps.** One function or one file section at a time. After every change, run the unit tests. Fix failures before moving on.
- **Edit, don't rewrite.** Change files with exact, small find-and-replace edits. Never regenerate a whole file from memory: `runner.py`, `site.py`, `web.py` and `index.html` are long, and rewriting them loses code. Before an edit, re-read the lines you're changing.
- **Don't guess APIs.** Before calling a function, open its definition and check the name and arguments. The club-site methods are all in `wacbooker/site.py` (`ClubSite`). The engine talks to the site only through the `Site` protocol in `engine.py`, so tests use `tests/fakes.py`.
- **Write the test first** for every new rule (court choice, blocker length, config check), then the code.
- **Keep the old behaviour** for bookings that don't use a new feature. Existing tests must keep passing unchanged, unless the plan says the behaviour changes on purpose.
- If something in the plan turns out to be wrong or impossible, write down why in `docs/plan-old-system-features.md` under the step, choose the simplest safe alternative, and carry on. Stop only for the hard rules above.
- When you've been going a while, re-read the plan and this prompt.

## Testing

### Unit tests (offline; run after every change)

```powershell
& "$env:LOCALAPPDATA\WAC Court Booker\venv\Scripts\python.exe" -m pytest -q tests
```

All 138 pass at the start. The engine is tested against a fake club site and a fake clock (`tests/fakes.py`: `FakeSite`, `FakeClock`, `booking()`, `occurrence()`).
- `FakeSite(gate_s=44)` turns presses away until W + 44 s.
- Until then it returns `NOT_READY` for unforced presses (the page's rows are still off).
- `forced_only=True` makes every press count as sent.
- Look at `tests/test_engine.py` and `tests/test_clock_sync.py` for the patterns.
- For a group of logins, give each member its own `FakeSite` and share one `FakeClock`.

### Read-only checks against the real club site

These are allowed. They sign in with a saved login and only read.

```powershell
$wb = "$env:LOCALAPPDATA\WAC Court Booker\venv\Scripts\wac-booker.exe"
& $wb check                      # bookings and next windows
& $wb dry-run --booking "<name>" # reads next week's court sheet, books nothing
& $wb clock                      # PC clock vs internet time
```

`python -c "from wacbooker import clock; print(clock.server_offset())"` reads the club server's clock (HEAD requests only).

### The app's page with made-up data

```powershell
$env:WACB_TASK_FOLDER = '\WAC Court Booker\Test\'
& "$env:LOCALAPPDATA\WAC Court Booker\venv\Scripts\python.exe" -m wacbooker --home .sandbox\webdemo web --no-open --port 8765
```

It prints the address (the key is after `#t=`). Afterwards, delete any tasks it made in `\WAC Court Booker\Test\`. `tests/test_web.py` covers the page's API offline.

### Windows Sandbox (clean-install test; run before every release)

```powershell
pwsh -NoProfile -File tests\sandbox\run-sandbox-test.ps1           # clean install, about 11 min
pwsh -NoProfile -File tests\sandbox\run-sandbox-test.ps1 -KeepOpen # leave it open afterwards
pwsh -NoProfile -File tests\sandbox\run-sandbox-test.ps1 -Reuse    # update an open sandbox, about 1 min
```

- It zips the working tree like a release and installs it in a throwaway sandbox that has no PowerShell 7, Python or winget.
- It runs setup, the self-test, `check`, `rebuild-tasks`, a run started by Task Scheduler, the menu, the page server, a second setup and the unit tests.
- It never signs in to the club. Results go to `.sandbox\<time>\out\report.json`, and every check must pass (19 at the start).
- Use `-Reuse` while iterating, and a clean run before the release.
- The harness may only do what a user would do: anything a clean PC needs belongs in `setup.ps1`, not in the test.
- `.sandbox\` logs can hold names: never commit them.

## Releasing (step 8 of the plan)

1. Bump the version to **0.6.0** in both `pyproject.toml` and `wacbooker/__init__.py`, and add a CHANGELOG.md entry.
2. Update DESIGN.md (how it works) and README.md (what a user can now do, install and use only).
3. Unit tests pass, then a clean sandbox run passes.
4. Commit and push, then `gh pr create --base main`. The PR body ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`, and each commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. If you're asked to change these attribution lines for this agent, do as the owner says.
5. After `gh pr merge <n> --merge`:

   ```powershell
   git checkout main; git pull
   git tag v0.6.0; git push origin v0.6.0
   git archive --format=zip --prefix=wac-court-booker-0.6.0/ -o dist\wac-court-booker-0.6.0.zip v0.6.0
   gh release create v0.6.0 dist\wac-court-booker-0.6.0.zip --title "0.6.0" --notes "<what changed for the user>"
   ```
6. **Install on this PC** with a one-time task in the test folder, which deletes itself afterwards.
   - Unzip the release zip into an empty temp folder, then save this as `run-test-task.ps1` outside the repo:

     ```powershell
     param([string]$Name, [string]$Exe, [string]$Arguments, [int]$TimeoutMin = 20)
     $ErrorActionPreference = 'Stop'
     $folder = '\WAC Court Booker\Test\'
     $me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
     $a = New-ScheduledTaskAction -Execute $Exe -Argument $Arguments -WorkingDirectory 'D:\Claude Code\wac-court-booker'
     $p = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
     $s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes $TimeoutMin) -AllowStartIfOnBatteries
     Register-ScheduledTask -TaskPath $folder -TaskName $Name -Action $a -Principal $p -Settings $s -Force | Out-Null
     Start-ScheduledTask -TaskPath $folder -TaskName $Name
     Start-Sleep -Seconds 3
     $end = (Get-Date).AddMinutes($TimeoutMin)
     while ((Get-ScheduledTask -TaskPath $folder -TaskName $Name).State -eq 'Running' -and (Get-Date) -lt $end) { Start-Sleep -Seconds 5 }
     $i = Get-ScheduledTaskInfo -TaskPath $folder -TaskName $Name
     "task $Name finished: LastTaskResult=$($i.LastTaskResult)"
     Unregister-ScheduledTask -TaskPath $folder -TaskName $Name -Confirm:$false
     ```
   - Run it:

     ```powershell
     pwsh -NoProfile -File run-test-task.ps1 -Name 'Update to 0.6.0' -Exe cmd.exe -Arguments '/c "<unzipped folder>\wac-court-booker-0.6.0\setup.cmd" -NoWizard'
     ```
   - Check it took: `& "$env:LOCALAPPDATA\WAC Court Booker\venv\Scripts\wac-booker.exe" --version` prints 0.6.0.
   - Confirm `\WAC Court Booker\Test\` is empty afterwards.

## When you finish, or stop

Report:
- what's done, with commits and the PR or release link;
- what's left;
- the test results (unit test count, sandbox pass count);
- anything that needs a real booking to verify. Offer it as a test the owner can approve; don't run it.

Keep `docs/plan-old-system-features.md` up to date as you go (mark each step done), so the next agent can pick up where you stopped.
