<#
.SYNOPSIS
  Installs WAC Court Booker for the current Windows user (run via setup.cmd).

.DESCRIPTION
  1. Finds Python 3.11+ (installs it with winget if missing).
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
#>
param(
    [switch]$NoWizard,
    [switch]$Dev,
    [string]$AppHome
)
$ErrorActionPreference = 'Stop'
$src = $PSScriptRoot
$app = if ($AppHome) { $AppHome } else { Join-Path $env:LOCALAPPDATA 'WAC Court Booker' }
New-Item -ItemType Directory -Force (Join-Path $app 'logs') | Out-Null
Start-Transcript -Path (Join-Path $app 'logs\setup.log') -Append | Out-Null

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

function Find-Python {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { return $null }
    foreach ($v in '3.14', '3.13', '3.12', '3.11') {
        try {
            $exe = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
        } catch { }
    }
    return $null
}

function Update-PathFromRegistry {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User') + ';' +
                (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps')
}

try {
    Write-Host "WAC Court Booker setup" -ForegroundColor Green
    Write-Host "Installing to $app"

    Step "Python"
    $py = Find-Python
    if (-not $py) {
        Write-Host "Python 3.11 or newer isn't installed. Installing the Python Install Manager..."
        winget install --id Python.PythonInstallManager -e --source winget --accept-source-agreements --accept-package-agreements
        Update-PathFromRegistry
        if (Get-Command py -ErrorAction SilentlyContinue) { & py install 3.13 }
        $py = Find-Python
    }
    if (-not $py) {
        Write-Host "Trying the standard Python installer instead..."
        winget install --id Python.Python.3.13 -e --source winget --accept-source-agreements --accept-package-agreements
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
    $lnk = Join-Path ([Environment]::GetFolderPath('Programs')) 'WAC Court Booker.lnk'
    $sh = New-Object -ComObject WScript.Shell
    $s = $sh.CreateShortcut($lnk)
    $s.TargetPath = Join-Path $venv 'Scripts\wac-booker.exe'
    if ($AppHome) { $s.Arguments = "--home `"$app`"" }
    $s.WorkingDirectory = $app
    $s.Description = 'Book WAC Hartland tennis courts when each booking window opens'
    $s.Save()
    Write-Host "Start-menu shortcut: WAC Court Booker"

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
