"""非阻塞本地文件日志；操作与错误落盘，循环查询不逐次记录。"""
from __future__ import annotations

import logging
import logging.handlers
import queue
import sys
from pathlib import Path


class BoundedQueueHandler(logging.handlers.QueueHandler):
    """Drop excess records rather than blocking Qt or growing memory without bound."""
    def __init__(self, records):
        super().__init__(records)
        self.dropped = 0

    def enqueue(self, record):
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            self.dropped += 1


class BoundedQueueListener(logging.handlers.QueueListener):
    def enqueue_sentinel(self):
        # Producers are detached before stop; make room without blocking the GUI.
        while True:
            try:
                self.queue.put_nowait(self._sentinel)
                return
            except queue.Full:
                try: self.queue.get_nowait(); self.queue.task_done()
                except queue.Empty: pass


class FileLogging:
    def __init__(self, path: Path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.logger=logging.getLogger('plugin_manager')
        self.original_level=self.logger.level
        self.logger.setLevel(logging.INFO)
        self.queue_handler=BoundedQueueHandler(queue.Queue(maxsize=4096))
        self.file_handler=logging.handlers.RotatingFileHandler(self.path,maxBytes=5*1024*1024,backupCount=3,encoding='utf-8')
        self.file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s',datefmt='%Y-%m-%d %H:%M:%S'))
        self.listener=BoundedQueueListener(self.queue_handler.queue,self.file_handler)
        self.logger.addHandler(self.queue_handler)
        self.memory_logger=logging.getLogger('plugin_manager.memory')
        self.memory_logger.propagate=False
        self.memory_logger.addHandler(self.queue_handler)
        self.listener.start()
        self.closed=False

    def close(self):
        if self.closed:return
        self.closed=True
        self.logger.removeHandler(self.queue_handler)
        self.memory_logger.removeHandler(self.queue_handler)
        self.listener.stop()
        if self.queue_handler.dropped:
            record=self.logger.makeRecord(self.logger.name,logging.WARNING,__file__,0,
                '日志写入积压，已丢弃 %d 条记录', (self.queue_handler.dropped,),None)
            self.file_handler.handle(record)
        self.file_handler.close()
        self.logger.setLevel(self.original_level)


def start_file_logging(path: Path) -> FileLogging:
    return FileLogging(path)


def configure_logging(path: Path | None = None) -> FileLogging | None:
    """配置控制台与插件日志文件；传 None 时只配置控制台。"""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    if getattr(sys, "frozen", False):
        # 打包后日志只落文件：--windowed 没有控制台，从命令行启动时也不该有残留输出
        root = logging.getLogger()
        for handler in list(root.handlers):
            if isinstance(handler, logging.StreamHandler):
                root.removeHandler(handler)
    return start_file_logging(path) if path is not None else None
