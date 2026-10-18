"""按己方角色、墓藏类型保存已确认的连续战败次数。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .scheduler import RetryableTaskError


class TombRaidHistory:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _read(self):
        if not self.path.exists():
            return {"version": 1, "players": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if value.get("version") != 1 or not isinstance(value.get("players"), dict):
                raise ValueError("记录格式无效")
            return value
        except (OSError, ValueError, AttributeError) as exc:
            raise RetryableTaskError(f"墓藏战败记录读取失败，暂停盗掠以免重复挑战：{exc}") from exc

    def load(self, owner: str, kind: str) -> dict[int, int]:
        try:
            rows = self._read()["players"].get(owner, {}).get(kind, {})
            if not isinstance(rows, dict):
                raise ValueError("战败次数不是字典")
            if any(not str(key).isdigit() or int(key) <= 0 or type(value) is not int or not 1 <= value <= 3
                   for key, value in rows.items()):
                raise ValueError("战败玩家或次数无效")
            return {int(key): value for key, value in rows.items()}
        except (ValueError, AttributeError) as exc:
            raise RetryableTaskError(f"墓藏战败记录无效，暂停盗掠：{exc}") from exc

    def save(self, owner: str, kind: str, losses: dict[int, int]):
        value = self._read()
        value["players"].setdefault(owner, {})[kind] = {str(key): count for key, count in losses.items() if count}
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix="tomb-history-", suffix=".tmp", dir=self.path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(value, file, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            raise RetryableTaskError(f"墓藏战败记录保存失败，本轮停止继续挑战：{exc}") from exc
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
