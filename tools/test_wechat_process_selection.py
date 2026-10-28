import asyncio
from types import SimpleNamespace
import pytest
from package.plugin_manager.wechat_native_launch import select_wechat_pid


def proc(pid,args=None,name='Weixin.exe'):
    return SimpleNamespace(pid=pid,info={'name':name,'cmdline':args})


def test_selects_window_owner_among_multiple_bootstrap_processes():
    assert select_wechat_pid([proc(1,[]),proc(2,[]),proc(3,['--type=wxocr'])],{2})==2


def test_window_owner_can_be_resolved_when_command_line_is_inaccessible():
    assert select_wechat_pid([proc(1,None),proc(2,[])],{1})==1


def test_both_helper_argument_formats_are_excluded():
    rows=[proc(1,['Weixin.exe']),proc(2,['Weixin.exe','--type','wxutility']),
          proc(3,['Weixin.exe','--type=wxocr'])]
    assert select_wechat_pid(rows,set())==1


def test_multiple_real_window_owners_are_not_guessed():
    with pytest.raises(RuntimeError,match='多个微信主窗口'):
        select_wechat_pid([proc(1,[]),proc(2,[])],{1,2})


def test_absent_wechat_has_specific_waiting_diagnostic():
    with pytest.raises(RuntimeError,match='尚未运行'):
        select_wechat_pid([proc(3,[],name='WXWork.exe')],{3})


def test_helpers_only_have_waiting_diagnostic():
    with pytest.raises(RuntimeError,match='仅检测到辅助进程'):
        select_wechat_pid([proc(2,['--type=wxutility'])],set())


def test_ambiguous_startup_candidates_are_reported():
    with pytest.raises(RuntimeError,match='候选进程：1,2'):
        select_wechat_pid([proc(1,[]),proc(2,[])],set())


def test_startup_failure_is_retried_after_cooldown(monkeypatch):
    from package.plugin_manager.runtime import PluginRuntime
    from package.plugin_manager import runtime,startup_launch
    async def run():
        now=[1];calls=[];labels=[]
        async def start(*args,**kwargs):
            calls.append(now[0])
            if len(calls)==1:raise RuntimeError('微信主进程尚未运行')
            return False
        monkeypatch.setattr(startup_launch,'ensure_game_started',start)
        monkeypatch.setattr(runtime,'time',SimpleNamespace(monotonic=lambda:now[0]))
        controller=SimpleNamespace(_startup_checked=False,platform_name='微信',
            window=SimpleNamespace(action_label=SimpleNamespace(setText=labels.append)),
            state=SimpleNamespace(closing=False),session=SimpleNamespace(prepare_reopen=None))
        assert not await PluginRuntime._ensure_startup(controller)
        assert not controller._startup_checked
        now[0]=20
        assert not await PluginRuntime._ensure_startup(controller)
        assert calls==[1]
        now[0]=21
        assert await PluginRuntime._ensure_startup(controller)
        assert controller._startup_checked and calls==[1,21]
        assert await PluginRuntime._ensure_startup(controller)
        assert calls==[1,21]
        assert any('20秒后重试' in label for label in labels)
    asyncio.run(run())
