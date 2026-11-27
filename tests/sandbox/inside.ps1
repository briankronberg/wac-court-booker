# Test driver that runs inside Windows Sandbox, a clean throwaway Windows.
# Windows PowerShell 5.1 syntax on purpose: that's the only PowerShell a clean PC has.
# Installs the release zip the way a new user would and checks each step. Nothing here
# signs in to the club site: the only login has no password, so no court can be booked.
# Results go to C:\wacb\out (mapped to the host): progress.log, report.json, done.json, logs.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$in = 'C:\wacb\in'
$out = 'C:\wacb\out'
$app = Join-Path $env:LOCALAPPDATA 'WAC Court Booker'
$exe = Join-Path $app 'venv\Scripts\wac-booker.exe'
$vpy = Join-Path $app 'venv\Scripts\python.exe'
$expected = (Get-Content (Join-Path $in 'expected-version.txt') -Raw).Trim()
# Hands-on mode: a person answers the setup wizard (types the club login), then the
# signed-in checks run. They're all read-only: sign-in, buddy list, clock and a dry run.
$interactive = Test-Path (Join-Path $in 'interactive.txt')
# Update mode (-Reuse on the host): this sandbox already ran a test and is still open.
# Install the new zip over it with setup.cmd, as a user updating would, then check again.
# Results go to a subfolder named in update.txt.
$updateFile = Join-Path $in 'update.txt'
$update = Test-Path $updateFile
if ($update) {
    $interactive = $false
    $out = Join-Path $out ((Get-Content $updateFile -Raw).Trim())
    New-Item -ItemType Directory -Force $out | Out-Null
}
$results = New-Object System.Collections.ArrayList
# Windows PowerShell 5.1 otherwise puts a byte-order mark in front of text piped to a
# program, so the menu would read "﻿1" instead of the typed "1".
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::InputEncoding = $OutputEncoding

function Log($m) {
    $line = "$(Get-Date -Format HH:mm:ss) $m"
    Add-Content (Join-Path $out 'progress.log') $line
    Write-Host $line
}
function Rec($step, $ok, $detail) {
    [void]$results.Add([pscustomobject]@{ step = $step; ok = [bool]$ok; detail = "$detail" })
    $word = if ($ok) { 'PASS' } else { 'FAIL' }
    Log "$word  $step  $detail"
    ConvertTo-Json -InputObject @($results) -Depth 3 | Set-Content (Join-Path $out 'report.json') -Encoding UTF8
}
function Run-Native($file, [string[]]$argv, $logName, $stdin = $null) {
    if ($null -ne $stdin) { $o = $stdin | & $file @argv 2>&1 | ForEach-Object { "$_" } }
    else { $o = & $file @argv 2>&1 | ForEach-Object { "$_" } }
    $code = $LASTEXITCODE
    $o | Set-Content (Join-Path $out $logName) -Encoding UTF8
    return @{ code = $code; text = ($o -join "`n") }
}
function Run-Setup($logName, [switch]$Wizard, [string]$Extra = '') {
    # Like a double-click: setup's own window, visible in the sandbox. Unattended, stdin
    # is empty so a 'pause' after a failure can't hang the test. With -Wizard (hands-on
    # mode) it's exactly a double-click: the person at the sandbox answers the wizard, and
    # READY goes to the progress log once the wizard is up. setup.ps1 keeps a transcript in
    # logs\setup.log; the part of this run is copied out as $logName.
    $log = Join-Path $app 'logs\setup.log'
    $before = if (Test-Path $log) { (Get-Item $log).Length } else { 0 }
    if ($Wizard) {
        # Setup ends by opening the app's page, which starts with the welcome steps. Wait
        # there until the person has added a club login (it lands in bookings.yaml).
        $p = Start-Process cmd.exe -ArgumentList "/c `"`"$setupCmd`"`"" -PassThru -WindowStyle Normal
        $timedOut = -not $p.WaitForExit(30 * 60 * 1000)
        if (-not $timedOut) {
            Log "READY: the app's page is open and waiting for the club login"
            $cfgFile = Join-Path $app 'bookings.yaml'
            $limit = (Get-Date).AddMinutes(120)
            while ((Get-Date) -lt $limit -and -not ((Test-Path $cfgFile) -and (Get-Content $cfgFile -Raw) -match '(?m)^\s*username:')) { Start-Sleep 3 }
            Start-Sleep 90   # the login test and buddy list run right after
        }
    } else {
        $p = Start-Process cmd.exe -ArgumentList "/c `"`"$setupCmd`" -NoWizard $Extra <nul`"" -PassThru -WindowStyle Normal
        $timedOut = -not $p.WaitForExit(30 * 60 * 1000)
    }
    if ($timedOut) { $p.Kill() }
    if (Test-Path $log) {
        $fs = [IO.File]::Open($log, 'Open', 'Read', 'ReadWrite')
        try { [void]$fs.Seek($before, 'Begin'); $text = (New-Object IO.StreamReader($fs)).ReadToEnd() } finally { $fs.Close() }
        Set-Content (Join-Path $out $logName) $text -Encoding UTF8
    }
    if ($timedOut) { return -1 }
    return $p.ExitCode
}

