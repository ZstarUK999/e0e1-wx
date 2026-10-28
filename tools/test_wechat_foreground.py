"""Exercise the actual PowerShell activation function without desktop input."""
import json
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'package/plugin_manager/wechat_recent.ps1'
if not SCRIPT.exists():
    SCRIPT = Path(__file__).with_name('wechat_recent.ps1')


@pytest.mark.parametrize('scenario', ['already', 'normal', 'fallback', 'denied', 'throws', 'shared'])
def test_activation_recovers_foreground_and_releases_input_queues(tmp_path, scenario):
    source = SCRIPT.read_text(encoding='utf-8-sig')
    activate = source[source.index('function Activate('):source.index('function Click(')]
    fake = r'''
Add-Type @"
using System;
using System.Collections.Generic;
public static class GameEntryInput {
 public static string Scenario;
 public static int Attempts;
 public static IntPtr Foreground = new IntPtr(99);
 public static List<string> Events = new List<string>();
 public static bool IsIconic(IntPtr h) {return false;}
 public static bool ShowWindowAsync(IntPtr h,int n) {return true;}
 public static IntPtr GetForegroundWindow() {return Foreground;}
 public static bool SetForegroundWindow(IntPtr h) {
  Attempts++;
  if(Scenario=="throws" && Attempts==2) throw new Exception("activation failed");
  if(Scenario=="normal" || ((Scenario=="fallback" || Scenario=="shared") && Attempts==2)) Foreground=h;
  return Foreground==h;
 }
 public static uint GetCurrentThreadId() {return 1;}
 public static uint GetWindowThreadProcessId(IntPtr h,IntPtr p) {return Scenario=="shared" ? 2u : h==new IntPtr(16) ? 3u : 2u;}
 public static bool AttachThreadInput(uint a,uint b,bool attach) {Events.Add(b+":"+attach);return true;}
 public static bool BringWindowToTop(IntPtr h) {return true;}
}
"@
function Start-Sleep {param($Milliseconds)}
$ErrorActionPreference='Stop'
$diagnostics=@{}
'''
    setup = f"[GameEntryInput]::Scenario='{scenario}'\n"
    if scenario == 'already':
        setup += '[GameEntryInput]::Foreground=[IntPtr]16\n'
    command = fake + activate + setup + r'''
$message=''
try {Activate ([PSCustomObject]@{Current=[PSCustomObject]@{NativeWindowHandle=16}})}
catch {$message=$_.Exception.Message}
@{attempts=[GameEntryInput]::Attempts;events=@([GameEntryInput]::Events);message=$message;diagnostics=$diagnostics} | ConvertTo-Json -Depth 5 -Compress
'''
    path = tmp_path / 'activation.ps1'
    path.write_text(command, encoding='utf-8-sig')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(path)],
                            capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    payload = json.loads(result.stdout.decode('utf-8-sig'))
    assert payload['attempts'] == (0 if scenario == 'already' else 1 if scenario == 'normal' else 2)
    if scenario in ('already', 'normal'):
        assert payload['events'] == []
    elif scenario == 'shared':
        assert payload['events'] == ['2:True', '2:False']
    else:
        assert payload['events'] == ['2:True', '3:True', '2:False', '3:False']
    if scenario == 'denied':
        assert payload['message']
        assert payload['diagnostics'] == {'targetHwnd': '16', 'foregroundHwnd': '99'}
    elif scenario == 'throws':
        assert 'activation failed' in payload['message']
    else:
        assert payload['message'] == ''
