"""Bounded daemon workers for local I/O; never execute game actions here.

qasync's default QThreadExecutor joins all active workers when closing its loop.
Cancelled HTTP futures cannot interrupt blocking I/O, so that join can keep a
closed plugin alive. These Python workers finish normally while the app runs,
but cannot hold the process open after its game-operation shutdown has finished.
"""
from concurrent.futures import Executor, Future
import queue
import threading

class BackgroundExecutor(Executor):
    def __init__(self, max_workers=4):
        self._queue=queue.Queue()
        self._closed=False
        self._lock=threading.Lock()
        self._workers=[]
        for index in range(max_workers):
            worker=threading.Thread(target=self._work,name=f'plugin-background-{index}',daemon=True)
            worker.start();self._workers.append(worker)

    def submit(self, function, /, *args, **kwargs):
        with self._lock:
            if self._closed:raise RuntimeError('后台执行器已关闭')
            future=Future()
            self._queue.put((future,function,args,kwargs))
            return future

    def _work(self):
        while True:
            item=self._queue.get()
            if item is None:return
            future,function,args,kwargs=item
            if future.set_running_or_notify_cancel():
                try:result=function(*args,**kwargs)
                except BaseException as exc:future.set_exception(exc)
                else:future.set_result(result)
            # Release the last report/result/closure while waiting for new work.
            item=future=function=args=kwargs=None
            if 'result' in locals():del result

    def shutdown(self, wait=True, *, cancel_futures=True):
        with self._lock:
            if self._closed:return
            self._closed=True
            while True:
                try:item=self._queue.get_nowait()
                except queue.Empty:break
                if item is not None:item[0].cancel()
            for _ in self._workers:self._queue.put(None)
        # Deliberately do not join blocking local I/O during Qt loop teardown.
