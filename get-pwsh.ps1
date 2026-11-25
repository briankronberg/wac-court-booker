# Fetches PowerShell 7 into %LOCALAPPDATA%\WAC Court Booker\pwsh for PCs without
# winget. setup.cmd runs this with Windows PowerShell 5.1, the only PowerShell such a
# PC has; everything else in setup runs in PowerShell 7.
# The download is checked against the SHA-256 that Microsoft publishes for the release.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$version = '7.7.0'
$builds = @{
    'x64'   = '7C74E03B20A75B59715847439D046A6214B1863EE79B187872980F139BB4A05F'
    'arm64' = '5DC7440CD98F0BA786A44D7DB9205DF5058474FD4DB143CAF7171E8375F34F75'
}
$arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'x64' }
$name = "PowerShell-$version-win-$arch.zip"
$url = "https://github.com/PowerShell/PowerShell/releases/download/v$version/$name"
$dest = Join-Path $env:LOCALAPPDATA 'WAC Court Booker\pwsh'
$zip = Join-Path $env:TEMP $name

try {
    Write-Host "Downloading PowerShell $version ($arch)..."
    Invoke-WebRequest $url -OutFile $zip -UseBasicParsing
    $hash = (Get-FileHash $zip -Algorithm SHA256).Hash
    if ($hash -ne $builds[$arch]) { throw "the PowerShell download didn't match its published checksum" }
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Expand-Archive $zip -DestinationPath $dest
    Get-ChildItem $dest -Recurse -File | Unblock-File
    Write-Host "PowerShell 7 is in $dest"
    exit 0
}
catch {
    Write-Host "Couldn't install PowerShell 7: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Remove-Item $zip -ErrorAction SilentlyContinue
}
