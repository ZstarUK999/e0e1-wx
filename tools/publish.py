"""一键发布：构建 → 上传 → 发布。

用法::

    python tools/publish.py 1.2.0 "修了斗法的刷新逻辑"
    python tools/publish.py 1.2.0 --skip-build      # 复用现有产物，只上传发布
    python tools/publish.py 1.2.0 --mandatory       # 设为强制更新

管理员密码从环境变量 E0E1_PUBLISH_PASSWORD 取，没设就交互式输入。
"""

from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
APP_NAME = "e0e1-wx-plugins"


def build(version: str, target: str, python: str) -> None:
    """跑打包脚本产出通用上传包。"""
    command = [
        python,
        str(ROOT / "tools" / "build_exe.py"),
        "--mode",
        "release",
        "--version",
        version,
        "--target",
        target,
        "--package",
    ]
    print(f"[1/3] 构建：{' '.join(command)}")
    result = subprocess.run(command, cwd=str(ROOT))
    if result.returncode != 0:
        raise SystemExit(f"构建失败，退出码 {result.returncode}")


def login(base: str, username: str, password: str) -> str:
    response = httpx.post(
        f"{base}/api/auth/login",
        json={"username": username, "password": password},
        timeout=15,
    )
    if response.status_code != 200:
        raise SystemExit(f"登录失败（{response.status_code}）：{response.text}")
    return response.json()["token"]


def upload(base: str, token: str, archive: Path, version: str, changelog: str, mandatory: bool) -> dict:
    print(f"[2/3] 上传：{archive.name}（{archive.stat().st_size / 1024 / 1024:.1f} MB）")
    with archive.open("rb") as handle:
        response = httpx.post(
            f"{base}/api/releases/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"archive": (archive.name, handle, "application/zip")},
            data={
                "version": version,
                "changelog": changelog,
                "mandatory": "true" if mandatory else "false",
            },
            timeout=300,
        )
    if response.status_code not in (200, 201):
        raise SystemExit(f"上传失败（{response.status_code}）：{response.text}")
    return response.json()


def publish(base: str, token: str, version: str) -> None:
    print(f"[3/3] 发布：{version}")
    response = httpx.post(
        f"{base}/api/releases/{version}/publish",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if response.status_code != 200:
        raise SystemExit(f"发布失败（{response.status_code}）：{response.text}")


def _env(name: str, default: str = "") -> str:
    """读配置；bat 里设的环境变量优先。"""
    return os.environ.get(f"PUBLISH_{name}", default)


def _env_flag(name: str) -> bool:
    return _env(name, "0").strip().lower() in ("1", "true", "yes")


def main() -> int:
    # 默认值都从环境变量取，这样 publish.bat 把配置写在文件里即可，命令行只给版本号
    parser = argparse.ArgumentParser(description="构建并发布插件新版本")
    parser.add_argument("version", help="版本号，如 1.2.0")
    parser.add_argument("changelog", nargs="?", default=_env("CHANGELOG"), help="更新日志")
    parser.add_argument("--base", default=_env("BASE", "http://127.0.0.1:8000"), help="后台 HTTP 地址")
    parser.add_argument("--target", default=_env("TARGET", "127.0.0.1:8001"), help="后台 gRPC 地址")
    parser.add_argument("--username", default=_env("USERNAME", "admin"))
    parser.add_argument("--password", default=_env("PASSWORD"), help="不设就交互输入")
    parser.add_argument("--skip-build", action="store_true", default=_env_flag("SKIP_BUILD"))
    parser.add_argument("--mandatory", action="store_true", default=_env_flag("MANDATORY"))
    parser.add_argument("--no-publish", action="store_true", default=_env_flag("NO_PUBLISH"))
    args = parser.parse_args()

    archive = DIST_DIR / f"{APP_NAME}-{args.version}-upload.zip"
    if not args.skip_build:
        build(args.version, args.target, sys.executable)
    if not archive.is_file():
        raise SystemExit(f"找不到上传包：{archive}")

    password = args.password or os.environ.get("E0E1_PUBLISH_PASSWORD", "")
    if not password:
        password = getpass.getpass("管理员密码：")

    token = login(args.base, args.username, password)
    release = upload(args.base, token, archive, args.version, args.changelog, args.mandatory)
    print(f"      版本 {release['version']}，{release['file_count']} 个文件，"
          f"{release['total_size'] / 1024 / 1024:.1f} MB")
    if not args.no_publish:
        publish(args.base, token, args.version)
        print(f"\n{args.version} 已生效。玩家下次启动会自动下载更新。")
    else:
        print(f"\n已上传但未发布，去后台点「发布」才生效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
