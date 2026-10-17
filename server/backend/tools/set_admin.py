"""设置或改管理员密码：库里已有管理员时，环境变量是改不动的，用这个。

用法::

    python tools/set_admin.py admin 新密码
"""

from __future__ import annotations

import sys
from pathlib import Path

# 以脚本方式运行时 cwd 不一定是 backend 根目录，自己把 app 包挂进去
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.models import Admin  # noqa: E402
from app.db.session import init_db, session_scope
from app.domain.accounts import hash_password


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    username, password = sys.argv[1], sys.argv[2]
    if len(password) < 6:
        print("[error] 密码至少 6 位")
        return 1

    init_db()
    with session_scope() as session:
        admin = session.query(Admin).filter(Admin.username == username).one_or_none()
        if admin is None:
            session.add(Admin(username=username, password_hash=hash_password(password)))
            print(f"[info] 已创建管理员：{username}")
        else:
            admin.password_hash = hash_password(password)
            print(f"[info] 已更新密码：{username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
