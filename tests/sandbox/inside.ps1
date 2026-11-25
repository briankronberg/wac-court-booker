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
function Run-Setup($logName) {
    # Like a double-click: setup's own window, visible in the sandbox. The only difference
    # is empty stdin, so a 'pause' after a failure can't hang the test. setup.ps1 keeps a
    # transcript in logs\setup.log; the part of this run is copied out as $logName.
    $log = Join-Path $app 'logs\setup.log'
    $before = if (Test-Path $log) { (Get-Item $log).Length } else { 0 }
    $p = Start-Process cmd.exe -ArgumentList "/c `"`"$setupCmd`" -NoWizard <nul`"" -PassThru -WindowStyle Normal
    $timedOut = -not $p.WaitForExit(30 * 60 * 1000)
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
    Rec 'clean PC' (-not ($has.pwsh -or $has.py)) (($has.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ' ')

    # 1. Download and unzip, with the "from the internet" mark Explorer leaves on each file.
    $dl = Join-Path $env:USERPROFILE 'Downloads'
    New-Item -ItemType Directory -Force $dl | Out-Null
    $zip = Get-ChildItem $in -Filter 'wac-court-booker-*.zip' | Select-Object -First 1
    Copy-Item $zip.FullName $dl
    Expand-Archive (Join-Path $dl $zip.Name) -DestinationPath $dl -Force
    $src = Join-Path $dl ([IO.Path]::GetFileNameWithoutExtension($zip.Name))
    Get-ChildItem $src -Recurse -File | ForEach-Object {
        Set-Content -Path $_.FullName -Stream Zone.Identifier -Value "[ZoneTransfer]`r`nZoneId=3"
    }
    $setupCmd = Join-Path $src 'setup.cmd'
    Rec 'unzip' (Test-Path $setupCmd) $src

    # 2. Setup from nothing.
    $t0 = Get-Date
    $code = Run-Setup 'setup-console.txt'
    $mins = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
    Copy-Item (Join-Path $app 'logs\setup.log') (Join-Path $out 'setup.log') -ErrorAction SilentlyContinue
    $console = Get-Content (Join-Path $out 'setup-console.txt') -Raw -ErrorAction SilentlyContinue
    Rec 'setup.cmd (first install)' ($code -eq 0 -and $console -match 'Installed WAC Court Booker') "exit $code after $mins min"

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

    # 5. A booking (login without a password), checked and scheduled.
    $r = Run-Native $vpy @((Join-Path $in 'make_booking.py')) 'make-booking.txt'
    Rec 'write bookings.yaml' ($r.code -eq 0) $r.text.Trim()
    $r = Run-Native $exe @('check') 'check.txt'
    Rec 'check' ($r.code -eq 0 -and $r.text -match 'Sandbox check') "exit $($r.code)"
    $r = Run-Native $exe @('rebuild-tasks') 'rebuild-tasks.txt'
    $tasks = @(Get-ScheduledTask -TaskPath '\WAC Court Booker\' -ErrorAction SilentlyContinue)
    foreach ($t in $tasks) { Export-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath | Set-Content (Join-Path $out "task-$($t.TaskName).xml") -Encoding UTF8 }
    Rec 'rebuild-tasks' ($r.code -eq 0 -and $tasks.Count -eq 1) "exit $($r.code), $($tasks.Count) task(s): $(($tasks.TaskName) -join ', ')"
    Run-Native $exe @('tasks') 'tasks.txt' | Out-Null

    # 6. Task Scheduler starts the booking the way it would on the day. With no password
    #    it must stop with a plain "Not booked" result before touching the club site.
    $resultsFile = Join-Path $app 'results.jsonl'
    if ($tasks.Count -ge 1) {
        Start-ScheduledTask -TaskName $tasks[0].TaskName -TaskPath $tasks[0].TaskPath
        $deadline = (Get-Date).AddMinutes(3)
        while ((Get-Date) -lt $deadline -and -not (Test-Path $resultsFile)) { Start-Sleep 2 }
        Start-Sleep 2
        $last = if (Test-Path $resultsFile) { Get-Content $resultsFile | Select-Object -Last 1 | ConvertFrom-Json } else { $null }
        $info = Get-ScheduledTaskInfo -TaskName $tasks[0].TaskName -TaskPath $tasks[0].TaskPath
        $ok = $last -and $last.status -eq 'not_booked' -and "$($last.detail)$($last.message)" -match 'password'
        Rec 'scheduled run (no password)' $ok "result=$(if ($last) { $last | ConvertTo-Json -Compress } else { 'none' }) LastTaskResult=$($info.LastTaskResult)"
    } else { Rec 'scheduled run (no password)' $false 'no task to start' }

    # 7. The menu, driven by typed answers: show bookings, Enter, quit.
    $r = Run-Native $exe @('menu') 'menu.txt' "1`r`n`r`n0`r`n"
    Rec 'menu (show bookings, quit)' ($r.code -eq 0 -and $r.text -match 'Sandbox check') "exit $($r.code)"

    # 8. Running setup again updates in place and keeps the bookings.
    $code = Run-Setup 'setup-console-2.txt'
    $kept = (Get-Content (Join-Path $app 'bookings.yaml') -Raw) -match 'Sandbox check'
    Rec 'setup.cmd again (update)' ($code -eq 0 -and $kept) "exit $code, bookings kept=$kept"

    # 9. The offline unit tests, on this Python.
    Run-Native $vpy @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', 'pytest') 'pip-pytest.txt' | Out-Null
    Push-Location $src
    $r = Run-Native $vpy @('-m', 'pytest', '-q', '-p', 'no:cacheprovider', "--junitxml=$(Join-Path $out 'pytest.xml')", 'tests') 'pytest.txt'
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
    }
    $failed = @($results | Where-Object { -not $_.ok }).Count
    ConvertTo-Json -InputObject @{ passed = $results.Count - $failed; failed = $failed } |
        Set-Content (Join-Path $out 'done.json') -Encoding UTF8
    Log "Done: $($results.Count - $failed) passed, $failed failed"
}
