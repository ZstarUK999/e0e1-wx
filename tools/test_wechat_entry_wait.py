"""Execute the UIA stage with fake entries; never activate or click real windows."""
import json
from pathlib import Path
import subprocess

import pytest


SCRIPT=Path(__file__).resolve().parents[1]/'package/plugin_manager/wechat_recent.ps1'
if not SCRIPT.exists():SCRIPT=Path(__file__).with_name('wechat_recent.ps1')


@pytest.mark.parametrize('mode,scenario,reads',[
    ('Probe','ready',1),('Probe','missing',1),('WaitPrepare','loading',3),
    ('WaitPrepare','ambiguous',1),('WaitPrepare','missing',2)])
def test_entry_stage_reuses_result_and_waits_only_after_navigation(tmp_path,mode,scenario,reads):
    source=SCRIPT.read_text(encoding='utf-8-sig')
    stage=source[source.index('function Invoke-Stage {'):source.index('if($Worker) {')]
    setup=r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$script:reads=0
function WechatWindows {return @()}
function Activate($window) {}
function EntryCache($entry) {return @{runtimeId=@(1,2);x=10;y=20}}
function Start-Sleep {param($Milliseconds);if($scenario -eq 'missing'){ Set-Variable -Name deadline -Value ([DateTime]::UtcNow.AddSeconds(-1)) -Scope 1 }}
function Entry {
 $script:reads++
 if($scenario -eq 'ambiguous'){throw 'multiple release entries'}
 if($scenario -eq 'missing' -or ($scenario -eq 'loading' -and $script:reads -lt 3)){return $null}
 return @{Window='fake';Element=[PSCustomObject]@{Current=[PSCustomObject]@{BoundingRectangle=[PSCustomObject]@{IsEmpty=$false;Width=100;Height=30}}}}
}
'''
    command=setup+stage+f"\n$Mode='{mode}';$scenario='{scenario}'\n"+r'''
$result=Invoke-Stage | ConvertFrom-Json
@{reads=$script:reads;result=$result} | ConvertTo-Json -Depth 8 -Compress
'''
    path=tmp_path/'stage.ps1'
    path.write_text(command,encoding='utf-8-sig')
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(path)],capture_output=True,timeout=15)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    value=json.loads(result.stdout.decode('utf-8-sig'))
    assert value['reads']==reads
    response=value['result']
    if scenario in ('ready','loading'):
        assert response['ok'] and response['found']
        assert response['cache']['runtimeId']==[1,2]
    elif mode=='Probe':
        assert response['ok'] and not response['found']
    else:
        assert not response['ok'] and response['message']
