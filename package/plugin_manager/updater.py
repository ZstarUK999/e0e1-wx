"""Download verified deltas and apply them after the packaged application exits."""
from __future__ import annotations
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time
from . import server_client
from .build_info import current as build_info

LOG=logging.getLogger('plugin_manager.updater')
STAGING_DIR_NAME='_staging'
APPLY_SCRIPT_NAME='apply_update.ps1'
EXCLUDED_NAMES={'license.bin','apply_update.cmd',APPLY_SCRIPT_NAME,'plugins.json','plugin_manager.log','tomb_raid_history.json'}

def app_root():
    if getattr(sys,'frozen',False):return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]/'dist'/'e0e1-wx-plugins'

def _relative(value):
    value=str(value).replace('\\','/')
    parts=value.split('/')
    if not value or any(not p or p in ('.','..') or p.endswith(('.', ' ')) or re.search(r'[<>:"|?*\x00-\x1f]',p) or
        re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',p,re.I) for p in parts):
        raise ValueError('非法更新路径')
    return PurePosixPath(value).as_posix()

def _is_managed(relative):
    try:relative=_relative(relative)
    except ValueError:return False
    return relative.split('/')[0].lower() not in ('_staging','logs') and relative.split('/')[-1].lower() not in EXCLUDED_NAMES

def _target(root,relative):
    target=root/_relative(relative)
    if not target.resolve().is_relative_to(root.resolve()):raise ValueError('更新路径越界')
    return target

def _digest(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def local_manifest():
    root=app_root();result={}
    if not root.is_dir():return result
    for path in root.rglob('*'):
        relative=path.relative_to(root).as_posix()
        if path.is_file() and _is_managed(relative):
            _target(root,relative)
            result[relative]=_digest(path)
    return result

def _validate(plan):
    version=str(plan['version'])
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}',version) or '..' in version:raise ValueError('非法更新版本')
    seen=set()
    for item in plan.get('changed',[]):
        path=_relative(item['path'])
        if not _is_managed(path) or path.lower() in seen:raise ValueError('更新清单包含受保护或重复文件')
        seen.add(path.lower())
        target=_target(app_root(),path)
        if target.exists() and not target.is_file():raise ValueError('更新目标不是文件')
        if not re.fullmatch('[0-9a-fA-F]{64}',item['sha256']):raise ValueError('非法文件校验值')
        if type(item.get('size')) is not int or item['size']<0:raise ValueError('非法文件大小')
    for relative in plan.get('removed',[]):
        path=_relative(relative)
        if not _is_managed(path) or path.lower() in seen:raise ValueError('删除清单包含受保护或重复文件')
        seen.add(path.lower())
        target=_target(app_root(),path)
        if target.exists() and not target.is_file():raise ValueError('更新目标不是文件')
    return version

def _download(url,target,ca_path,progress=None):
    import httpx
    target.parent.mkdir(parents=True,exist_ok=True)
    partial=target.with_name(target.name+'.download')
    with httpx.stream('GET',url,verify=str(ca_path),timeout=httpx.Timeout(5.0,connect=2.0,read=2.0),follow_redirects=True) as response:
        response.raise_for_status()
        with partial.open('wb') as handle:
            for block in response.iter_bytes(256*1024):
                handle.write(block)
                if progress:progress(len(block))
    os.replace(partial,target)

def _pending_path():return app_root()/STAGING_DIR_NAME/'pending.json'

def prepare(plan,progress=None,cancel_event=None):
    version=_validate(plan)
    def cancelled():
        if cancel_event is not None and cancel_event.is_set():raise RuntimeError('更新下载已取消')
    cancelled()
    stage=app_root()/STAGING_DIR_NAME/version
    payload=stage/'payload';payload.mkdir(parents=True,exist_ok=True)
    total=sum(item['size'] for item in plan.get('changed',[]));done=0
    for item in plan.get('changed',[]):
        cancelled()
        target=_target(payload,item['path'])
        if not(target.is_file() and target.stat().st_size==item['size'] and _digest(target)==item['sha256'].lower()):
            for attempt in range(3):
                current=[0]
                def received(size):
                    cancelled()
                    current[0]+=size
                    if progress:progress(min(done+current[0],total),total,item['path'])
                try:
                    _download(item['url'],target,server_client.cert_dir()/'ca.pem',received)
                    if target.stat().st_size!=item['size'] or _digest(target)!=item['sha256'].lower():
                        raise RuntimeError('文件校验失败：'+item['path'])
                    break
                except Exception:
                    cancelled()
                    if attempt==2:raise
                    if cancel_event is not None:cancel_event.wait(.5*(attempt+1))
                    else:time.sleep(.5*(attempt+1))
        done+=item['size']
        if progress:progress(done,total,item['path'])
    cancelled()
    metadata={'version':version,'changed':[{k:item[k] for k in ('path','sha256','size')} for item in plan.get('changed',[])],
              'removed':plan.get('removed',[]),'exe':Path(sys.executable).name if getattr(sys,'frozen',False) else 'e0e1-wx-plugins.exe'}
    script=app_root()/APPLY_SCRIPT_NAME
    script.write_text(APPLY_SCRIPT,encoding='utf-8-sig')
    pending=_pending_path();temporary=pending.with_suffix('.tmp')
    temporary.write_text(json.dumps(metadata,ensure_ascii=False),encoding='utf-8')
    os.replace(temporary,pending)
    LOG.info('更新已校验并准备就绪：%s，%d 个文件',version,len(metadata['changed']))
    return script

def pending_update():
    path=_pending_path()
    return path if path.is_file() else None

def launch_pending():
    if not getattr(sys,'frozen',False) or not build_info().is_release:return False
    pending=pending_update()
    if not pending:return False
    plan=json.loads(pending.read_text(encoding='utf-8'));version=_validate(plan)
    if _relative(plan['exe'])!=Path(sys.executable).name:raise ValueError('更新入口不匹配')
    payload=app_root()/STAGING_DIR_NAME/version/'payload'
    for item in plan['changed']:
        target=_target(payload,item['path'])
        if not target.is_file() or target.stat().st_size!=item['size'] or _digest(target)!=item['sha256'].lower():
            raise RuntimeError('待安装更新已损坏：'+item['path'])
    script=app_root()/APPLY_SCRIPT_NAME
    script.write_text(APPLY_SCRIPT,encoding='utf-8-sig')
    subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-WindowStyle','Hidden',
        '-File',str(script),'-AppRoot',str(app_root()),'-ParentId',str(os.getpid())],cwd=app_root(),
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return True

