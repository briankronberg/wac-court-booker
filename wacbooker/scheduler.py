"""Windows Task Scheduler: one task per booking under \\WAC Court Booker\\.

Each task starts 75 minutes before its booking window W (the run then waits
until W - 15 min), wakes the PC, starts late if the PC was off, and never runs
two copies at once. Weekly bookings use a weekly trigger at PC-local time;
one-offs a single trigger. All PowerShell work runs in pwsh (PowerShell 7).

Signed-out runs use logon type "Password": Windows stores the Windows
password with the task so the run can reach Credential Manager. Every
re-registration needs that password again; the menu asks once per session.
If the PC refuses (common on work PCs), tasks fall back to "signed in, screen
can be locked" and the reason is reported.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from . import APP_NAME, clubtime, paths
from .config import Booking, Config

# WACB_TASK_FOLDER lets tests use their own folder (e.g. \WAC Court Booker\Test\).
FOLDER = os.environ.get("WACB_TASK_FOLDER") or f"\\{APP_NAME}\\"
TEST_FOLDER = f"\\{APP_NAME}\\Test\\"
PREFIX = "Booking - "
DAY_TAGS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def pwsh() -> str:
    found = shutil.which("pwsh")
    if found:
        return found
    default = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "PowerShell" / "7" / "pwsh.exe"
    if default.exists():
        return str(default)
    # setup.cmd puts a private copy here on PCs without winget.
    private = Path(os.environ.get("LOCALAPPDATA", "")) / APP_NAME / "pwsh" / "pwsh.exe"
    if private.exists():
        return str(private)
    raise RuntimeError("PowerShell 7 (pwsh) isn't installed. Run setup.cmd again.")


def run_ps(script: str, stdin: str = "", timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run([pwsh(), "-NoProfile", "-NonInteractive", "-Command", script],
                          input=stdin, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


PRIME_SUFFIX = " (Prime Time part)"


def task_name(booking_name: str, part: str = "main") -> str:
    name = PREFIX + re.sub(r'[\\/:*?"<>|]', "-", booking_name).strip()
    return name + (PRIME_SUFFIX if part == "prime" else "")


def python_for_tasks() -> str:
    """pythonw.exe next to the running interpreter, so no console window pops up."""
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def run_args(booking_name: str, part: str = "main") -> str:
    args = ["-m", "wacbooker"]
    if os.environ.get("WACB_HOME"):
        args += ["--home", os.environ["WACB_HOME"]]
    args += ["run", "--booking", booking_name]
    if part != "main":
        args += ["--part", part]
    return subprocess.list2cmdline(args)


def _local(dt: datetime) -> datetime:
    return dt.astimezone()  # PC local time


@dataclass
class Plan:
    name: str            # task name
    booking: str
    xml: str
    next_run: datetime | None
    enabled: bool


def build_xml(b: Booking, run_at: datetime, logon: str, now: datetime | None = None,
              command: str | None = None, arguments: str | None = None) -> str:
    """Task XML. `logon` is 'InteractiveToken' or 'Password'. __USER__ is filled
    in by PowerShell with the current Windows account."""
    now = now or datetime.now().astimezone()
    start = _local(run_at)
    if b.day is not None:
        trig = (f"<CalendarTrigger><StartBoundary>{start:%Y-%m-%dT%H:%M:%S}</StartBoundary>"
                f"<Enabled>true</Enabled><ScheduleByWeek><DaysOfWeek><{DAY_TAGS[start.weekday()]} />"
                f"</DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek></CalendarTrigger>")
    else:
        if start < now:
            start = now + timedelta(minutes=1)
        trig = (f"<TimeTrigger><StartBoundary>{start:%Y-%m-%dT%H:%M:%S}</StartBoundary>"
                f"<Enabled>true</Enabled></TimeTrigger>")
    desc = escape(f"{APP_NAME}: {b.name}. {b.describe()}. Change it in the {APP_NAME} menu.")
    cmd = escape(command or python_for_tasks())
    args = escape(arguments or run_args(b.name))
    workdir = escape(str(paths.home()))
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Author>{APP_NAME}</Author><Description>{desc}</Description></RegistrationInfo>
  <Triggers>{trig}</Triggers>
  <Principals><Principal id="Author"><UserId>__USER__</UserId><LogonType>{logon}</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>{'true' if b.active else 'false'}</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT3H</ExecutionTimeLimit>
    <Priority>5</Priority>
  </Settings>
  <Actions Context="Author"><Exec><Command>{cmd}</Command><Arguments>{args}</Arguments><WorkingDirectory>{workdir}</WorkingDirectory></Exec></Actions>
</Task>
"""


def plan(cfg: Config, logon: str, now: datetime | None = None) -> list[Plan]:
    """The tasks the config needs. Bookings with no future window get none."""
    now_c = (now or clubtime.now_central()).astimezone(clubtime.CENTRAL)
    out = []
    for b in cfg.bookings:
        for p in b.parts:  # a singles booking split at Prime Time has two runs
            nxt = b.next_runs(now_c - clubtime.LATE_OK, 1, p.key)
            if not nxt:
                continue
            xml = build_xml(b, nxt[0].run_at, logon, now=now, arguments=run_args(b.name, p.key))
            out.append(Plan(task_name(b.name, p.key), b.name, xml, nxt[0].run_at, b.active))
    return out


