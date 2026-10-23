"""游戏重启后的会话级任务标记；不保存旧命令、库存或执行进度。"""
from __future__ import annotations

import time


class RestartResume:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.observed = set()
        self.observed_at = 0
        self.observed_session = None
        self.pending = set()
        self.source_session = None
        self.launched = False

    def observe(self, tasks, session, *, healthy):
        if tasks and session:
            self.observed = set(tasks)
            self.observed_at = self.clock()
            self.observed_session = session
        elif healthy:
            self.observed.clear()

    def arm(self):
        if self.pending and (not self.launched or self.observed_session == self.source_session):
            return
        if self.observed and self.clock()-self.observed_at <= 120:
            self.pending.update(self.observed)
            self.source_session = self.observed_session
            self.launched = False

    def cancel(self, *tasks):
        self.pending.difference_update(tasks)
        self.observed.difference_update(tasks)

    def next_task(self, session):
        if not self.launched or not session or session == self.source_session:
            return None
        return next((task for task in ('desire', 'pet_fodder', 'daily') if task in self.pending), None)

    def consumed(self, task):
        self.pending.discard(task)