def check(*,player_id):
    if not getattr(sys,'frozen',False) or not build_info().is_release:return None
    return server_client.check_update(local_manifest(),player_id=player_id)

APPLY_SCRIPT=r'''param([string]$AppRoot,[int]$ParentId)
$ErrorActionPreference='Stop'
$pending=Join-Path $AppRoot '_staging/pending.json'
$log=Join-Path $AppRoot '_staging/update.log'
$changed=@();$removed=@();$applied=@();$saved=@();$backup=$null
try {
  $parent=Get-Process -Id $ParentId -ErrorAction SilentlyContinue
  if($parent -and -not $parent.WaitForExit(120000)){throw 'Application did not exit'}
  $plan=Get-Content -LiteralPath $pending -Raw -Encoding UTF8 | ConvertFrom-Json
  $stage=Join-Path (Join-Path $AppRoot '_staging') $plan.version
  $payload=Join-Path $stage 'payload'
  $backup=Join-Path $stage ('backup-'+[guid]::NewGuid().ToString('N'))
  function SafePath([string]$base,[string]$relative){
    $base=[IO.Path]::GetFullPath($base).TrimEnd('\')+'\'
    $full=[IO.Path]::GetFullPath((Join-Path $base $relative))
    if(-not $full.StartsWith($base,[StringComparison]::OrdinalIgnoreCase)){throw 'Update path outside application'}
    return $full
  }
  function FileHash([string]$path){
    $stream=[IO.File]::OpenRead($path)
    $hash=[Security.Cryptography.SHA256]::Create()
    try{return [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-','')}
    finally{$stream.Dispose();$hash.Dispose()}
  }
  foreach($item in $plan.changed){
    $source=SafePath $payload $item.path
    if((FileHash $source) -ne $item.sha256){throw 'Staged checksum mismatch'}
    $null=SafePath $AppRoot $item.path
  }
  foreach($relative in @($plan.removed)){$null=SafePath $AppRoot $relative}
  # Back up every destination before changing any live files.
  foreach($relative in (@($plan.changed | ForEach-Object {$_.path})+@($plan.removed))){
    $target=SafePath $AppRoot $relative
    if(Test-Path -LiteralPath $target){
      $copy=SafePath $backup $relative
      $null=New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($copy)) -Force
      Copy-Item -LiteralPath $target -Destination $copy -Force
      $saved+=,$relative
    }
  }
  foreach($item in $plan.changed){
    $target=SafePath $AppRoot $item.path
    $null=New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($target)) -Force
    $applied+=,$item.path
    Copy-Item -LiteralPath (SafePath $payload $item.path) -Destination $target -Force
    if((FileHash $target) -ne $item.sha256){throw 'Installed checksum mismatch'}
  }
  foreach($relative in @($plan.removed)){
    $target=SafePath $AppRoot $relative
    if(Test-Path -LiteralPath $target){$applied+=,$relative;Remove-Item -LiteralPath $target -Force}
  }
  Remove-Item -LiteralPath $pending -Force
  Add-Content -LiteralPath $log -Value ('SUCCESS '+$plan.version)
  Start-Process -FilePath (SafePath $AppRoot $plan.exe) -WorkingDirectory $AppRoot -WindowStyle Normal
} catch {
  $failure=$_.Exception.Message
  foreach($relative in $applied){
    try{
      $target=SafePath $AppRoot $relative
      if($saved -contains $relative){Copy-Item -LiteralPath (SafePath $backup $relative) -Destination $target -Force}
      elseif(Test-Path -LiteralPath $target){Remove-Item -LiteralPath $target -Force}
    }catch{Add-Content -LiteralPath $log -Value ('ROLLBACK FAILED '+$relative+' '+$_)}
  }
  Add-Content -LiteralPath $log -Value ('FAILED '+$failure)
  if(Test-Path -LiteralPath $pending){Move-Item -LiteralPath $pending -Destination (Join-Path $AppRoot '_staging/failed.json') -Force}
  # Keep staging and backups for diagnosis/retry. Do not silently launch a mixed build.
}
'''
