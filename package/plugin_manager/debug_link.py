"""调试链接的校验与打开：只允许本机 devtools 链接，交给 Chrome 打开。"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from PySide6.QtCore import QProcess

DEBUG_LINK_PATTERN = r"devtools://devtools/bundled/inspector\.html\?ws=127\.0\.0\.1:([0-9]{1,5})"


def valid_debug_link(link: str) -> bool:
    match = re.fullmatch(DEBUG_LINK_PATTERN, link)
    return bool(match and 1 <= int(match[1]) <= 65535)


def chrome_candidates() -> list[str]:
    candidates = [shutil.which("chrome"), shutil.which("chrome.exe")]
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"))
    return [candidate for candidate in candidates if candidate]


def open_chrome(link: str) -> bool:
    if not valid_debug_link(link):
        return False
    for candidate in chrome_candidates():
        if Path(candidate).is_file():
            success, _ = QProcess.startDetached(str(candidate), [link])
            return success
    return False
