import logging
from types import SimpleNamespace

from package.devtools.engine import DebugEngine
from package.devtools.worker import AsyncDevtoolsWorker
from package.devtools.service import DevtoolsService


def test_diagnostics_reach_plugin_log_without_overwriting_connection_state(caplog):
    engine = DebugEngine(SimpleNamespace(), SimpleNamespace())
    original = dict(engine.status)
    events = []
    worker = SimpleNamespace(emit=events.append)
    engine.on_status_change(lambda status: AsyncDevtoolsWorker.handle_bridge_status(worker, status))
    with caplog.at_level(logging.INFO, logger='plugin_manager'):
        engine._emit_hook_diagnostic({'event':'load-enter','pid':1234})
        engine._emit_hook_diagnostic({'event':'scene','pid':1234,'scene':999,'accepted':False,'level':'warning'})
        for event in events:
            DevtoolsService.handle_event(SimpleNamespace(), event)
    assert engine.status == original and 'hook_diagnostic' not in engine.status
    assert len(events) == 2
    assert 'load-enter' in caplog.text and '"accepted": false' in caplog.text
    assert caplog.records[-1].levelno == logging.WARNING


def test_frida_thread_diagnostics_are_marshaled_to_worker_loop():
    engine = DebugEngine(SimpleNamespace(), SimpleNamespace())
    scheduled, statuses = [], []
    engine._frida_loop = SimpleNamespace(is_closed=lambda:False,call_soon_threadsafe=scheduled.append)
    engine.on_status_change(statuses.append)
    engine._emit_hook_diagnostic({'event':'hook-ready'})
    assert not statuses and len(scheduled) == 1
    scheduled[0]()
    assert statuses[0]['hook_diagnostic']['event'] == 'hook-ready'


def test_native_callback_forwards_diagnostics_and_errors_but_keeps_noise_filtered(tmp_path,monkeypatch):
    from package.devtools import engine as module
    tools = tmp_path/'tools'
    (tools/'config/win').mkdir(parents=True)
    (tools/'config/win/addresses.25799.json').write_text('{}')
    (tools/'hook.js').write_text('const DEBUG_PORT = 9421; // @@CONFIG@@')
    handlers, statuses, noise = {}, [], []
    class Script:
        def on(self,name,callback):handlers[name]=callback
        def load(self):
            handlers['message']({'type':'send','payload':{'type':'e0e1-hook-diagnostic','event':'hook-ready','pid':999}},None)
            handlers['message']({'type':'send','payload':'ordinary noisy message'},None)
            handlers['message']({'type':'error','description':'hook install failed'},None)
    script=Script()
    session=SimpleNamespace(create_script=lambda source:script,on=lambda *args:None)
    frida=SimpleNamespace(get_local_device=lambda:SimpleNamespace(attach=lambda pid:session))
    monkeypatch.setattr(module,'tools_root',lambda:tools)
    monkeypatch.setattr(module.DebugEngine,'_load_frida',lambda self:frida)
    monkeypatch.setattr(module.DebugEngine,'_find_wmpf_pids_win',lambda self:([1234],25799))
    logger=SimpleNamespace(info=lambda *a:None,error=lambda *a:None,frida_debug=lambda *a:noise.append(a))
    instance=DebugEngine(SimpleNamespace(channel='wechat',debug_port=9421),logger)
    instance.on_status_change(statuses.append)
    instance._start_frida_sync()
    assert [s['hook_diagnostic']['event'] for s in statuses] == ['hook-ready','script-error']
    assert all(s['hook_diagnostic']['pid']==1234 for s in statuses)
    assert len(noise)==1 and 'ordinary noisy message' in noise[0]
