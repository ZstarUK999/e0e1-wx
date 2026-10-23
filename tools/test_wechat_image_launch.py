import asyncio
from types import SimpleNamespace

import pytest
from PIL import Image

from package.plugin_manager.blank_recovery import BlankScreenRecovery
from package.plugin_manager.wechat_image_launch import WechatImageLauncher, classify_blank, IMAGES


def test_blank_requires_nearly_uniform_client_area():
    assert classify_blank(Image.new('RGB', (300, 300), 'white')) == 'white'
    assert classify_blank(Image.new('RGB', (300, 300), 'black')) == 'black'
    assert classify_blank(Image.new('RGB', (300, 300), '#808080')) is None
    image = Image.new('RGB', (300, 300), 'white')
    image.paste(Image.new('RGB', (100, 100), 'green'), (0, 0))
    assert classify_blank(image) is None


def test_color_templates_do_not_confuse_active_and_inactive():
    import pyautogui
    for prefix in ('sidebar', 'miniapps'):
        with Image.open(IMAGES / (prefix + '_active.png')) as active, Image.open(IMAGES / (prefix + '_inactive.png')) as inactive:
            canvas = Image.new('RGB', (200, 100), '#ededed')
            canvas.paste(inactive, (20, 20))
            with pytest.raises(pyautogui.ImageNotFoundException):
                pyautogui.locate(active, canvas, confidence=.94, grayscale=False)


@pytest.mark.parametrize('state',['active','inactive'])
def test_sidebar_matches_red_dot_and_does_not_confuse_selection(state):
    import pyautogui
    with Image.open(IMAGES / ('sidebar_'+state+'_red_dot.png')) as icon:
        shot=Image.new('RGB',(300,200),'#ededed');shot.paste(icon,(40,60))
    gui=SimpleNamespace(screenshot=lambda **kw:shot,locate=pyautogui.locate,
        ImageNotFoundException=pyautogui.ImageNotFoundException)
    launcher=WechatImageLauncher(gui=gui);launcher.focus=lambda window:None
    window=SimpleNamespace(left=100,top=200,width=300,height=200)
    assert launcher.locate('sidebar_'+state,window) is not None
    opposite='inactive' if state=='active' else 'active'
    assert launcher.locate('sidebar_'+opposite,window) is None


def launcher_with_screens(screens):
    now = [0.]
    clicks = []
    launcher = WechatImageLauncher(gui=SimpleNamespace(click=lambda *p: clicks.append(p)),
                                   clock=lambda: now[0], sleep=lambda t: now.__setitem__(0, now[0]+t))
    launcher.focus = lambda window: None
    def locate(name, window):
        return (10, 20) if name in screens(len(clicks)) else None
    launcher.locate = locate
    return launcher, clicks


def test_navigation_clicks_only_inactive_and_confirms_green():
    launcher, clicks = launcher_with_screens(lambda n: {'sidebar_inactive'} if n == 0 else {'sidebar_active'})
    launcher.select(None, 'sidebar_active', 'sidebar_inactive', '入口')
    assert clicks == [(10, 20)]
    launcher.select(None, 'sidebar_active', 'sidebar_inactive', '入口')
    assert clicks == [(10, 20)]


def test_navigation_never_advances_when_click_does_not_select():
    launcher, clicks = launcher_with_screens(lambda n: {'sidebar_inactive'})
    with pytest.raises(RuntimeError, match='绿色'):
        launcher.select(None, 'sidebar_active', 'sidebar_inactive', '入口')
    assert len(clicks) == 1


def test_game_clicked_once_then_window_confirmation_required():
    launcher, clicks = launcher_with_screens(lambda n: {'game'})
    launcher.main_window = lambda: None
    launcher.select = lambda *args: None
    launcher.game_windows = lambda: []
    with pytest.raises(RuntimeError, match='未确认新游戏窗口'):
        launcher.open_game()
    assert len(clicks) == 1


def test_blank_recovery_requires_disconnect_activity_and_persistence():
    async def run():
        now, captures, restarts = [0.], [], []
        async def capture():
            captures.append(True)
            return (123, 'white')
        async def restart():restarts.append(True)
        recovery = BlankScreenRecovery(clock=lambda: now[0], capture=capture, restart=restart)
        async def poll(**kwargs):
            await recovery.poll(**dict(active=True, disconnected=True, kicked=False, closing=False, **kwargs))
        await recovery.poll(active=False, disconnected=True, kicked=False, closing=False)
        assert not captures
        await recovery.poll(active=True, disconnected=False, kicked=False, closing=False)
        await recovery.poll(active=True, disconnected=True, kicked=True, closing=False)
        assert not captures
        for t in (0, 5, 10):
            now[0] = t
            await poll()
        assert not restarts
        now[0] = 15
        await poll()
        assert restarts == [True]
        now[0] = 30
        await poll()
        assert len(captures) == 4
    asyncio.run(run())


def test_nonblank_or_changed_window_resets_confirmation():
    async def run():
        now, results, restarts = [0.], iter([(1,'black'),None,(1,'black'),(2,'black'),(2,'black')]), []
        async def capture():return next(results)
        async def restart():restarts.append(True)
        recovery = BlankScreenRecovery(clock=lambda: now[0], capture=capture, restart=restart)
        for t in (0, 5, 10, 15, 20):
            now[0] = t
            await recovery.poll(active=True, disconnected=True, kicked=False, closing=False)
        assert not restarts
    asyncio.run(run())
