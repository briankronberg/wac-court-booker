# Pick-up prompt — paste into Claude Code

Stop point: 2026-11-27. Task 6 (blockers) of the old-system-features plan is
RED-confirmed: tests written and failing for the right reasons; the runner
implementation (the GREEN) has not started. Tasks 4 and 5 are done and green.

The full handoff (verified baseline, exact spec, failure modes, pitfalls,
standing rules) is in `.superpowers/sdd/plan-old-system-features/progress.md`
— the "HANDOFF / STOP POINT" section at the bottom. Read it first.

---

Pick up the `old-system-features` branch of WAC Court Booker where the previous agent stopped. Stop point: Task 6 (blockers) is RED-confirmed — the tests exist and fail for the right reasons; the runner implementation hasn't started. Everything you need is in this repo:

1. Read `.superpowers/sdd/plan-old-system-features/progress.md` — the progress ledger; the "HANDOFF / STOP POINT (2026-11-27)" section at the bottom is the handoff: verified baseline, the exact spec, per-test failure modes, pitfalls, rules.
2. Read `docs/plan-old-system-features.md` — the plan (tasks 6, 7 and the finish remain).
3. Verify the baseline before writing any code:
   `& "$env:LOCALAPPDATA\WAC Court Booker\venv\Scripts\python.exe" -m pytest -q`
   Expect: 11 failed, 184 passed — all 11 failures in `tests/test_blocker.py`.

Then continue in order:

- **Task 6 GREEN** — implement `plan_blocker` and the blocker paths in
  `run_booking` / `run_group` / `book_now` in `wacbooker/runner.py`. The 11
  failing tests in `tests/test_blocker.py` are the spec; the handoff section
  lists what each one pins. One open decision is called out there: the
  book-now test's date must guarantee an open booking window at run time
  (or you record a ruling about book-now gating for blocker bookings) —
  decide, encode it in the test, then implement. All of `test_blocker.py`
  green, full suite green, no regressions elsewhere.
- **Task 7 — email summary** (plan §7): settings (address + SMTP via the
  creds file, Gmail app-password default, smtplib SSL 465), one plain email
  per scheduled run / per group, "Send test email" button. Also decide the
  carried-over blocker-run email question (own email vs a line in the main
  run's email). Never put passwords in `bookings.yaml`, logs, or state.
- **Task 8 — finish**: DESIGN.md, README (install/usage only, intro lines
  3–6 unchanged), CHANGELOG, bump 0.6.0 in `pyproject.toml` and
  `wacbooker/__init__.py`, sandbox test, PR, merge, tag + release, install.
  Then offer the owner a real window test of the group run + blocker
  (real courts, only with the owner's OK for that run).
- **Whole-branch review** with fresh eyes.

Rules (from the plan header and the owner — still in force): TDD — no
production code without a failing test first, and watch each test fail for
the RIGHT reason (a test bug or a failure in the wrong layer is not it).
Don't stop to check in between tasks; ask only before irreversible or
destructive ops, security-sensitive actions, or side effects outside the
worktree (merge, push, publishing a release). Record deviations in the
ledger as `Ruling: <what> — <why> — <cost if wrong>`. Commits end with
`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; PR bodies end
with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
Never book, cancel, or hold a real court without the owner's OK for that
run; never see, print, log, or commit passwords.
