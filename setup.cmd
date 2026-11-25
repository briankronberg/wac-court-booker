@echo off
rem WAC Court Booker setup. Double-click this file.
rem Installs PowerShell 7 if it's missing, then runs setup.ps1 with it.
setlocal
set "PWSH=pwsh"
where pwsh >nul 2>nul
if errorlevel 1 (
  if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" (
    set "PWSH=%ProgramFiles%\PowerShell\7\pwsh.exe"
  ) else (
    echo Installing PowerShell 7 ^(needed by WAC Court Booker^)...
    winget install --id Microsoft.PowerShell -e --source winget --accept-source-agreements --accept-package-agreements
    set "PWSH=%ProgramFiles%\PowerShell\7\pwsh.exe"
  )
)
"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
if errorlevel 1 (
  echo.
  echo Setup didn't finish. The message above says why.
  pause
  exit /b 1
)
endlocal
