"""单进程双协议：uvicorn 管 HTTP 管理端，grpc.aio 管插件通道。

两者共享同一份 domain 层和数据库，所以一个进程就够。
"""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path

import grpc
import uvicorn

from .db.session import init_db
from .grpc.servicer import register
from .http import create_app
from .settings import settings


def _server_credentials() -> grpc.ServerCredentials:
    """mTLS：必须校验客户端证书。"""
    certs = settings.certs_dir
    ca = (certs / "ca.pem").read_bytes()
    server_cert = (certs / "server.pem").read_bytes()
    server_key = (certs / "server.key").read_bytes()
    return grpc.ssl_server_credentials(
        [(server_key, server_cert)],
        root_certificates=ca,
        require_client_auth=True,
    )


def _missing_certs() -> list[str]:
    certs = settings.certs_dir
    return [
        name
        for name in ("ca.pem", "server.pem", "server.key")
        if not (certs / name).is_file()
    ]


async def serve() -> None:
    missing = _missing_certs()
    if missing:
        raise SystemExit(
            f"缺少证书：{', '.join(missing)}；先跑 python tools/gen_certs.py 生成"
        )

    init_db()

    server = grpc.aio.server()
    register(server)
    server.add_secure_port(f"{settings.grpc_host}:{settings.grpc_port}", _server_credentials())
    await server.start()
    print(f"[info] gRPC 插件通道：{settings.grpc_host}:{settings.grpc_port}（mTLS）")

    config = uvicorn.Config(
        create_app(),
        host=settings.http_host,
        port=settings.http_port,
        log_level="info",
    )
    uvicorn_server = uvicorn.Server(config)
    print(f"[info] HTTP 管理端：http://{settings.http_host}:{settings.http_port}")

    stop = asyncio.Event()

    def _stop(*_: object) -> None:
        stop.set()

    for name in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(name, _stop)
        except NotImplementedError:
            pass

    http_task = asyncio.create_task(uvicorn_server.serve())
    await stop.wait()
    http_task.cancel()
    uvicorn_server.shutdown = True  # type: ignore[assignment]
    await server.stop(grace=3)
    print("[info] 服务已停止")


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
