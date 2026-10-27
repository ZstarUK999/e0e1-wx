import asyncio
import logging
import queue
from package.plugin_manager.logging_setup import BoundedQueueHandler, BoundedQueueListener
from package.plugin_manager.transport import PluginTransport
from package.plugin_manager.runtime_memory import process_memory
from tools.test_plugin_runtime import FakeCdp


def test_log_storm_has_bounded_storage():
    q=queue.Queue(maxsize=32);handler=BoundedQueueHandler(q)
    record=logging.LogRecord('test',logging.INFO,__file__,1,'hello',(),None)
    for _ in range(100000):handler.handle(record)
    assert q.qsize()==32
    assert handler.dropped==99968


def test_full_logging_queue_can_accept_shutdown_sentinel():
    q=queue.Queue(maxsize=1);q.put('record')
    listener=BoundedQueueListener(q)
    listener.enqueue_sentinel()
    assert q.qsize()==1 and q.get_nowait() is listener._sentinel


def test_reconnect_poll_uses_small_expression_and_reinstalls_missing_hook():
    async def run():
        t=PluginTransport(FakeCdp());t.connected=True;t.context_id=7
        calls=[];present=[True]
        async def evaluate(expression,*args,**kwargs):
            calls.append(expression)
            if 'async function configureWechatReconnect' in expression:
                present[0]=True
                return {'kicked':False}
            return {'kicked':False} if present[0] else None
        t._evaluate=evaluate
        for _ in range(1000):assert await t.wechat_reconnect_status(True)=={'kicked':False}
        assert all(len(s)<300 for s in calls)
        present[0]=False
        await t.wechat_reconnect_status(True)
        assert 'async function configureWechatReconnect' in calls[-1]
        await t.wechat_reconnect_status(False)
        assert 'configureWechatReconnect(globalThis,false)' in calls[-1]
    asyncio.run(run())


def test_memory_snapshot_contains_python_process():
    result=process_memory()
    assert result['python']['rssBytes']>0
    assert result['python']['threads']>=1
