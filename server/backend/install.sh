#!/usr/bin/env bash
# 注册为 systemd 服务：建虚拟环境 → 装依赖 → 渲染 unit → 开机自启并立即启动
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
UNIT_SRC="${ROOT}/e0e1-server.service"
REQ="${ROOT}/requirements.txt"
VENV="${ROOT}/.venv"
PIP="${VENV}/bin/pip"
PY="${VENV}/bin/python"
SERVICE_NAME="e0e1-server"
USER_NAME="${SERVICE_USER:-$(id -un)}"

for file in "$UNIT_SRC" "$REQ"; do
  [[ -f "$file" ]] || { echo "缺少 $file" >&2; exit 1; }
done

command -v python3 >/dev/null 2>&1 || { echo "需要先安装 python3" >&2; exit 1; }

if [[ ! -d "$VENV" ]]; then
  echo "创建虚拟环境：$VENV"
  python3 -m venv "$VENV"
fi

echo "安装依赖"
"$PIP" install -r "$REQ"

if [[ ! -x "$PY" ]]; then
  echo "虚拟环境异常：$PY 不存在" >&2
  exit 1
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
sed -e "s|{current_path}|${ROOT}|g" -e "s|{user}|${USER_NAME}|g" "$UNIT_SRC" >"$TMP"

echo "安装服务：$SERVICE_NAME（运行用户 ${USER_NAME}）"
sudo cp "$TMP" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"

echo
echo "完成。常用命令："
echo "  ./restart.sh            重启"
echo "  ./stop.sh               停止"
echo "  ./start.sh              启动"
echo "  sudo journalctl -u ${SERVICE_NAME} -f    看日志"
echo "  sudo systemctl status ${SERVICE_NAME}    看状态"
