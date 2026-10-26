import asyncio
import csv
import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from package.plugin_manager.legion_bloodmoon import LegionBloodmoonPanel, export_statistics, ranked_rows


def data():
    return dict(account='1:42', legionId=42, warId='war-1', name='血月', fetchedAt='2026-10-26', note='服务端统计',
                rows=[dict(id='10', name='甲,乙', score=10, killRoleNum=2, killGuardNum=3, dieNum=4),
                      dict(id='11', name='=危险公式', score=100, killRoleNum=0, killGuardNum=5, dieNum=0),
                      dict(id='12', name='缺失', score=None, killRoleNum=None, killGuardNum=None, dieNum=None)])


def test_csv_and_ranking(tmp_path):
    path = tmp_path / '统计.csv'
    export_statistics(path, data())
    assert path.read_bytes().startswith(b'\xef\xbb\xbf')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.reader(stream))
    assert rows[0][-4:] == ['杀敌次数', '攻城次数', '总积分', '死亡次数']
    assert rows[1][5] == '11' and rows[1][6] == "'=危险公式"
    assert rows[2][6] == '甲,乙' and rows[2][-1] == '4'
    assert rows[3][-1] == '' and rows[3][4] == ''
    assert [r['id'] for r in ranked_rows(data()['rows'])] == ['11', '10', '12']


def test_panel_selection_and_statistics():
    app = QApplication.instance() or QApplication([])
    panel = LegionBloodmoonPanel()
    panel.accept_history(dict(rows=[dict(warId='war-1', name='血月'), dict(warId='war-2', name='另一场')]))
    panel.accept(data())
    assert panel.table.rowCount() == 3 and panel.table.item(0, 1).text() == '11'
    assert panel.table.item(1, 7).text() == '4' and panel.table.item(2, 7).text() == '—'
    assert panel.export.isEnabled()
    panel.selector.setCurrentIndex(1)
    assert panel.data is None and panel.table.rowCount() == 0 and not panel.export.isEnabled()
    panel.accept(data())
    assert panel.data is None
    panel.close()


def test_feature_session_and_failure(tmp_path):
    from package.plugin_manager.legion import LegionFeature, LegionPanel
    app = QApplication.instance() or QApplication([])
    panel = LegionPanel(SimpleNamespace(path=tmp_path / 'plugins.json'))
    state = SimpleNamespace(installed='one', closing=False)
    class Transport:
        async def season_insight(self, op, args):
            if op == 'history':
                return dict(rows=[dict(warId='war-1', name='血月')])
            return data()
    feature = LegionFeature(Transport(), state, panel)
    asyncio.run(feature.fetch_bloodmoon('history', {}))
    asyncio.run(feature.fetch_bloodmoon('statistics', dict(warId='war-1')))
    assert panel.bloodmoon.data['warId'] == 'war-1'
    panel.bloodmoon.clear()
    async def changed(*args):
        state.installed = 'two'
        return data()
    feature.transport.season_insight = changed
    asyncio.run(feature.fetch_bloodmoon('statistics', {}))
    assert panel.bloodmoon.data is None and panel.bloodmoon.fetch.isEnabled()
    panel.close()


def test_statistics_allowed_by_both_transports():
    from package.plugin_manager.transport import PluginTransport
    from package.plugin_manager.douyin import DouyinTransport
    async def evaluate(expression, context_id, timeout_ms):
        assert '"statistics"' in expression and 'getSeasonBfRoleResult' in expression
        assert context_id == 7
        return data()
    fake = SimpleNamespace(_evaluate=evaluate, context_id=7)
    assert asyncio.run(PluginTransport.season_insight(fake, 'statistics', {'warId': 'war-1'}))['warId'] == 'war-1'
    async def rpc(op, args, timeout_ms):
        assert op == 'season-insight' and args['op'] == 'statistics'
        return data()
    fake = SimpleNamespace(_rpc=rpc)
    assert asyncio.run(DouyinTransport.season_insight(fake, 'statistics', {'warId': 'war-1'}))['warId'] == 'war-1'


def test_persistent_cache_selection_export_and_explicit_refresh(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / 'cache.json'
    panel = LegionBloodmoonPanel(path)
    history = dict(account='wechat:1:42', rows=[dict(warId='war-1', name='血月'), dict(warId='war-2', name='其他场')])
    panel.accept_history(history)
    panel.accept(dict(data(), cacheAccount='wechat:1:42'))
    requests = []
    panel.requested.connect(lambda op, args: requests.append((op, args)))
    panel.selector.setCurrentIndex(1)
    panel.selector.setCurrentIndex(0)
    assert panel.data['warId'] == 'war-1' and panel.export.isEnabled()
    panel.fetch.click()
    assert requests == []
    panel.refresh.click()
    assert requests[0][0] == 'statistics' and requests[0][1]['cacheAccount'] == 'wechat:1:42'
    panel.close()
    again = LegionBloodmoonPanel(path)
    assert again.data['warId'] == 'war-1' and again.table.rowCount() == 3
    assert '本地缓存' in again.message.text()
    again.accept_history(dict(account='wechat:2:43', rows=history['rows']))
    assert again.data is None and not again.export.isEnabled()
    again.accept_history(dict(account='wechat:1:42', rows=[]))
    assert again.data['warId'] == 'war-1', 'cached historical wars survive server expiry'
    again.close()


def test_corrupt_cache_does_not_break_panel(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / 'cache.json'
    path.write_text('bad', encoding='utf-8')
    panel = LegionBloodmoonPanel(path)
    assert panel.data is None and panel.selector.count() == 0
    panel.close()
