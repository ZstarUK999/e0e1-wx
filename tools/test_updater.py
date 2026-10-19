import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from package.plugin_manager import updater

def plan(data=b'new',removed=None):
 return {'version':'2.0.0','changed':[{'path':'_internal/app.bin','sha256':hashlib.sha256(data).hexdigest(),'size':len(data),'url':'https://test/file'}],'removed':removed or []}

@pytest.fixture
def root(tmp_path,monkeypatch):
 monkeypatch.setattr(updater,'app_root',lambda:tmp_path)
 monkeypatch.setattr(updater.server_client,'cert_dir',lambda:tmp_path)
 return tmp_path

def test_manifest_excludes_windows_paths_and_credentials(root):
 for relative in ['license.bin','_staging/x/payload.bin','logs/run.log','apply_update.cmd','plugins.json','_internal/app.bin']:
  p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'x')
 assert list(updater.local_manifest())==['_internal/app.bin']

@pytest.mark.parametrize('path',['../outside','C:/outside','/root','_staging/file','logs/file','LICENSE.BIN','a/../../b','a:ads','CON','a/../b'])
def test_rejects_unsafe_update_paths(root,path):
 p=plan();p['changed'][0]['path']=path
 with pytest.raises(ValueError):updater.prepare(p)
 assert not updater.pending_update()

def test_verified_download_retry_reuse_and_progress(root,monkeypatch):
 calls=[];progress=[]
 def download(url,target,ca,callback):
  calls.append(url);target.parent.mkdir(parents=True,exist_ok=True)
  target.write_bytes(b'bad' if len(calls)==1 else b'new');callback(3)
 monkeypatch.setattr(updater,'_download',download);monkeypatch.setattr(updater.time,'sleep',lambda t:None)
 updater.prepare(plan(),progress=lambda *p:progress.append(p))
 assert len(calls)==2 and progress[-1][:2]==(3,3)
 updater.prepare(plan());assert len(calls)==2
 metadata=json.loads(updater.pending_update().read_text());assert 'url' not in metadata['changed'][0]
 assert (root/updater.APPLY_SCRIPT_NAME).exists()

def test_failed_checksum_never_marks_ready(root,monkeypatch):
 def download(url,target,*args):target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'bad')
 monkeypatch.setattr(updater,'_download',download);monkeypatch.setattr(updater.time,'sleep',lambda t:None)
 with pytest.raises(RuntimeError):updater.prepare(plan())
 assert updater.pending_update() is None

def test_removal_only_update_is_ready(root):
 updater.prepare({'version':'2.0.0','changed':[],'removed':['old.dll']})
 assert updater.pending_update()

def test_launch_waits_parent_and_keeps_package_identity(root,monkeypatch):
 monkeypatch.setattr(updater,'_download',lambda url,target,*args:(target.parent.mkdir(parents=True,exist_ok=True),target.write_bytes(b'new')))
 updater.prepare(plan());(root/'license.bin').write_bytes(b'identity')
 monkeypatch.setattr(updater.sys,'frozen',True,raising=False)
 monkeypatch.setattr(updater.sys,'executable',str(root/'e0e1-wx-plugins.exe'))
 monkeypatch.setattr(updater,'build_info',lambda:SimpleNamespace(is_release=True))
 calls=[];monkeypatch.setattr(updater.subprocess,'Popen',lambda *a,**k:calls.append((a,k)))
 assert updater.launch_pending();assert '-ParentId' in calls[0][0][0]
 assert (root/'license.bin').read_bytes()==b'identity'
 (root/'_staging/2.0.0/payload/_internal/app.bin').write_bytes(b'bad')
 with pytest.raises(RuntimeError):updater.launch_pending()
 assert len(calls)==1

def test_source_run_does_not_update(root,monkeypatch):
 monkeypatch.delattr(updater.sys,'frozen',raising=False)
 monkeypatch.setattr(updater,'build_info',lambda:SimpleNamespace(is_release=True))
 monkeypatch.setattr(updater.server_client,'check_update',lambda *a,**k:pytest.fail('source should never update dist'))
 assert updater.check(player_id='1') is None


@pytest.mark.parametrize('fail',[False,True])
def test_real_windows_installer_and_rollback(root,fail):
 import shutil,subprocess
 powershell=shutil.which('powershell.exe')
 if not powershell:pytest.skip('Windows PowerShell not installed')
 (root/'app.bin').write_bytes(b'old')
 (root/'bad.bin').write_bytes(b'old bad')
 (root/'obsolete.dll').write_bytes(b'old dll')
 (root/'license.bin').write_bytes(b'identity')
 payload=root/'_staging/2.0.0/payload';payload.mkdir(parents=True)
 items=[]
 for name,data in [('app.bin',b'new'),('added.bin',b'added'),('bad.bin',b'new bad')]:
  (payload/name).write_bytes(data)
  items.append({'path':name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()})
 metadata={'version':'2.0.0','changed':items,'removed':['obsolete.dll'],'exe':'app.exe'}
 pending=root/'_staging/pending.json';pending.write_text(json.dumps(metadata))
 script=updater.APPLY_SCRIPT
 if fail:
  script=script.replace('    Copy-Item -LiteralPath (SafePath $payload $item.path)',
      "    if($item.path -eq 'bad.bin'){throw 'simulated locked file'}\n    Copy-Item -LiteralPath (SafePath $payload $item.path)")
 path=root/'installer.ps1';path.write_text(script,encoding='utf-8-sig')
 wrapper=root/'run.ps1'
 wrapper.write_text("param([string]$Root)\nfunction Start-Process { param($FilePath,$WorkingDirectory,$WindowStyle) Set-Content -LiteralPath (Join-Path $WorkingDirectory 'launched.txt') -Value $FilePath; Set-Content -LiteralPath (Join-Path $WorkingDirectory 'launch-style.txt') -Value $WindowStyle -Encoding UTF8 }\n& (Join-Path $Root 'installer.ps1') -AppRoot $Root -ParentId 99999999\n",encoding='utf-8-sig')
 result=subprocess.run([powershell,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(wrapper),'-Root',str(root)],capture_output=True,text=True,timeout=20)
 assert result.returncode==0,result.stderr
 assert (root/'license.bin').read_bytes()==b'identity'
 assert not pending.exists()
 if fail:
  assert (root/'app.bin').read_bytes()==b'old'
  assert (root/'bad.bin').read_bytes()==b'old bad'
  assert not (root/'added.bin').exists()
  assert (root/'obsolete.dll').exists()
  assert (root/'_staging/failed.json').exists()
  assert not (root/'launched.txt').exists()
 else:
  assert (root/'app.bin').read_bytes()==b'new'
  assert (root/'bad.bin').read_bytes()==b'new bad'
  assert (root/'added.bin').read_bytes()==b'added'
  assert not (root/'obsolete.dll').exists()
  assert (root/'launched.txt').exists()
  assert (root/'launch-style.txt').read_text(encoding='utf-8-sig').strip()=='Normal'
