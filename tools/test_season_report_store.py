import json
import os

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from package.plugin_manager.season_insight import SeasonInsightPanel
from package.plugin_manager.season_report_store import SeasonReportStore
from package.plugin_manager.store import PluginConfigStore


def test_legacy_import_and_incremental_save_do_not_embed_reports_in_metadata(tmp_path):
    app=QApplication.instance() or QApplication([])
    config=PluginConfigStore(tmp_path/'plugins.json')
    path=tmp_path/'season_insight.json'
    account='wechat:1:42'
    report=dict(warId='war',roleId=100001,rows=[dict(battleId=1)],nextStart=15,complete=False)
    path.write_text(json.dumps({account:dict(wars={},ranks={},reports={'war:100001':report})}),encoding='utf-8')
    panel=SeasonInsightPanel(config)
    assert panel.cache[account]['reports']['war:100001']['nextStart']==15
    panel.account=account
    panel.save()
    assert 'reports' not in json.loads(path.read_text(encoding='utf-8'))[account]
    metadata=path.read_bytes()
    updated=dict(report,rows=[dict(battleId=1),dict(battleId=2)],nextStart=30)
    panel.save_report(account,'war:100001',updated)
    assert path.read_bytes()==metadata,'report paging must not serialize or rewrite metadata'
    panel.close()
    restored=SeasonInsightPanel(config)
    assert restored.cache[account]['reports']['war:100001']['nextStart']==30
    restored.close()


def test_idempotent_legacy_import_never_replaces_newer_sqlite_snapshot(tmp_path):
    store=SeasonReportStore(tmp_path/'reports.sqlite3')
    store.put('account','a',dict(nextStart=30,rows=[]))
    store.put('account','a',dict(nextStart=15,rows=[]),only_missing=True)
    assert store.load()['account']['a']['nextStart']==30
    store.put('other','a',dict(nextStart=99,rows=[]))
    assert store.load()['account']['a']['nextStart']==30
    assert store.load()['other']['a']['nextStart']==99
