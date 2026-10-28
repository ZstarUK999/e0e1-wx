"""WeChat duplicate-login timeout; one restart for each confirmed event."""
import time
import logging

LOG = logging.getLogger('plugin_manager')


class WechatReconnect:
    def __init__(self, transport, *, clock=time.monotonic):
        self.transport, self.clock = transport, clock
        self.event = None
        self.started = 0
        self.restarted = False
        self.restart_message = None
        self._configured = False

    async def poll(self, settings):
        enabled = settings.get('wechat_reconnect', False)
        if not enabled and not self._configured:
            self.event = None
            self.restarted = False
            self.restart_message = None
            return None
        # Mark before sending: a lost acknowledgement may still have installed the hook.
        if enabled:self._configured = True
        status = await self.transport.wechat_reconnect_status(enabled)
        if not enabled:self._configured = False
        if not settings.get('wechat_reconnect') or not status or not status.get('kicked'):
            self.event = None
            self.restarted = False
            self.restart_message = None
            return None
        event = status.get('event')
        if not isinstance(event, str) or not event:
            return None
        if event != self.event:
            self.event, self.started, self.restarted = event, self.clock(), bool(status.get('restarted'))
            self.restart_message = None
            LOG.warning('检测到微信账号重复登录，%d秒后重新打开游戏', settings['reconnect_seconds'])
            callback = getattr(self.transport, 'before_wechat_restart', None)
            if callback is not None:
                callback()
        if self.restarted:
            return self.restart_message or '已请求重新打开游戏，等待新会话'
        remaining = max(0, settings['reconnect_seconds'] - (self.clock() - self.started))
        if remaining > 0:
            return f'微信顶号：{remaining:.0f}秒后重新打开游戏'
        # Never replay a restart whose acknowledgement was lost.
        self.restarted = True
        self.restart_message = '重开请求结果未确认，请核对游戏窗口；本次不会自动重复打开'
        try:
            accepted = await self.transport.wechat_restart_after_kick(event)
        except Exception as exc:
            self.restart_message = '微信自动重开未完成：'+str(exc)
            LOG.exception('%s', self.restart_message)
            return self.restart_message
        if accepted is not True:
            LOG.error('顶号重开未执行：原游戏未确认退出，不调用游戏内部重启')
            self.restart_message = '顶号重开未执行，请手动关闭并从微信打开游戏'
            return self.restart_message
        self.restart_message = '已点击微信最近使用中的普通版遗弃之地，等待新会话'
        LOG.info('微信顶号等待结束，已点击微信最近使用中的普通版遗弃之地')
        return self.restart_message
