"""Reopen the release game from WeChat's 最近使用 UI, without URL shortcuts."""
from __future__ import annotations
import asyncio
import json
import logging
import os
from pathlib import Path
import subprocess
import time
import tempfile
from . import wechat_position_cache as positions

LOG=logging.getLogger('plugin_manager')


def _save_position(kind,value):
    try:positions.save(kind,value)
    except OSError as exc:LOG.warning('微信位置缓存保存失败，仍可正常定位：%s',exc)


async def _recent_ui(mode, entry_cache=None):
    executable=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    extra=[]
    with tempfile.TemporaryDirectory(prefix="wechat-entry-") as folder:
        if entry_cache is not None:
            source=Path(folder)/"entry.json"
            source.write_text(json.dumps(entry_cache),encoding="utf-8")
            extra.extend(["-EntryCachePath",str(source)])
        hot_modes={'Probe','EntryPrepare','EntryOpen','WaitPrepare','Navigate','CachedPrepare','CachedOpen'}
        failed=False
        if mode in hot_modes:
            from .wechat_ui_worker import request
            result=await request(mode,str(source) if entry_cache is not None else '')
        else:
            proc=await asyncio.create_subprocess_exec(str(executable),'-NoProfile','-NonInteractive','-STA',
                '-File',str(Path(__file__).with_name('wechat_recent.ps1')),'-Mode',mode,*extra,
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                out,err=await asyncio.wait_for(proc.communicate(),timeout=20)
            except BaseException:
                if proc.returncode is None:proc.kill()
                await proc.communicate()
                raise
            try:result=json.loads(out.decode('utf-8-sig').strip())
            except (ValueError,UnicodeError):
                raise RuntimeError('微信最近使用入口识别失败：'+err.decode('utf-8',errors='replace')[-600:])
            failed=bool(proc.returncode)
        if failed or not result.get('ok'):
            if not mode.startswith('Cached'):LOG.error('微信入口识别失败：阶段=%s；诊断=%s',mode,json.dumps(result.get('diagnostics',{}),ensure_ascii=False))
            raise RuntimeError(result.get('message','微信最近使用入口操作失败'))
        if result.get("cache"):_save_position("entry",result["cache"])
        return result

_native_probe_task = None


async def _native_ui(mode,label=None,cache=None):
    global _native_probe_task
    if mode not in ('Snapshot','Scan','Click','CachedClick'):
        return await _native_ui_request(mode,label,cache)
    if _native_probe_task is not None and not _native_probe_task.done():
        raise RuntimeError('上次微信原生控件扫描仍在收尾，暂不重复注入')
    task=asyncio.create_task(_native_ui_request(mode,label,cache),name='wechat-native-probe')
    _native_probe_task=task
    task.add_done_callback(lambda done:done.exception() if not done.cancelled() else None)
    try:
        return await asyncio.wait_for(asyncio.shield(task),timeout=25)
    except TimeoutError:
        raise RuntimeError('微信控件扫描超时，保留原生会话等待收尾，未取消在途扫描') from None
    finally:
        if task.done() and _native_probe_task is task:_native_probe_task=None


async def _native_ui_request(mode,label=None,cache=None):
    """Reuse one native session; run blocking Win32/Frida calls off the GUI thread."""
    from . import wechat_native_launch as native
    if cache is None and mode in ('Snapshot','Scan','Click'):
        cache=positions.load().get('native')
    result=await asyncio.to_thread(native.run,mode,label,cache)
    if mode in ('Scan','Snapshot'):_save_position('native',result)
    elif result.get('snapshot'):_save_position('native',result['snapshot'])
    if mode in ('Click','CachedClick'):LOG.info('微信控件导航：%s，位置=%s',label,result['control']['screenCenter'])
    elif mode=='Close':LOG.info('微信旧游戏窗口已确认关闭')
    return result


async def close_native():
    from .wechat_native_launch import close
    if _native_probe_task is not None and not _native_probe_task.done():
        await asyncio.shield(_native_probe_task)
    await asyncio.to_thread(close)


async def _cached_prepare(cached):
    entry=cached.get('entry')
    if entry:
        try:return await _recent_ui('CachedPrepare',entry_cache=entry)
        except Exception as exc:LOG.debug('缓存游戏入口需更新：%s',exc)
    # Persisted native coordinates describe a past page, never current visibility.
    return None


async def _wait_recent():
    # Wait and validate in one warm worker request, returning the located card.
    return await _recent_ui('WaitPrepare')


async def _click_native_control(snapshot,label):
    # Re-read current visible controls immediately before input. The persistent
    # Frida session reuses its root; only layout metadata is taken from cache.
    return await _native_ui('Click',label,cache=snapshot)


async def _prepare_after_navigation(label):
    if label=='发现':
        # Discover is intermediate: open its native cell before waiting for cards.
        snapshot=await _native_ui('Snapshot')
        if any(c.get('label')=='小程序' for c in snapshot.get('controls',[])):
            await _click_native_control(snapshot,'小程序')
        else:
            prepared=await _recent_ui('Probe')
            if prepared.get('found'):return prepared
            await _recent_ui('Navigate')
    return await _wait_recent()


async def _prepare_native_entry(*,force_scan=False):
    if not force_scan:
        cached=positions.load()
        if cached.get('entry') or cached.get('native'):
            prepared=await _cached_prepare(cached)
            if prepared:
                LOG.info('微信入口预检查通过：已使用缓存位置')
                return prepared
    # An already-open page needs no native navigation or version-dependent scan.
    prepared=await _recent_ui('Probe')
    if prepared.get('found'):
        return prepared
    snapshot=await _native_ui('Snapshot')
    labels={c.get('label') for c in snapshot.get('controls',[])}
    if '小程序' in labels:
        await _click_native_control(snapshot,'小程序')
        return await _prepare_after_navigation('小程序')
    elif '发现' in labels:
        await _click_native_control(snapshot,'发现')
        return await _prepare_after_navigation('发现')
    else:
        raise RuntimeError('Frida未找到微信小程序或发现入口；未关闭游戏')


async def prepare_wechat_game(*,runner=None):
    started=time.monotonic()
    if runner:result=await runner('Prepare')
    else:result=await _prepare_native_entry()
    LOG.info('微信重开预检查通过：Frida原生控件及最近使用文本入口；耗时=%.2f秒',time.monotonic()-started)
    return result


async def prepare_wechat_start(before_open=None):
    """Prepare native navigation and game hooks concurrently, before the launch click."""
    if before_open is None:return await prepare_wechat_game()
    jobs=[asyncio.create_task(prepare_wechat_game()),asyncio.create_task(before_open())]
    try:
        prepared,_=await asyncio.gather(*jobs)
        return prepared
    except BaseException:
        for job in jobs:
            if not job.done():job.cancel()
        await asyncio.gather(*jobs,return_exceptions=True)
        raise


async def reopen_wechat_game(*,runner=None,before_open=None,prepared=None):
    if runner:
        await runner('WaitClosed')
    else:
        if prepared is None:prepared=await _prepare_native_entry()
        await _native_ui('Close')
    if before_open:await before_open()
    if runner:
        await runner('Open')
    else:
        await open_wechat_game(prepared=prepared)
    LOG.info('已点击微信最近使用中的普通版遗弃之地，等待大厅确认')


async def _wait_game_window():
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if (await _native_ui('Status'))['windows']:return True
        await asyncio.sleep(.5)
    return False


async def open_wechat_game(*,prepared=None):
    cached=positions.load()
    if prepared is None:prepared=await _prepare_native_entry()
    if (await _native_ui('Status'))['windows']:
        raise RuntimeError('游戏窗口已经存在，停止重复打开')
    try:
        target=(prepared or {}).get('cache') or cached.get('entry')
        if target:
            await _recent_ui('CachedOpen',entry_cache=target)
            LOG.info('已使用缓存位置打开游戏，等待窗口确认')
        else:
            await _recent_ui('EntryOpen')
        if await _wait_game_window():return
        raise RuntimeError('15秒内未确认游戏窗口')
    except Exception as exc:
        # A lost acknowledgement or a late window must never cause a second launch.
        if (await _native_ui('Status'))['windows']:return
        LOG.warning('缓存或首次打开游戏未确认：%s；使用新扫描位置重试',exc)
    await _prepare_native_entry(force_scan=True)
    if (await _native_ui('Status'))['windows']:return
    await _recent_ui('EntryOpen')
    if await _wait_game_window():return
    raise RuntimeError('重新扫描位置后仍未确认游戏窗口，已结束本轮两次尝试')
