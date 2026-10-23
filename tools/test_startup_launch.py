import asyncio
from types import SimpleNamespace

from package.plugin_manager.startup_launch import ensure_game_started, DouyinImageLauncher


def test_existing_game_is_never_opened_or_restarted():
    calls = []
    launcher = SimpleNamespace(game_windows=lambda: [object()],
        prepare=lambda: calls.append('prepare'), open_game=lambda: calls.append('open'))
    async def ready():
        calls.append('debug')
    result = asyncio.run(ensure_game_started('微信', before_open=ready,
        factory=lambda **kw: launcher))
    assert result is False
    assert calls == []


def test_missing_game_prepares_debug_before_opening():
    calls = []
    launcher = SimpleNamespace(game_windows=lambda: [],
        prepare=lambda: calls.append('prepare'), open_game=lambda: calls.append('open'))
    async def ready():
        calls.append('debug')
    asyncio.run(ensure_game_started('微信', before_open=ready,
        factory=lambda **kw: launcher))
    assert calls == ['prepare', 'debug', 'open']


def test_game_appearing_during_prepare_is_not_clicked_again():
    calls = []
    windows = []
    launcher = SimpleNamespace(game_windows=lambda: windows,
        prepare=lambda: windows.append(object()), open_game=lambda: calls.append('open'))
    asyncio.run(ensure_game_started('抖音', factory=lambda **kw: launcher))
    assert calls == []


def test_douyin_has_one_navigation_level_then_game_icon():
    assert DouyinImageLauncher.navigation == (('miniapps_active', 'miniapps_inactive', '小游戏入口'),)
    assert len(DouyinImageLauncher.template_names) == 3
