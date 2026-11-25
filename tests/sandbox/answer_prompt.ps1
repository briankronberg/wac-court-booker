# Inside the sandbox: answer setup's desktop-shortcut question with keypresses in a real
# console window (stdin not redirected), and check what setup did. Called by inside.ps1
# with the unzipped release folder; writes one JSON result per case. Windows PowerShell 5.1.
# Leaves the desktop shortcut and the saved answer as they were.
param([string]$Src, [string]$Out)
$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force $Out | Out-Null
$log = Join-Path $Out 'keyboard-test.txt'
Set-Content $log "keyboard test $(Get-Date -Format s)"
function Say($m) { Add-Content $log $m }
$cases = New-Object System.Collections.ArrayList

$app = Join-Path $env:LOCALAPPDATA 'WAC Court Booker'
$setupLog = Join-Path $app 'logs\setup.log'
$desk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'WAC Court Booker.lnk'
$choice = Join-Path $app 'desktop-shortcut.txt'
$src = $Src
Say "setup from: $src"
$hadLnk = Test-Path $desk
$hadChoice = if (Test-Path $choice) { (Get-Content $choice -Raw).Trim() } else { $null }
# Type into another process's console: attach to it and write key events into its input
# buffer. Unlike SendKeys this needs no active desktop (the sandbox window may be closed).
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public static class ConKeys {
  [StructLayout(LayoutKind.Explicit, CharSet=CharSet.Unicode)] struct KEY_EVENT {
    [FieldOffset(0)] public int bKeyDown; [FieldOffset(4)] public short wRepeatCount;
    [FieldOffset(6)] public short wVirtualKeyCode; [FieldOffset(8)] public short wVirtualScanCode;
    [FieldOffset(10)] public char UnicodeChar; [FieldOffset(12)] public int dwControlKeyState; }
  [StructLayout(LayoutKind.Explicit)] struct INPUT_RECORD { [FieldOffset(0)] public short EventType; [FieldOffset(4)] public KEY_EVENT Key; }
  [DllImport("kernel32.dll")] static extern bool FreeConsole();
  [DllImport("kernel32.dll")] static extern bool AttachConsole(int pid);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] static extern IntPtr CreateFile(string n, uint a, uint s, IntPtr sa, uint c, uint f, IntPtr t);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] static extern bool WriteConsoleInput(IntPtr h, INPUT_RECORD[] r, int n, out int w);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
  public static string Type(int pid, string text) {
    FreeConsole();
    if (!AttachConsole(pid)) return "attach failed " + Marshal.GetLastWin32Error();
    IntPtr h = CreateFile("CONIN$", 0xC0000000, 3, IntPtr.Zero, 3, 0, IntPtr.Zero);
    var recs = new INPUT_RECORD[text.Length * 2];
    for (int i = 0; i < text.Length; i++) {
      char c = text[i]; short vk = (short)(c == '\r' ? 0x0D : char.ToUpper(c));
      for (int d = 0; d < 2; d++) { recs[i*2+d].EventType = 1; recs[i*2+d].Key.bKeyDown = d == 0 ? 1 : 0;
        recs[i*2+d].Key.wRepeatCount = 1; recs[i*2+d].Key.wVirtualKeyCode = vk; recs[i*2+d].Key.UnicodeChar = c; }
    }
    int w; bool ok = WriteConsoleInput(h, recs, recs.Length, out w);
    CloseHandle(h); FreeConsole();
    return ok ? "typed " + w : "write failed " + Marshal.GetLastWin32Error();
  }
}
"@

function Run-Case($name, $keys, $wantLnk, $wantSaved) {
    $before = (Get-Content $setupLog -ErrorAction SilentlyContinue | Measure-Object).Count
    $p = Start-Process cmd.exe -ArgumentList "/c `"`"$src\setup.cmd`" -NoWizard`"" -PassThru -WindowStyle Normal
    $asked = $false
    $end = (Get-Date).AddMinutes(4)
    while (-not $p.HasExited -and (Get-Date) -lt $end) {
        Start-Sleep 1
        $new = @(Get-Content $setupLog -ErrorAction SilentlyContinue | Select-Object -Skip $before)
        # The question comes right after the Start-menu line; give it a moment to show.
        if ($keys -and -not $asked -and ($new -match 'Start-menu shortcut')) {
            Start-Sleep 3
            if (-not $p.HasExited) {
                Say "$name : $([ConKeys]::Type($p.Id, $keys))"; $asked = $true
            }
        }
    }
    if (-not $p.HasExited) {
        & taskkill.exe /f /t /pid $p.Id | Out-Null
        Say "$name : TIMED OUT (setup was still waiting)"
        [void]$cases.Add(@{ name = $name; ok = $false; detail = 'setup was still waiting for an answer' })
        return
    }
    $text = (Get-Content $setupLog -ErrorAction SilentlyContinue | Select-Object -Skip $before) -join "`n"
    $made = Test-Path $desk
    $saved = if (Test-Path $choice) { (Get-Content $choice -Raw).Trim() } else { '(none)' }
    $detail = "exit=$($p.ExitCode) typed=$asked desktop shortcut=$made saved answer=$saved"
    Say "$name : $detail"
    [void]$cases.Add(@{ name = $name; ok = ($p.ExitCode -eq 0 -and $made -eq $wantLnk -and $saved -eq $wantSaved -and ($asked -eq [bool]$keys)); detail = $detail })
}

# 1. Fresh: no shortcut, no saved answer. Answer y.
Remove-Item $desk, $choice -ErrorAction SilentlyContinue
Run-Case 'answer y' "y`r" $true 'Yes'
# 2. Saved yes, shortcut deleted: no question, shortcut comes back.
Remove-Item $desk -ErrorAction SilentlyContinue
Run-Case 'remembered yes, shortcut deleted' $null $true 'Yes'
# 3. Fresh again. Answer n.
Remove-Item $desk, $choice -ErrorAction SilentlyContinue
Run-Case 'answer n' "n`r" $false 'No'
# 4. Saved no: no question, no shortcut.
Run-Case 'remembered no' $null $false 'No'
# Put things back as they were.
Remove-Item $desk, $choice -ErrorAction SilentlyContinue
if ($hadChoice) { Set-Content $choice $hadChoice }
if ($hadLnk) { Copy-Item (Join-Path ([Environment]::GetFolderPath('Programs')) 'WAC Court Booker.lnk') $desk }
ConvertTo-Json -InputObject @($cases) | Set-Content (Join-Path $Out 'keyboard-test.json') -Encoding UTF8
Say 'done'


