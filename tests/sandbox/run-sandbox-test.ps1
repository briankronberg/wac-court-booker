<#
.SYNOPSIS
  Installs WAC Court Booker on a clean Windows in Windows Sandbox and checks it, unattended.

.DESCRIPTION
  Builds a release-style zip from this working tree (or uses -Zip), starts Windows Sandbox
  with it mapped read-only, and runs tests\sandbox\inside.ps1 there at sign-in. That script
  installs from the zip with setup.cmd -NoWizard, then checks PowerShell 7 and Python got
  installed, the self-test (browser and toast), check, rebuild-tasks, a run started by
  Task Scheduler, the menu, a second setup run, and the offline unit tests.

  Nothing signs in to the club site: the only login in the sandbox has no password, so
  nothing can be booked. Results land in .sandbox\<time>\out (report.json and logs).

  Needs the Windows Sandbox feature, and no other sandbox running (Windows allows one).

.PARAMETER Zip
  Test this release zip instead of building one from the working tree.
.PARAMETER TimeoutMinutes
  Give up waiting after this long (default 40).
.PARAMETER KeepOpen
  Leave the sandbox window open afterwards, to look around. Closing it discards everything.
.PARAMETER HandsOn
  Run setup with its wizard so a person can type a club login into the sandbox. A line
  saying READY appears when the wizard is waiting. Then the signed-in checks run too, all
  read-only (sign-in, buddy list, clock, dry run). The password goes into the sandbox's
  own Credential Manager and is gone when the sandbox closes. Waits up to 2 hours. The
  sandbox stays open afterwards, for -Reuse.
.PARAMETER Reuse
  Update the sandbox that a -KeepOpen or -HandsOn run left open, instead of starting a
  clean one. The new zip goes in with setup.cmd -NoWizard (an update, as a user would run
  it), then the checks run again, including the signed-in ones if a login was typed in.
  Takes seconds plus the checks, since PowerShell 7 and Python are already there. It
  doesn't retest a first install, so run a clean test before a release.
