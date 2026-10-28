"""One prewarmed UIA helper for foreground navigation; no polling while idle."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import subprocess


class RecentUiWorker:
    def __init__(self):
        self.loop=asyncio.get_running_loop()
        self.process=None
        self.lock=asyncio.Lock()

    async def _stop(self):
        process=self.process;self.process=None
        if process is None:return
        if process.stdin is not None:process.stdin.close()
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(),timeout=1)
            except (Exception,asyncio.CancelledError):
                if process.returncode is None:
                    try:process.kill()
                    except ProcessLookupError:pass
                await process.wait()

    async def close(self):
        async with self.lock:await self._stop()

    async def _ready(self):
        if self.process is not None and self.process.returncode is None:return
        executable=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
        self.process=await asyncio.create_subprocess_exec(str(executable),'-NoProfile','-NonInteractive','-STA',
            '-File',str(Path(__file__).with_name('wechat_recent.ps1')),'-Worker',
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        line=await asyncio.wait_for(self.process.stdout.readline(),timeout=10)
        if not line or not json.loads(line.decode('utf-8-sig')).get('ready'):
            raise RuntimeError('微信控件辅助进程预热失败')

    async def request(self,mode,entry_cache_path=''):
        async with self.lock:
            try:
                await self._ready()
                message=json.dumps({'mode':mode,'entryCachePath':entry_cache_path},ensure_ascii=True)+'\n'
                self.process.stdin.write(message.encode('utf-8'))
                await self.process.stdin.drain()
                line=await asyncio.wait_for(self.process.stdout.readline(),timeout=20)
                if not line:raise RuntimeError('微信控件辅助进程已退出')
                return json.loads(line.decode('utf-8-sig'))
            except BaseException:
                await self._stop()
                raise


_worker=None


async def request(mode,entry_cache_path=''):
    global _worker
    loop=asyncio.get_running_loop()
    if _worker is None or _worker.loop is not loop:
        if _worker and _worker.process and _worker.process.returncode is None:
            try:_worker.process.kill()
            except ProcessLookupError:pass
        _worker=RecentUiWorker()
    return await _worker.request(mode,entry_cache_path)


async def close():
    global _worker
    worker=_worker;_worker=None
    if worker is not None:await worker.close()
