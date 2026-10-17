"""运行服务的共享状态：会话、调度与功能插件都读写这一份，避免互相引用。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RuntimeState:
    closing: bool = False              # 正在关闭，不再发起新操作
    stop_operation: bool = False       # 请求当前任务在安全步骤收尾
    blocked: str = ''                  # 会话被暂停的原因，非空即禁止自动任务
    blocked_session: str | None = None # 被暂停时注入的驻留脚本 id，换会话才解除
    installed: str | None = None       # 当前会话注入的驻留脚本 id
    configured: dict | None = None     # 已下发到页面的配置快照
    epoch: tuple | None = None         # (cdp_port, miniapp_epoch)，变了就是新会话