#>
param(
    [string]$Zip,
    [int]$TimeoutMinutes = 40,
    [switch]$KeepOpen,
    [switch]$HandsOn,
    [switch]$Reuse
)
if ($HandsOn -and $TimeoutMinutes -lt 150) { $TimeoutMinutes = 150 }
if ($HandsOn) { $KeepOpen = $true }
if ($Reuse -and $HandsOn) { throw "-Reuse uses the login already typed into the open sandbox; leave out -HandsOn." }
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$version = ((Select-String -Path (Join-Path $repo 'wacbooker\__init__.py') -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value)
$current = Join-Path $repo '.sandbox\current.json'   # the sandbox this script left open, if any
$stamp = Get-Date -Format yyyyMMdd-HHmmss
if ($Reuse) {
    if (-not (Test-Path $current)) { throw "No open sandbox to reuse. Run once with -KeepOpen or -HandsOn first." }
    $cur = Get-Content $current -Raw | ConvertFrom-Json
    $run, $inDir = $cur.run, $cur.inDir
    $outDir = Join-Path $cur.outDir "update-$stamp"   # the sandbox sees C:\wacb\out\update-<time>
    $KeepOpen = $true
} else {
    $run = Join-Path $repo ".sandbox\$stamp"
    $inDir = Join-Path $run 'in'
    $outDir = Join-Path $run 'out'
}
New-Item -ItemType Directory -Force $inDir, $outDir | Out-Null

if (-not (Get-Command WindowsSandbox.exe -ErrorAction SilentlyContinue)) {
    throw "Windows Sandbox isn't turned on. Turn on the 'Windows Sandbox' feature, restart, then try again."
}
$wsb = Get-Command wsb.exe -ErrorAction SilentlyContinue
function Get-SandboxIds {
    if (-not $wsb) { return @() }
    $j = & wsb.exe list --raw 2>$null | ConvertFrom-Json -ErrorAction SilentlyContinue
    return @($j.WindowsSandboxEnvironments | ForEach-Object { $_.Id })
}
$running = @(Get-SandboxIds)
if ($Reuse) {
    if (-not $wsb) { throw "-Reuse needs the wsb command (the Windows Sandbox CLI, Windows 11 24H2 or later)." }
    if (-not $running.Count) {
        Remove-Item $current -ErrorAction SilentlyContinue
        throw "That sandbox was closed. Run a full test again."
    }
    # Only this run's zip, so the driver can't pick an older one.
    Get-ChildItem $inDir -Filter 'wac-court-booker-*.zip' | Remove-Item -Force
} elseif ($running.Count -or (Get-Process WindowsSandboxRemoteSession -ErrorAction SilentlyContinue)) {
    throw "A Windows Sandbox is already running. Close it first (Windows allows only one), or use -Reuse."
}

# The zip under test.
if ($Zip) {
    Copy-Item $Zip $inDir
    if ((Split-Path $Zip -Leaf) -match 'wac-court-booker-(.+)\.zip') { $version = $Matches[1] }
} else {
    # Every tracked or new (not ignored) file, as the release zip lays them out.
    $name = "wac-court-booker-$version"
    $stage = Join-Path $run "stage\$name"
    Push-Location $repo
    try {
        $files = git ls-files --cached --others --exclude-standard | Where-Object { Test-Path $_ -PathType Leaf }
        foreach ($f in $files) {
            $dest = Join-Path $stage $f
            New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
            Copy-Item $f $dest
        }
    } finally { Pop-Location }
    Compress-Archive -Path $stage -DestinationPath (Join-Path $inDir "$name.zip")
    Remove-Item -Recurse -Force (Join-Path $run 'stage')
}
Set-Content (Join-Path $inDir 'expected-version.txt') $version
Remove-Item (Join-Path $inDir 'interactive.txt'), (Join-Path $inDir 'update.txt') -ErrorAction SilentlyContinue
if ($HandsOn) { Set-Content (Join-Path $inDir 'interactive.txt') 'hands-on' }
if ($Reuse) { Set-Content (Join-Path $inDir 'update.txt') "update-$stamp" }
foreach ($f in 'inside.cmd', 'inside.ps1', 'make_booking.py') { Copy-Item (Join-Path $PSScriptRoot $f) $inDir }

$config = Join-Path $run 'test.wsb'
@"
<Configuration>
  <MemoryInMB>4096</MemoryInMB>
  <Networking>Enable</Networking>
  <MappedFolders>
    <MappedFolder><HostFolder>$inDir</HostFolder><SandboxFolder>C:\wacb\in</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$outDir</HostFolder><SandboxFolder>C:\wacb\out</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder>
  </MappedFolders>
  <LogonCommand><Command>cmd.exe /c C:\wacb\in\inside.cmd</Command></LogonCommand>
</Configuration>
"@ | Set-Content $config -Encoding UTF8

if ($Reuse) {
    # Same sandbox and sign-in session: run the driver again, in update mode.
    Write-Host "Updating the open sandbox to WAC Court Booker $version. Results: $outDir"
    # One argument string with the command quoted: Start-Process doesn't quote array items,
    # so the command would otherwise reach wsb split at its spaces.
    Start-Process wsb.exe -WindowStyle Hidden -ArgumentList ("exec --id $($running[0]) -r ExistingLogin " +
        '-c "cmd.exe /c C:\wacb\in\inside.cmd"')
} else {
    Write-Host "Testing WAC Court Booker $version in Windows Sandbox. Results: $outDir"
    Start-Process WindowsSandbox.exe -ArgumentList "`"$config`""
    @{ run = $run; inDir = $inDir; outDir = $outDir } | ConvertTo-Json | Set-Content $current
}

$progress = Join-Path $outDir 'progress.log'
$done = Join-Path $outDir 'done.json'
$shown = 0
$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
while ((Get-Date) -lt $deadline -and -not (Test-Path $done)) {
    Start-Sleep 5
    if (Test-Path $progress) {
        $lines = @(Get-Content $progress)
        $lines | Select-Object -Skip $shown | ForEach-Object { Write-Host "  $_" }
        $shown = $lines.Count
    }
}
if (Test-Path $progress) { Get-Content $progress | Select-Object -Skip $shown | ForEach-Object { Write-Host "  $_" } }

if (-not $KeepOpen) {
    foreach ($id in Get-SandboxIds) { & wsb.exe stop --id $id 2>$null | Out-Null }
    Get-Process WindowsSandboxRemoteSession, WindowsSandboxClient -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Remove-Item $current -ErrorAction SilentlyContinue
} else {
    Write-Host "The sandbox stays open. -Reuse updates just the app in it next time."
}

if (-not (Test-Path $done)) {
    Write-Host "Timed out after $TimeoutMinutes minutes. Partial results: $outDir" -ForegroundColor Red
    exit 2
}
$sum = Get-Content $done -Raw | ConvertFrom-Json
$colour = if ($sum.failed) { 'Red' } else { 'Green' }
Write-Host "`n$($sum.passed) passed, $($sum.failed) failed. Details: $outDir" -ForegroundColor $colour
exit ([int]($sum.failed -gt 0))
