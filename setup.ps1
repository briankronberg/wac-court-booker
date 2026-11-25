<#
.SYNOPSIS
  Installs WAC Court Booker for the current Windows user (run via setup.cmd).

.DESCRIPTION
  1. Finds Python 3.11+. If it's missing, installs Python 3.13 with winget, or on a PC
     without winget the official Python 3.14 installer from python.org (checked).
  2. Creates a private Python environment in %LOCALAPPDATA%\WAC Court Booker\venv
     and installs the app into it.
  3. Downloads the app's own Chromium (Playwright, headless shell).
  4. Registers the toast sender name and adds a Start-menu shortcut.
  5. Starts the setup wizard (unless -NoWizard).

  Run it again any time to update the app from this folder; bookings and
  logins are kept.

.PARAMETER NoWizard
  Install only; don't start the wizard.
.PARAMETER Dev
  Install the app from this folder in editable mode (for development).
.PARAMETER AppHome
  Install somewhere other than %LOCALAPPDATA%\WAC Court Booker.
.PARAMETER DesktopShortcut
  Ask (default): ask once whether to put a shortcut on the desktop, and remember the
  answer; an existing desktop shortcut is just refreshed. Yes or No: don't ask.
#>
param(
    [switch]$NoWizard,
    [switch]$Dev,
    [string]$AppHome,
    [ValidateSet('Ask', 'Yes', 'No')][string]$DesktopShortcut = 'Ask'
)
$ErrorActionPreference = 'Stop'
$src = $PSScriptRoot
$app = if ($AppHome) { $AppHome } else { Join-Path $env:LOCALAPPDATA 'WAC Court Booker' }
New-Item -ItemType Directory -Force (Join-Path $app 'logs') | Out-Null
Start-Transcript -Path (Join-Path $app 'logs\setup.log') -Append | Out-Null

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

function Test-Python($exe) {
    try {
        $ok = & $exe -c "import sys; print(sys.version_info >= (3, 11))" 2>$null
        return ($LASTEXITCODE -eq 0 -and "$ok".Trim() -eq 'True')
    } catch { return $false }
}

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in '3.14', '3.13', '3.12', '3.11') {
            try {
                $exe = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $exe) { return "$exe".Trim() }
            } catch { }
        }
    }
    # Standard per-user installs, in case the py launcher isn't on PATH yet.
    foreach ($v in '314', '313', '312', '311') {
        foreach ($root in @((Join-Path $env:LOCALAPPDATA 'Programs\Python'), $env:ProgramFiles)) {
            $exe = Join-Path $root "Python$v\python.exe"
            if ((Test-Path $exe) -and (Test-Python $exe)) { return $exe }
        }
    }
    return $null
}

function Install-PythonFromPythonOrg {
    # The official installer, for the current user only (no admin). Pinned and checked:
    # the SHA-256 below is of the PSF-signed file, and the signature is checked too.
    $version = '3.14.10'
    $builds = @{
        'amd64' = '92480239264744FE0386A1BD8275786FEFA126E3129E56A68E22B52C73329965'
        'arm64' = '5B9547E4EDAE2F6FB2FBFEC5E26CF91B4EA191E3B07F7727D5A2C5C2CCA93ED3'
    }
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'amd64' }
    $name = "python-$version-$arch.exe"
    $exe = Join-Path $env:TEMP $name
    try {
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest "https://www.python.org/ftp/python/$version/$name" -OutFile $exe
        if ((Get-FileHash $exe -Algorithm SHA256).Hash -ne $builds[$arch]) {
            throw "the Python download didn't match its expected checksum"
        }
        $sig = Get-AuthenticodeSignature $exe
        if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'O=Python Software Foundation') {
            throw "the Python download isn't signed by the Python Software Foundation"
        }
        # /passive shows the installer's progress bar (it can take several minutes) but
        # asks nothing. Only the parts the app needs: core, exe, lib (has venv and
        # ensurepip) and the py launcher; no docs, Tcl/Tk, headers, tests or shortcuts.
        Write-Host "Installing Python $version. A Python progress window shows while it works."
        $p = Start-Process $exe -Wait -PassThru -ArgumentList @(
            '/passive', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1',
            'InstallLauncherAllUsers=0', 'Include_doc=0', 'Include_tcltk=0', 'Include_dev=0',
            'Include_test=0', 'Include_pip=0', 'Include_debug=0', 'Include_symbols=0',
            'Shortcuts=0', 'AssociateFiles=0')
        if ($p.ExitCode) { throw "the Python installer stopped with code $($p.ExitCode)" }
    }
    finally { Remove-Item $exe -ErrorAction SilentlyContinue }
}

