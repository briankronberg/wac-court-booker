@echo off
rem WAC Court Booker setup. Double-click this file.
rem Finds PowerShell 7, installing it if it's missing, then runs setup.ps1 with it.
setlocal
set "PRIVATE_PWSH=%LOCALAPPDATA%\WAC Court Booker\pwsh\pwsh.exe"
set "PWSH="
where pwsh >nul 2>nul && set "PWSH=pwsh"
if not defined PWSH if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" set "PWSH=%ProgramFiles%\PowerShell\7\pwsh.exe"
if not defined PWSH if exist "%PRIVATE_PWSH%" set "PWSH=%PRIVATE_PWSH%"
if defined PWSH goto run

echo Installing PowerShell 7 ^(needed by WAC Court Booker^)...
where winget >nul 2>nul && winget install --id Microsoft.PowerShell -e --source winget --accept-source-agreements --accept-package-agreements
if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" (
  set "PWSH=%ProgramFiles%\PowerShell\7\pwsh.exe"
  goto run
)
rem No winget, or it failed: fetch PowerShell 7 into the app's own folder; no admin needed.
rem Windows PowerShell 5.1 does this one download because it's the only PowerShell present.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0get-pwsh.ps1"
if exist "%PRIVATE_PWSH%" set "PWSH=%PRIVATE_PWSH%"
if defined PWSH goto run
echo.
echo PowerShell 7 couldn't be installed. Install it from https://aka.ms/powershell, then run setup.cmd again.
pause
exit /b 1

:run
"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
if errorlevel 1 (
  echo.
  echo Setup didn't finish. The message above says why.
  pause
  exit /b 1
)
endlocal
