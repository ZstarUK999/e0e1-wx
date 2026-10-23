from copy import deepcopy

from package.plugin_manager.player_pvp import PlayerPvpHistory,estimate_pvp


def stats(kind='erlang',pid='12324803'):
    return {'player_id':pid,'base_up':100,'base_down':50,'face_kind':kind,'face_complete':True,'face_pvp':48,
        'desire':{'current':10,'best':30},'magic':{'current':20,'best':50,'current_id':1,'current_name':'日常'},
        'faces':[{'slot':i,'config_id':6000+i,'name':'二郎','level':40,'quality':6,'star':1,'pvp':6,
            'base_attributes':[{'id':1,'name':'攻击力','value':1000,'style':1}],
            'entries':[{'id':100,'name':'PVP增伤','value':100,'style':2,'unlock':False}]} for i in range(1,9)],
        'equipment_plan':2,'suits':[[6001,8]],'erlang_snapshot':{'id':int(pid),'attribute':{'__map__':[[117,10000],[118,5000]]},
            'pet':{'cfgId':7},'magic':{'onUsePlan':1}},'missing':[]}


def test_diff_only_and_erlang_never_subtracted():
    value=estimate_pvp(stats())
    assert value['low']==value['high']==200
    assert value['desire_extra']==20 and value['magic_extra']==30
    same=stats();same['desire']['current']=30;same['magic']['current']=50
    assert estimate_pvp(same)['low']==150


def test_wukong_range_and_history_only_replace_face_contribution():
    value=estimate_pvp(stats('wukong'))
    assert (value['low'],value['high'])==(202,212)
    value=estimate_pvp(stats('wukong'),{'pvp':60,'observed_base_up':999})
    assert value['low']==value['high']==222
    assert '套装 10%' in value['face_note']
    # Explicitly recorded bonus is used once, not added on top of the default.
    assert estimate_pvp(stats('wukong'),{'pvp':60,'set_bonus':10})['low']==222


def test_full_snapshot_history_persists_and_is_platform_and_player_isolated(tmp_path):
    path=tmp_path/'scan.db';store=PlayerPvpHistory(path,'wechat')
    source=stats();history=store.observe(source)
    assert history['snapshot']==source['erlang_snapshot']
    assert history['set_bonus']==10
    assert history['faces']==source['faces'] and history['suits']==source['suits']
    assert history['equipment_plan']==2
    wukong=stats('wukong');wukong['erlang_snapshot']=None
    again=PlayerPvpHistory(path,'wechat').observe(wukong)
    assert again==history
    assert PlayerPvpHistory(path,'douyin').observe(wukong) is None
    assert store.observe({**wukong,'player_id':'12324804'}) is None
    # Incomplete equipment must never overwrite complete observed equipment.
    broken=stats();broken['face_complete']=False;broken['face_pvp']=1
    assert store.observe(broken)==history
    source['face_pvp']=64;source['erlang_snapshot']['pet']['cfgId']=8
    assert store.observe(source)['snapshot']['pet']['cfgId']==8
    assert store.observe(wukong)['pvp']==64


def test_header_detail_and_incomplete_data_do_not_make_zero_estimate(tmp_path):
    store=PlayerPvpHistory(tmp_path/'scan.db','wechat')
    result=store.decorate({'text':'玩家正文','pvp_estimate':stats()})
    assert result['text'].startswith('── PVP加成预估 ──')
    assert '预估：200%' in result['text'] and '历史记录二郎套装' in result['text']
    assert '攻击力 1000' in result['text'] and 'PVP增伤 1%' in result['text']
    assert '当前法器方案：1「日常」' in result['text']
    assert '二郎套装额外加成：10%' in result['text']
    assert '替换用PVP合计：58%' in result['text']
    broken=deepcopy(stats());broken['missing']=['当前法器方案未下发']
    result=store.decorate({'text':'正文','pvp_estimate':broken})
    assert result['pvp_result']['missing']==['当前法器方案未下发']
    assert result['pvp_result']['low']==200
    assert '暂不计算' not in result['text']
    assert '按现有数据预估' in result['text']
    broken['magic']['current']=None;broken['magic']['best']=None
    broken['missing']=['脸谱部位1基础配置或等级缺失','当前法器方案未下发']
    result=store.decorate({'text':'正文','pvp_estimate':broken})
    assert result['pvp_result']['low']==170 and 'PVP增伤＋减免预估：170%' in result['text']