function Update-PathFromRegistry {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User') + ';' +
                (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps')
}

try {
    Write-Host "WAC Court Booker setup" -ForegroundColor Green
    Write-Host "Installing to $app"
    # Files from a downloaded zip carry the "from the internet" mark; clear it.
    Get-ChildItem -Path $src -Recurse -File | Unblock-File -ErrorAction SilentlyContinue

    Step "Python"
    $py = Find-Python
    $haveWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)
    if (-not $py -and $haveWinget) {
        Write-Host "Python 3.11 or newer isn't installed. Installing Python 3.13 (this takes a minute)..."
        winget install --id Python.Python.3.13 -e --source winget --scope user --silent --accept-source-agreements --accept-package-agreements
        Update-PathFromRegistry
        $py = Find-Python
    }
    if (-not $py) {
        if ($haveWinget) { Write-Host "winget didn't install it; downloading Python from python.org instead..." }
        else { Write-Host "Python 3.11 or newer isn't installed. Downloading it from python.org (this takes a minute)..." }
        Install-PythonFromPythonOrg
        Update-PathFromRegistry
        $py = Find-Python
    }
    if (-not $py) {
        throw "Python couldn't be installed automatically. Install Python 3.13 from python.org (tick 'Add to PATH'), then run setup.cmd again."
    }
    Write-Host "Using $py"

    Step "App environment"
    $venv = Join-Path $app 'venv'
    $vpy = Join-Path $venv 'Scripts\python.exe'
    # An update can't replace the app's files while the app runs (the menu, or a booking).
    # Never stop it: ask, and carry on by itself once it's closed.
    $venvDir = (Join-Path $venv '') -replace '\\$', ''
    function Get-AppProcess {
        @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -and $_.Path.StartsWith($venvDir + '\', [StringComparison]::OrdinalIgnoreCase) })
    }
    if ((Get-AppProcess).Count) {
        Write-Host "WAC Court Booker is open. Close its menu window to continue (if a booking is running, wait for it to finish)." -ForegroundColor Yellow
        $until = (Get-Date).AddMinutes(5)
        while ((Get-AppProcess).Count -and (Get-Date) -lt $until) { Start-Sleep 2 }
        if ((Get-AppProcess).Count) { throw "WAC Court Booker is still open. Close it, then run setup.cmd again." }
        Write-Host "Closed. Carrying on."
    }
    if ((Test-Path $vpy) -and -not (Test-Python $vpy)) {
        Write-Host "The app's Python environment is broken (Python was updated or removed); rebuilding it."
        Remove-Item -Recurse -Force $venv
    }
    if (-not (Test-Path $vpy)) { & $py -m venv $venv; if ($LASTEXITCODE) { throw "couldn't create $venv" } }
    & $vpy -m pip install --quiet --disable-pip-version-check --upgrade pip
    if ($Dev) { & $vpy -m pip install --quiet --disable-pip-version-check -e $src }
    else { & $vpy -m pip install --quiet --disable-pip-version-check --upgrade $src }
    if ($LASTEXITCODE) { throw "installing the app's Python packages failed (see above)" }

    Step "Browser"
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $app 'browsers'
    & $vpy -m playwright install --only-shell chromium
    if ($LASTEXITCODE) {
        Write-Host "The app's own browser didn't download (antivirus or a company network can block it)." -ForegroundColor Yellow
        Write-Host "The wizard will set it to use Microsoft Edge instead." -ForegroundColor Yellow
    }

    Step "Notifications and Start menu"
    $key = 'HKCU:\Software\Classes\AppUserModelId\WACCourtBooker'
    New-Item -Path $key -Force | Out-Null
    Set-ItemProperty -Path $key -Name DisplayName -Value 'WAC Court Booker'
    $sh = New-Object -ComObject WScript.Shell
    function Save-Shortcut($path) {
        $s = $sh.CreateShortcut($path)
        $s.TargetPath = Join-Path $venv 'Scripts\wac-booker.exe'
        if ($AppHome) { $s.Arguments = "--home `"$app`"" }
        $s.WorkingDirectory = $app
        $s.Description = 'Book WAC Hartland tennis courts when each booking window opens'
        $s.Save()
    }
    Save-Shortcut (Join-Path ([Environment]::GetFolderPath('Programs')) 'WAC Court Booker.lnk')
    Write-Host "Start-menu shortcut: WAC Court Booker"

    # Desktop shortcut: asked once (the answer is remembered), so updates don't ask again.
    $desk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'WAC Court Booker.lnk'
    $choiceFile = Join-Path $app 'desktop-shortcut.txt'
    $want = $DesktopShortcut
    if ($want -eq 'Ask') {
        if (Test-Path $desk) { $want = 'Yes' }
        elseif (Test-Path $choiceFile) { $want = (Get-Content $choiceFile -Raw).Trim() }
        elseif ([Console]::IsInputRedirected) { $want = 'No' }   # unattended: don't guess, ask next time
        else {
            $a = Read-Host "Put a WAC Court Booker shortcut on your desktop too, to open the app easily? (Y/n)"
            $want = if ($a -match '^\s*n') { 'No' } else { 'Yes' }
            Set-Content $choiceFile $want
        }
    } else {
        Set-Content $choiceFile $want
    }
    if ($want -eq 'Yes') {
        Save-Shortcut $desk
        Write-Host "Desktop shortcut: WAC Court Booker"
    }

    $ver = & $vpy -m wacbooker version
    Write-Host "`nInstalled WAC Court Booker $ver." -ForegroundColor Green

    if (-not $NoWizard) {
        $wargs = @()
        if ($AppHome) { $wargs += @('--home', $app) }
        & (Join-Path $venv 'Scripts\wac-booker.exe') @wargs setup
    }
    exit 0
}
catch {
    Write-Host "`nSetup stopped: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Stop-Transcript | Out-Null
}