try {
    Log "Sandbox test of WAC Court Booker $expected"

    # 0. What a clean PC has.
    $has = @{
        winget = [bool](Get-Command winget -ErrorAction SilentlyContinue)
        pwsh   = [bool](Get-Command pwsh -ErrorAction SilentlyContinue)
        py     = [bool](Get-Command py -ErrorAction SilentlyContinue)
        python = [bool](Get-Command python -ErrorAction SilentlyContinue)
    }
    $hasText = ($has.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ' '
    if ($update) { Log "update of an earlier install ($hasText)" }
    else { Rec 'clean PC' (-not ($has.pwsh -or $has.py)) $hasText }

    # 1. Download and unzip, with the "from the internet" mark Explorer leaves on each file.
    #    An update unzips into a fresh folder, like a new download would.
    $dl = Join-Path $env:USERPROFILE 'Downloads'
    if ($update) { $dl = Join-Path $dl ("update-" + (Get-Date -Format yyyyMMdd-HHmmss)) }
    New-Item -ItemType Directory -Force $dl | Out-Null
    $zip = Get-ChildItem $in -Filter 'wac-court-booker-*.zip' | Sort-Object LastWriteTime | Select-Object -Last 1
    Copy-Item $zip.FullName $dl
    Expand-Archive (Join-Path $dl $zip.Name) -DestinationPath $dl -Force
    $src = Join-Path $dl ([IO.Path]::GetFileNameWithoutExtension($zip.Name))
    Get-ChildItem $src -Recurse -File | ForEach-Object {
        Set-Content -Path $_.FullName -Stream Zone.Identifier -Value "[ZoneTransfer]`r`nZoneId=3"
    }
    $setupCmd = Join-Path $src 'setup.cmd'
    Rec 'unzip' (Test-Path $setupCmd) $src

    # 2. Setup from nothing (hands-on mode: with the wizard, answered by a person).
    $t0 = Get-Date
    $code = if ($interactive) { Run-Setup 'setup-console.txt' -Wizard } else { Run-Setup 'setup-console.txt' }
    $mins = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
    Copy-Item (Join-Path $app 'logs\setup.log') (Join-Path $out 'setup.log') -ErrorAction SilentlyContinue
    $console = Get-Content (Join-Path $out 'setup-console.txt') -Raw -ErrorAction SilentlyContinue
    $what = if ($update) { 'setup.cmd (update)' } else { 'setup.cmd (first install)' }
    Rec $what ($code -eq 0 -and $console -match 'Installed WAC Court Booker') "exit $code after $mins min"

    $privatePwsh = Join-Path $app 'pwsh\pwsh.exe'
    $machinePwsh = Join-Path $env:ProgramFiles 'PowerShell\7\pwsh.exe'
    $which = if (Test-Path $machinePwsh) { $machinePwsh } elseif (Test-Path $privatePwsh) { $privatePwsh } else { 'none' }
    Rec 'PowerShell 7 installed' ($which -ne 'none') $which

    $pyv = if (Test-Path $vpy) { (& $vpy -c "import sys,platform; print(platform.python_version(), sys._base_executable)") } else { 'no venv' }
    Rec 'Python and app environment' (Test-Path $exe) "$pyv"

    if (-not (Test-Path $exe)) { throw "setup didn't install the app; see setup-console.txt and setup.log" }

    # 3. Version.
    $r = Run-Native $exe @('version') 'version.txt'
    Rec 'version' ($r.code -eq 0 -and $r.text.Trim() -eq $expected) $r.text.Trim()

    # 4. Self-test: browser starts and reaches the club's sign-in page (no sign-in), toast shows.
    $r = Run-Native $exe @('selftest', '--browser', '--toast', '--out', (Join-Path $out 'selftest.json')) 'selftest.txt'
    $st = Get-Content (Join-Path $out 'selftest.json') -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
    Rec 'selftest: browser' ($st.browser_ok -eq $true) "browser_ok=$($st.browser_ok)"
    Rec 'selftest: toast' ($st.toast_shown -eq $true) "toast_shown=$($st.toast_shown)"
    Rec 'selftest: app folder' ($st.home_writable -eq $true -and $st.log_file -eq $true) "home_writable=$($st.home_writable) log_file=$($st.log_file) wake_timers=$($st.wake_timers)"

    # 4b. Signed-in checks, read-only, with the login a person typed into the wizard: in
    #     hands-on mode, or in update mode when an earlier hands-on run left one here.
    # Earlier versions of this test put their login and bookings in the person's own app
    # folder. Take them out (and their tasks), so only what the person added remains.
    $clean = Run-Native $vpy @((Join-Path $in 'cleanup_old.py')) 'cleanup.txt'
    if ($clean.text -match 'removed') {
        Run-Native $exe @('rebuild-tasks') 'cleanup-rebuild-tasks.txt' | Out-Null
        Log "removed an earlier run's test login and bookings from the app folder"
    }

    $nick = $null
    $loginInfo = "$(& $vpy -c "from wacbooker import config; d, c = config.load(); x = c.logins[0] if c.logins else None; print(f'{x.nickname}|{x.username}' if x else '|')")".Trim()
    $firstLogin, $nickUser = $loginInfo -split '\|', 2
    if ($update -and $firstLogin -and $st.passwords_reachable.$firstLogin -eq $true) { $nick = $firstLogin }
    if ($interactive -or $nick) {
        $nick = $firstLogin
        $reach = if ($nick) { $st.passwords_reachable.$nick } else { $false }
        Rec 'login saved' ($nick -and $reach -eq $true) "login '$nick', password in Credential Manager=$reach"
        if ($nick) {
            $r = Run-Native $exe @('test-login', '--login', $nick) 'test-login.txt'
            Rec 'test-login (read-only)' ($r.code -eq 0) (($r.text -split "`n" | Where-Object { $_ -match 'Signed in|fail|error|couldn' } | Select-Object -First 1) -replace '\(\d+\)', '')
            $r = Run-Native $exe @('buddies', '--login', $nick) 'buddies.txt'
            Rec 'buddies (read-only)' ($r.code -eq 0) (($r.text -split "`n" | Where-Object { $_ -match 'budd' } | Select-Object -Last 1))
        }
        $r = Run-Native $exe @('clock') 'clock.txt'
        Rec 'clock' ($r.code -eq 0) ($r.text.Trim() -split "`n" | Select-Object -Last 1)
    }

    # 5. Test bookings, checked and scheduled. They live in a scratch app folder with
    #    their own task folder, never in the app folder the person uses, so the menu
    #    only ever shows the logins and bookings they added themselves:
    #    - login "test-no-password" (no password) with booking "Sandbox check";
    #    - with a signed-in login, a PAUSED booking "Sandbox dry run" on it, for the dry run
    #      (same username, so its password comes from Credential Manager as usual).
    $realConfig = Join-Path $app 'bookings.yaml'
    $realBefore = if (Test-Path $realConfig) { (Get-FileHash $realConfig).Hash } else { '' }
    $scratch = 'C:\wacb-test-home'
    New-Item -ItemType Directory -Force $scratch | Out-Null
    if (-not (Test-Path (Join-Path $scratch 'browsers'))) {
        cmd.exe /c "mklink /J `"$scratch\browsers`" `"$app\browsers`"" | Out-Null   # the same app browser
    }
    $env:WACB_HOME = $scratch
    $env:WACB_TASK_FOLDER = '\WAC Court Booker\Test\'
    $mbArgs = @((Join-Path $in 'make_booking.py'))
    if ($nick) { $mbArgs += @('--dry-login', $nick, '--dry-user', $nickUser) }
    $r = Run-Native $vpy $mbArgs 'make-booking.txt'
    Rec 'write test bookings (scratch folder)' ($r.code -eq 0) $r.text.Trim()
    if ($nick) {
        $r = Run-Native $exe @('dry-run', '--booking', 'Sandbox dry run') 'dry-run.txt'
        Rec 'dry-run (read-only)' ($r.code -eq 0 -and $r.text -match 'show open|would go|no court') (($r.text -split "`n" | Where-Object { $_ -match 'min at|would go|Stopped' }) -join ' | ')
    }
    $r = Run-Native $exe @('check') 'check.txt'
    Rec 'check' ($r.code -eq 0 -and $r.text -match 'Sandbox check') "exit $($r.code)"
    $r = Run-Native $exe @('rebuild-tasks') 'rebuild-tasks.txt'
    $all = @(Get-ScheduledTask -TaskPath '\WAC Court Booker\Test\' -ErrorAction SilentlyContinue)
    foreach ($t in $all) { Export-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath | Set-Content (Join-Path $out "task-$($t.TaskName).xml") -Encoding UTF8 }
    $tasks = @($all | Where-Object { $_.TaskName -eq 'Booking - Sandbox check' })
    $dryOff = $true
    if ($nick) { $dryOff = @($all | Where-Object { $_.TaskName -eq 'Booking - Sandbox dry run' -and $_.State -eq 'Disabled' }).Count -eq 1 }
    Rec 'rebuild-tasks' ($r.code -eq 0 -and $tasks.Count -eq 1 -and $dryOff) "exit $($r.code), tasks: $((($all | ForEach-Object { "$($_.TaskName) [$($_.State)]" })) -join ', ')"
    Run-Native $exe @('tasks') 'tasks.txt' | Out-Null

    # 6. Task Scheduler starts the booking the way it would on the day. With no password
    #    it must stop with a plain "Not booked" result before touching the club site.
    $resultsFile = Join-Path $scratch 'results.jsonl'
    if ($tasks.Count -ge 1) {
        $n0 = if (Test-Path $resultsFile) { @(Get-Content $resultsFile).Count } else { 0 }
        Start-ScheduledTask -TaskName $tasks[0].TaskName -TaskPath $tasks[0].TaskPath
        $deadline = (Get-Date).AddMinutes(3)
        while ((Get-Date) -lt $deadline -and -not ((Test-Path $resultsFile) -and @(Get-Content $resultsFile).Count -gt $n0)) { Start-Sleep 2 }
        Start-Sleep 2
        $last = if (Test-Path $resultsFile) { Get-Content $resultsFile | Select-Object -Last 1 | ConvertFrom-Json } else { $null }
        $info = Get-ScheduledTaskInfo -TaskName $tasks[0].TaskName -TaskPath $tasks[0].TaskPath
        $ok = $last -and $last.status -eq 'not_booked' -and "$($last.detail)$($last.message)" -match 'password'
        Rec 'scheduled run (no password)' $ok "result=$(if ($last) { $last | ConvertTo-Json -Compress } else { 'none' }) LastTaskResult=$($info.LastTaskResult)"
    } else { Rec 'scheduled run (no password)' $false 'no task to start' }

    # 7. The menu, driven by typed answers: show bookings, Enter, quit.
    $r = Run-Native $exe @('menu') 'menu.txt' "1`r`n`r`n0`r`n"
    Rec 'menu (show bookings, quit)' ($r.code -eq 0 -and $r.text -match 'Sandbox check') "exit $($r.code)"

    # 7a. The app's page: the server starts, serves the page, refuses a request without
    #     its token, lists the booking, then stops when asked (as setup asks it to).
    $webOut = Join-Path $out 'web-server.txt'
    $wp = Start-Process $exe -ArgumentList 'web', '--no-open' -PassThru -WindowStyle Hidden -RedirectStandardOutput $webOut
    $url = $null
    foreach ($i in 1..30) { Start-Sleep 1; $line = Get-Content $webOut -ErrorAction SilentlyContinue | Select-String '^Open (http\S+)'; if ($line) { $url = $line.Matches[0].Groups[1].Value; break } }
    $webOk = $false; $detail = 'no address printed'
    if ($url) {
        $base = $url -replace '/#t=.*$', ''
        $tok = $url -replace '^.*#t=', ''
        try {
            $page = Invoke-WebRequest "$base/" -UseBasicParsing -TimeoutSec 10
            $cal = Invoke-WebRequest "$base/calendar" -UseBasicParsing -TimeoutSec 10
            $denied = try { Invoke-WebRequest "$base/api/state" -UseBasicParsing -TimeoutSec 10 | Out-Null; $false } catch { $true }
            $st = Invoke-RestMethod "$base/api/state" -Headers @{ 'X-WACB-Token' = $tok } -TimeoutSec 60
            $titles = @($st.bookings | ForEach-Object { $_.title }) -join '; '
            Invoke-RestMethod -Method Post "$base/api/quit" -Headers @{ 'X-WACB-Token' = $tok } -ContentType 'application/json' -Body '{}' -TimeoutSec 10 | Out-Null
            $stopped = $wp.WaitForExit(20000)
            $webOk = $page.Content -match 'WAC Court Booker' -and $cal.Content -match 'Available courts' -and $denied -and $st.version -eq $expected -and @($st.bookings).Count -ge 1 -and $stopped
            $detail = "page=$($page.StatusCode) calendar=$($cal.StatusCode) no-token refused=$denied version=$($st.version) bookings: $titles; stopped=$stopped"
        } catch { $detail = "error: $($_.Exception.Message)" }
    }
    if (-not $wp.HasExited) { Stop-Process -Id $wp.Id -Force -ErrorAction SilentlyContinue }
    Rec 'app page (web server)' $webOk $detail
    Remove-Item Env:\WACB_HOME, Env:\WACB_TASK_FOLDER

    # 7b. None of that touched the person's own app folder or tasks.
    $realAfter = if (Test-Path $realConfig) { (Get-FileHash $realConfig).Hash } else { '' }
    $stray = @(Get-ScheduledTask -TaskPath '\WAC Court Booker\' -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -like 'Booking - Sandbox*' })
    $leak = if (Test-Path $realConfig) { (Get-Content $realConfig -Raw) -match 'test-no-password|nickname: sandbox|Sandbox check|Sandbox dry run' } else { $false }
    Rec 'own app folder untouched by tests' ($realBefore -eq $realAfter -and -not $leak -and -not $stray.Count) "bookings.yaml unchanged=$($realBefore -eq $realAfter), test entries in it=$leak, test tasks in the real folder=$($stray.Count)"

    # 8. Running setup again updates in place and keeps the bookings.
    $code = Run-Setup 'setup-console-2.txt'
    $kept = ((Test-Path $realConfig) -and (Get-FileHash $realConfig).Hash -eq $realAfter) -or (-not $realAfter)
    Rec 'setup.cmd again (update)' ($code -eq 0 -and $kept) "exit $code, bookings.yaml kept=$kept"
    $startLnk = Join-Path ([Environment]::GetFolderPath('Programs')) 'WAC Court Booker.lnk'
    $target = if (Test-Path $startLnk) { (New-Object -ComObject WScript.Shell).CreateShortcut($startLnk).TargetPath } else { '' }
    Rec 'Start-menu shortcut opens the page' ($target -eq (Join-Path (Split-Path $exe) 'wac-booker-web.exe')) "target=$target"
    # A first install always puts one on the desktop too, and the update keeps it.
    $deskLnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'WAC Court Booker.lnk'
    $dTarget = if (Test-Path $deskLnk) { (New-Object -ComObject WScript.Shell).CreateShortcut($deskLnk).TargetPath } else { '' }
    Rec 'desktop shortcut opens the page' ($dTarget -eq (Join-Path (Split-Path $exe) 'wac-booker-web.exe')) "target=$dTarget"

    # 9. The offline unit tests, on this Python.
    Run-Native $vpy @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', 'pytest') 'pip-pytest.txt' | Out-Null
    # The tests aren't in the release zip; the host puts them (and pyproject.toml) in in\dev.
    Push-Location (Join-Path $in 'dev')
    $env:PYTHONDONTWRITEBYTECODE = '1'   # in\ is read-only here
    $r = Run-Native $vpy @('-m', 'pytest', '-q', '-p', 'no:cacheprovider', "--junitxml=$(Join-Path $out 'pytest.xml')", 'tests') 'pytest.txt'
    Remove-Item Env:\PYTHONDONTWRITEBYTECODE
    Pop-Location
    $summary = ($r.text -split "`n" | Where-Object { $_ -match 'passed|failed|error' } | Select-Object -Last 1)
    Rec 'unit tests' ($r.code -eq 0) "$summary"
}
catch {
    Rec 'driver' $false $_.Exception.Message
}
finally {
    foreach ($f in 'logs\wac-booker.log', 'results.jsonl', 'bookings.yaml') {
        Copy-Item (Join-Path $app $f) $out -ErrorAction SilentlyContinue
        Copy-Item (Join-Path 'C:\wacb-test-home' $f) (Join-Path $out ("test-" + (Split-Path $f -Leaf))) -ErrorAction SilentlyContinue
    }
    $failed = @($results | Where-Object { -not $_.ok }).Count
    ConvertTo-Json -InputObject @{ passed = $results.Count - $failed; failed = $failed } |
        Set-Content (Join-Path $out 'done.json') -Encoding UTF8
    Log "Done: $($results.Count - $failed) passed, $failed failed"
}
