@echo off
rem Runs at sign-in inside Windows Sandbox (the .wsb LogonCommand).
rem A clean sandbox has only Windows PowerShell 5.1, so the test driver is written for it.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File C:\wacb\in\inside.ps1
