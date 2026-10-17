#!/usr/bin/env bash
# 删除 systemd 服务（不会删虚拟环境和 data/ 里的数据）
set -euo pipefail

SERVICE_NAME="e0e1-server"

if ! command -v systemctl >/dev/null 2>&1; then
  echo "这台机器没有 systemd，无需卸载" >&2
  exit 1
fi

if [[ ! -f "/etc/systemd/system/${SERVICE_NAME}.service" ]]; then
  echo "服务未安装：${SERVICE_NAME}"
  exit 0
fi

read -r -p "确认删除服务 ${SERVICE_NAME}？(y/N) " answer
[[ "$answer" =~ ^[Yy]$ ]] || { echo "已取消"; exit 0; }

sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true
sudo rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload
sudo systemctl reset-failed "$SERVICE_NAME" 2>/dev/null || true

echo "已删除服务 ${SERVICE_NAME}。虚拟环境与 data/ 保留，需要手动清理。"
