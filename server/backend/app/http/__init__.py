"""FastAPI 管理端：给网页前端和插件下载用。"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..settings import settings
from ..domain.packages import cleanup_expired_packages
from .routers import auth, certificates, logs, players, releases


async def _cleanup_packages() -> None:
    try:
        await asyncio.to_thread(cleanup_expired_packages)
    except Exception:
        logging.getLogger(__name__).exception("玩家包定时清理失败，将在下一轮重试")


async def _package_cleanup_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        await _cleanup_packages()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _cleanup_packages()
    task = asyncio.create_task(_package_cleanup_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    app = FastAPI(title="e0e1 插件服务器", docs_url="/api/docs", lifespan=lifespan)

    @app.middleware("http")
    async def no_cache_static(request, call_next):
        """前端文件不缓存：改了 app.js 刷新就能生效，不用强制刷新。"""
        response = await call_next(request)
        if not request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(auth.router)
    app.include_router(certificates.router)
    app.include_router(players.router)
    app.include_router(releases.router)
    app.include_router(logs.router)

    if settings.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(settings.web_dir), html=True), name="web")
    return app
