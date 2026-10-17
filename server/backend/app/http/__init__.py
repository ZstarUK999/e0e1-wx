"""FastAPI 管理端：给网页前端和插件下载用。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..settings import settings
from .routers import auth, logs, players, releases


def create_app() -> FastAPI:
    app = FastAPI(title="e0e1 插件服务器", docs_url="/api/docs")

    @app.middleware("http")
    async def no_cache_static(request, call_next):
        """前端文件不缓存：改了 app.js 刷新就能生效，不用强制刷新。"""
        response = await call_next(request)
        if not request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(auth.router)
    app.include_router(players.router)
    app.include_router(releases.router)
    app.include_router(logs.router)

    if settings.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(settings.web_dir), html=True), name="web")
    return app
