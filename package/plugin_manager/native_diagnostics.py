"""Synchronous breadcrumbs alongside faulthandler's native crash stack."""
import os
import threading
from datetime import datetime

_stream = None


def set_stream(stream):
    global _stream
    _stream = stream


def checkpoint(message):
    stream = _stream
    if stream is None:
        return
    try:
        line = f'{datetime.now().isoformat(timespec="milliseconds")} pid={os.getpid()} thread={threading.get_ident()} {message}\n'
        # Bypass the async logging queue and Python buffering, so the last UI
        # boundary is available even if the next native call crashes the process.
        os.write(stream.fileno(), line.encode('utf-8', errors='replace'))
    except (OSError, ValueError):
        pass
