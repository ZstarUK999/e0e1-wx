import asyncio
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from package.plugin_manager.store import PluginConfigStore, validate_config
from package.plugin_manager.polling_controls import DEFAULTS
from package.plugin_manager.window import PluginWindow
from package.plugin_manager.reconnect import WechatReconnect
from package.plugin_manager.auction import AuctionFeature
from test_plugin_runtime import make_controller, ready


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_switches_persist_and_validate(app, tmp_path):
    store = PluginConfigStore(tmp_path/'config.json')
    window = PluginWindow(store)
    try:
        for page, key in [('daily','automation_overlay'), ('global','blank_recovery'),
                          ('legion','legion_poll'), ('desire','desire_poll'), ('debug','memory_poll')]:
            box = getattr(window.pages[page], key)
            box.setChecked(not DEFAULTS[key])
            assert store.snapshot()['ui'][key] is (not DEFAULTS[key])
            assert PluginConfigStore(store.path).snapshot()['ui'][key] is (not DEFAULTS[key])
        raw = store.snapshot()
        for key in DEFAULTS:raw['ui'].pop(key)
        assert all(validate_config(raw)['ui'][key] == value for key,value in DEFAULTS.items())
        raw['ui']['memory_poll'] = 1
        with pytest.raises(ValueError):validate_config(raw)
        panel = window.pages['bloodmoon']
        panel.sub_switches['attack'].setChecked(True)
        assert store.snapshot()['bloodmoon']['attack']['enabled']
        assert not store.snapshot()['bloodmoon']['speed_up']['enabled']
    finally:
        window.deleteLater()


def test_reconnect_off_is_quiet_and_failed_unhook_retries():
    async def run():
        calls, fail = [], [False]
        async def status(on):
            calls.append(on)
            if fail[0]:raise TimeoutError()
            return {'kicked':False}
        reconnect = WechatReconnect(SimpleNamespace(wechat_reconnect_status=status))
        for _ in range(3):await reconnect.poll({'wechat_reconnect':False})
        assert calls == []
        await reconnect.poll({'wechat_reconnect':True})
        fail[0] = True
        with pytest.raises(TimeoutError):await reconnect.poll({'wechat_reconnect':False})
        fail[0] = False
        await reconnect.poll({'wechat_reconnect':False})
        await reconnect.poll({'wechat_reconnect':False})
        assert calls == [True, False, False]
    asyncio.run(run())


def test_disabled_auction_never_injects_and_stop_retries(app, tmp_path):
    async def run():
        from package.plugin_manager.auction import AuctionPanel
        store = PluginConfigStore(tmp_path/'auction.json')
        panel = AuctionPanel(store)
        calls, fail = [], [False]
        async def call(op, args):
            calls.append(op)
            if fail[0]:raise TimeoutError()
            return {}
        feature = AuctionFeature(SimpleNamespace(auction_call=call), SimpleNamespace(installed='s',closing=False), panel)
        await feature.poll();await feature.poll()
        assert not calls and not panel.timer.isActive()
        store.set_ui_flag('auction_poll',True)
        await feature.poll()
        assert calls == ['status']
        store.set_ui_flag('auction_poll',False)
        fail[0] = True
        await feature.poll()
        fail[0] = False
        await feature.poll();await feature.poll()
        assert calls == ['status','stop','stop']
        assert not panel.timer.isActive()
        panel.deleteLater()
    asyncio.run(run())


def test_overlay_off_sends_one_cleanup_and_controls_bypass_busy(app, tmp_path):
    async def run():
        controller, service, transport, window = make_controller(tmp_path)
        try:
            await ready(controller, service)
            calls=[]
            async def overlay(payload):calls.append(payload);return {}
            transport.automation_overlay=overlay
            await controller._sync_automation_overlay()
            assert calls == []
            window.store.set_ui_flag('automation_overlay',True)
            controller._next_overlay_sync=0
            await controller._sync_automation_overlay()
            window.store.set_ui_flag('automation_overlay',False)
            pending = asyncio.get_running_loop().create_future()
            controller.automation.operation = pending
            await controller._sync_optional_controls()
            assert not pending.done(), 'switch cleanup must not cancel or await the daily operation'
            pending.set_result(None)
            assert calls[-1]['active'] is False
            count=len(calls)
            controller._next_overlay_sync=0
            await controller._sync_optional_controls()
            assert len(calls)==count
            assert not controller.legion.scanner.control_enabled
            assert not controller.legion.scanner.timer.isActive()
            window.store.set_ui_flag('legion_scan_enabled',True)
            assert controller.legion.scanner.control_enabled
            window.store.set_ui_flag('legion_scan_enabled',False)
            assert not controller.legion.scanner.timer.isActive()
        finally:
            if controller.automation.operation and not controller.automation.operation.done():
                controller.automation.operation.set_result(None)
            await controller.shutdown();window.close()
    asyncio.run(run())


def test_optional_reads_only_run_when_their_switch_is_on(app, tmp_path):
    async def run():
        controller, service, transport, window = make_controller(tmp_path)
        counts = dict(legion=0, memory=0, desire=0)
        async def legion(*args):counts['legion']+=1;return None
        async def memory(*args):counts['memory']+=1
        async def stats():counts['desire']+=1;return {}
        transport.legion_read=legion
        controller.memory_monitor.sample=memory
        controller.desire.refresh_stats=stats
        try:
            await ready(controller, service)
            await controller.poll()
            assert counts == dict(legion=0, memory=0, desire=0)
            for key in ('legion_poll','memory_poll','desire_poll'):window.store.set_ui_flag(key,True)
            await controller.poll()
            assert all(value>0 for value in counts.values())
            for key in ('legion_poll','memory_poll','desire_poll'):window.store.set_ui_flag(key,False)
            before=dict(counts)
            controller.legion.next_poll=0
            controller.desire._stats_loaded=False
            await controller.poll()
            assert counts == before
        finally:
            await controller.shutdown();window.close()
    asyncio.run(run())
