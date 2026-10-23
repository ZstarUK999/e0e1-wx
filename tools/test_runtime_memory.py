import asyncio
import logging
import io
import pytest
from package.plugin_manager.runtime_memory import RuntimeMemoryMonitor


@pytest.fixture
def memory_caplog(caplog):
    logger=logging.getLogger('plugin_manager.memory')
    logger.addHandler(caplog.handler)
    try:yield caplog
    finally:logger.removeHandler(caplog.handler)


def test_memory_samples_are_throttled_and_keep_only_latest(memory_caplog):
    caplog=memory_caplog
    class Transport:
        connected=True
        calls=0
        async def memory_snapshot(self):
            self.calls+=1
            return {'heap':{'usedSize':100*self.calls}}
    async def run():
        clock=[1];t=Transport();m=RuntimeMemoryMonitor(clock=lambda:clock[0],processes=lambda:{'privateBytes':50})
        await m.sample(t,'one');await m.sample(t,'one');assert t.calls==1
        clock[0]=61;await m.sample(t,'one');assert t.calls==1
        clock[0]=300;await m.sample(t,'one');assert t.calls==1
        clock[0]=301;await m.sample(t,'one');assert t.calls==2
        assert m.last['js']['heap']['usedSize']==200
        await m.sample(t,'two');assert t.calls==3
        t.connected=False;clock[0]=200;await m.sample(t,'two');assert t.calls==3
    with caplog.at_level(logging.INFO,logger='plugin_manager'):asyncio.run(run())
    assert caplog.text.count('运行内存诊断')==3


def test_memory_sample_timeout_does_not_interrupt_game_operations(memory_caplog):
    caplog=memory_caplog
    class Transport:
        connected=True
        async def memory_snapshot(self):raise TimeoutError()
    async def run():
        m=RuntimeMemoryMonitor(processes=lambda:{'privateBytes':123})
        await m.sample(Transport(),'one')
        assert m.last['jsUnavailable']=='TimeoutError' and m.last['native']['privateBytes']==123
    with caplog.at_level(logging.INFO,logger='plugin_manager'):asyncio.run(run())
    assert 'TimeoutError' in caplog.text


def test_memory_is_written_to_file_without_console_output(tmp_path):
    from package.plugin_manager.logging_setup import start_file_logging
    console=io.StringIO()
    handler=logging.StreamHandler(console)
    parent=logging.getLogger('plugin_manager')
    parent.addHandler(handler)
    file=tmp_path/'plugin.log'
    session=start_file_logging(file)
    try:
        logging.getLogger('plugin_manager.memory').info('运行内存诊断：file-only')
        parent.info('普通操作日志')
    finally:
        session.close()
        parent.removeHandler(handler)
    assert '运行内存诊断：file-only' in file.read_text(encoding='utf-8')
    assert '运行内存诊断' not in console.getvalue()
    assert '普通操作日志' in console.getvalue()
    assert session.queue_handler not in logging.getLogger('plugin_manager.memory').handlers


def test_unsupported_heap_api_is_not_retried_every_sample_until_new_context():
    from package.plugin_manager.transport import PluginTransport
    from tools.test_plugin_runtime import FakeCdp
    class Cdp(FakeCdp):
        calls=0
        async def send(self,*args,**kwargs):
            self.calls+=1
            raise RuntimeError('method not found')
    async def run():
        c=Cdp();t=PluginTransport(cdp=c);t.context_id=7
        async def evaluate(*args,**kwargs):return {}
        t._evaluate=evaluate
        first=await t.memory_snapshot();second=await t.memory_snapshot()
        assert first['heapUnavailable']==second['heapUnavailable']=='unsupported' and c.calls==1
        t.invalidate();t.context_id=7
        await t.memory_snapshot();assert c.calls==2
    asyncio.run(run())