REGISTER_PS = r"""
$ErrorActionPreference = 'Stop'
$in = [Console]::In.ReadToEnd() | ConvertFrom-Json
$folder = $in.folder
$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$out = @()
foreach ($t in $in.tasks) {
  $xml = $t.xml.Replace('__USER__', [System.Security.SecurityElement]::Escape($me))
  try {
    if ($in.password) {
      Register-ScheduledTask -TaskPath $folder -TaskName $t.name -Xml $xml -User $me -Password $in.password -Force | Out-Null
    } else {
      Register-ScheduledTask -TaskPath $folder -TaskName $t.name -Xml $xml -Force | Out-Null
    }
    $out += @{ name = $t.name; ok = $true }
  } catch {
    $out += @{ name = $t.name; ok = $false; error = $_.Exception.Message }
  }
}
$keep = @($in.tasks | ForEach-Object { $_.name })
$removed = @()
if ($in.prune) {
  Get-ScheduledTask -TaskPath $folder -ErrorAction SilentlyContinue |
    Where-Object { $_.TaskPath -eq $folder -and $keep -notcontains $_.TaskName } |
    ForEach-Object { Unregister-ScheduledTask -TaskPath $folder -TaskName $_.TaskName -Confirm:$false; $removed += $_.TaskName }
}
@{ results = $out; removed = $removed; user = $me } | ConvertTo-Json -Depth 4 -Compress
"""


@dataclass
class SyncResult:
    ok: bool
    logon: str
    registered: list[str]
    removed: list[str]
    errors: list[str]
    note: str = ""


def _register(plans: list[Plan], password: str | None, folder: str, prune: bool) -> dict:
    payload = json.dumps({"folder": folder, "prune": prune, "password": password or "",
                          "tasks": [{"name": p.name, "xml": p.xml} for p in plans]})
    r = run_ps(REGISTER_PS, stdin=payload)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"Task Scheduler update failed: {(r.stderr or r.stdout).strip()[:300]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def sync(cfg: Config, windows_password: str | None = None, folder: str = FOLDER,
         now: datetime | None = None) -> SyncResult:
    """Make the tasks in `folder` match the config exactly."""
    signed_out = cfg.run_signed_out and bool(windows_password)
    logon = "Password" if signed_out else "InteractiveToken"
    plans = plan(cfg, logon, now)
    res = _register(plans, windows_password if signed_out else None, folder, prune=True)
    errors = [f"{x['name']}: {x.get('error', '')}" for x in res["results"] if not x.get("ok")]
    note = ""
    if signed_out and errors:
        # Typical on work PCs: storing passwords for tasks is blocked by policy,
        # or the password was wrong. Fall back to "signed in, screen can be locked".
        note = ("Windows wouldn't save these tasks to run while signed out "
                f"({errors[0].split(': ', 1)[-1][:160]}). They'll run while you're signed in "
                "(the screen can be locked).")
        plans = plan(cfg, "InteractiveToken", now)
        res = _register(plans, None, folder, prune=True)
        logon = "InteractiveToken"
        errors = [f"{x['name']}: {x.get('error', '')}" for x in res["results"] if not x.get("ok")]
    elif cfg.run_signed_out and not windows_password:
        note = "Signed-out runs need your Windows password; these tasks run while you're signed in."
    return SyncResult(not errors, logon, [x["name"] for x in res["results"] if x.get("ok")],
                      list(res.get("removed") or []), errors, note)


STATUS_PS = r"""
$folder = [Console]::In.ReadToEnd().Trim()
$rows = @(Get-ScheduledTask -TaskPath $folder -ErrorAction SilentlyContinue | Where-Object { $_.TaskPath -eq $folder } | ForEach-Object {
  $i = $_ | Get-ScheduledTaskInfo
  @{ name = $_.TaskName; state = "$($_.State)"; logon = "$($_.Principal.LogonType)"; wake = $_.Settings.WakeToRun;
     next = if ($i.NextRunTime) { $i.NextRunTime.ToString('o') } else { '' };
     last = if ($i.LastRunTime -and $i.LastRunTime.Year -gt 2000) { $i.LastRunTime.ToString('o') } else { '' };
     result = $i.LastTaskResult }
})
ConvertTo-Json -InputObject $rows -Depth 3 -Compress
"""


def status(folder: str = FOLDER) -> list[dict]:
    r = run_ps(STATUS_PS, stdin=folder)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:300])
    text = r.stdout.strip()
    return json.loads(text) if text else []


def remove_all(folder: str = FOLDER) -> None:
    run_ps(f"Get-ScheduledTask -TaskPath '{folder}' -ErrorAction SilentlyContinue | "
           f"Where-Object {{ $_.TaskPath -eq '{folder}' }} | Unregister-ScheduledTask -Confirm:$false")


# ---------------------------------------------------------------- wake timers

def wake_timers_on() -> bool | None:
    try:
        r = subprocess.run(["powercfg", "/q", "SCHEME_CURRENT", "SUB_SLEEP", "RTCWAKE"],
                           capture_output=True, text=True, timeout=30)
    except OSError:
        return None
    vals = re.findall(r"Current AC Power Setting Index:\s*0x([0-9a-f]+)", r.stdout, re.I)
    if not vals:
        return None
    return int(vals[0], 16) != 0


def enable_wake_timers() -> tuple[bool, str]:
    cmds = [["powercfg", "/setacvalueindex", "SCHEME_CURRENT", "SUB_SLEEP", "RTCWAKE", "1"],
            ["powercfg", "/setdcvalueindex", "SCHEME_CURRENT", "SUB_SLEEP", "RTCWAKE", "1"],
            ["powercfg", "/setactive", "SCHEME_CURRENT"]]
    for c in cmds:
        r = subprocess.run(c, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return False, (r.stderr or r.stdout).strip()[:200] or "powercfg refused"
    return bool(wake_timers_on()), "wake timers are on for the current power plan"
