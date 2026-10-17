"""服务器配置：全部可用 E0E1_ 前缀的环境变量覆盖。"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    # env_file 用绝对路径：服务化后工作目录不一定是 backend，相对路径会读不到 .env
    model_config = SettingsConfigDict(
        env_prefix="E0E1_", env_file=str(BACKEND_ROOT / ".env"), extra="ignore"
    )

    # HTTP 管理端与前端
    http_host: str = "127.0.0.1"
    http_port: int = 8000
    # gRPC 插件通道
    grpc_host: str = "127.0.0.1"
    grpc_port: int = 8001

    data_dir: Path = BACKEND_ROOT / "data"
    certs_dir: Path = BACKEND_ROOT / "certs"
    web_dir: Path = BACKEND_ROOT.parent / "web"

    database_url: str = ""
    license_key_path: Path = BACKEND_ROOT / "data" / "license_ed25519.key"

    admin_username: str = "admin"
    admin_password: str = "admin"
    jwt_secret: str = "change-me-in-production-please-use-env"
    jwt_expire_minutes: int = 720
    download_ticket_minutes: int = 15

    # 下载链接的对外地址；插件实际拉文件走这里，不一定等于 http_host
    public_base_url: str = "https://127.0.0.1:8000"

    def model_post_init(self, __context) -> None:
        if not self.database_url:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.database_url = f"sqlite:///{(self.data_dir / 'server.db').resolve().as_posix()}"


settings = Settings()
