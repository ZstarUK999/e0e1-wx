"""非阻塞本地文件日志；操作与错误落盘，循环查询不逐次记录。"""
from __future__ import annotations

import logging
import logging.handlers
import queue
from pathlib import Path


class FileLogging:
    def __init__(self, path: Path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.logger=logging.getLogger('plugin_manager')
        self.original_level=self.logger.level
        self.logger.setLevel(logging.INFO)
        self.queue_handler=logging.handlers.QueueHandler(queue.Queue())
        self.file_handler=logging.handlers.RotatingFileHandler(self.path,maxBytes=5*1024*1024,backupCount=3,encoding='utf-8')
        self.file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s',datefmt='%Y-%m-%d %H:%M:%S'))
        self.listener=logging.handlers.QueueListener(self.queue_handler.queue,self.file_handler)
        self.logger.addHandler(self.queue_handler)
        self.listener.start()
        self.closed=False

    def close(self):
        if self.closed:return
        self.closed=True
        self.logger.removeHandler(self.queue_handler)
        self.listener.stop()
        self.file_handler.close()
        self.logger.setLevel(self.original_level)


def start_file_logging(path: Path) -> FileLogging:
    return FileLogging(path)


def configure_logging(path: Path | None = None) -> FileLogging | None:
    """配置控制台与插件日志文件；传 None 时只配置控制台。"""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    return start_file_logging(path) if path is not None else None
