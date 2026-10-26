import asyncio
import json

import pytest

from package.plugin_manager.season_legion_statistics import apply_score,scan_battlefield
from tools.test_season_battlefield_scan import prepare
from tools.test_season_legion_statistics import setup


@pytest.mark.parametrize('kills,guards,deaths,expected',[(80,78,9,887),(134,48,17,1405),(100,9,16,1025),(0,0,0,0)])
def test_game_score_rule_includes_death_points(kills,guards,deaths,expected):
    row=dict(killRoleNum=kills,killGuardNum=guards,dieNum=deaths,statisticsComplete=True)
    apply_score(row)
    assert row['score']==expected and row['scoreSource']=='规则计算'
    assert not apply_score(row)


def test_server_score_preserved_and_derived_score_updates_or_clears():
    server=dict(score=999,statisticsComplete=True,killRoleNum=1,killGuardNum=2,dieNum=3)
    apply_score(server)
    assert server['score']==999 and server['scoreSource']=='服务端排名'
    row=dict(statisticsComplete=True,killRoleNum=1,killGuardNum=2,dieNum=3)
    apply_score(row,[20,2,3])
    assert row['score']==33
    row['dieNum']=4
    apply_score(row,[20,2,3])
    assert row['score']==36
    row['statisticsComplete']=False
    apply_score(row)
    assert row['score'] is None and row['scoreSource']=='统计不完整'


@pytest.mark.parametrize('changes',[dict(killGuardNum=None),dict(dieNum=None),dict(killRoleNum=-1),dict(statisticsComplete=False)])
def test_incomplete_statistics_do_not_get_scores(changes):
    row=dict(statisticsComplete=True,killRoleNum=1,killGuardNum=2,dieNum=3)
    row.update(changes);apply_score(row)
    assert row['score'] is None


def test_cached_legion_gets_scores_without_requests_and_saves_csv(tmp_path):
    app,panel=setup(tmp_path)
    bucket=panel.cache[panel.account]
    bucket['legion_statistics']={'war:99':dict(warId='war',legionId=99,legionName='其他阴司',complete=True,rows=[
        dict(id=100003,name='未上榜',statisticsComplete=True,killRoleNum=2,killGuardNum=4,dieNum=3)])}
    events=[];panel.requested.connect(lambda *args:events.append(args))
    panel._open_legion(0,0)
    assert not events
    assert panel.roles.item(0,4).text()=='27'
    assert panel.roles.item(0,12).text()=='规则计算'
    saved=json.loads(panel.cache_path.read_text(encoding='utf-8'))
    assert saved[panel.account]['legion_statistics']['war:99']['rows'][0]['score']==27
    path=tmp_path/'scores.csv';panel.export_table_csv(path)
    assert '规则计算' in path.read_text(encoding='utf-8-sig')
    panel.close()


def test_recursive_scan_calculates_new_players_and_preserves_server_scores(tmp_path):
    async def run():
        app,panel,transport,feature=prepare(tmp_path)
        await scan_battlefield(feature,dict(warId='war',bTimeId=1),'one',1)
        rows={str(r['id']):r for r in panel.cache[panel.account]['battlefield_scans']['war']['rows']}
        assert rows['100002']['score']==10
        assert rows['100004']['score']==13 and rows['100004']['scoreSource']=='规则计算'
        assert rows['100005']['score']==50 and rows['100005']['scoreSource']=='服务端结算'
        panel.close()
    asyncio.run(run())
