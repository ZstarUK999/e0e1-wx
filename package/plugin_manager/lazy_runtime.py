"""Shared lazy factory definitions for CDP and the statically compiled Douyin bridge."""
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SOURCES={
    'ui': [('daily_tasks','sweep_runtime.js')],
    'daily': [('daily_tasks','daily_runtime.js')],
    'desire': [('plugin_manager','desire_runtime.js')],
    'battle_assist': [('plugin_manager','pve_assist_overlay.js'),('plugin_manager','battle_assist_runtime.js')],
    'automation_overlay': [('plugin_manager','automation_overlay.js')],
    'startup': [('plugin_manager','startup_cleanup.js')],
}
RETURNS={
    'ui': 'createEnergyRuntime(g)',
    'daily': 'createDailyRuntime',
    'desire': 'createDesireRuntime',
    'battle_assist': '(g.__e0e1BattleAssist=createBattleAssistRuntime(g))',
    'automation_overlay': '(g.__e0e1AutomationOverlay=createAutomationOverlay(g))',
    'startup': '()=>dismissStartupPage(g)',
}


def factory_source(name):
    source='\n'.join((ROOT.parent/folder/file).read_text(encoding='utf-8-sig') for folder,file in SOURCES[name])
    return 'function(g,resident){\n'+source+'\nreturn '+RETURNS[name]+';}'


def operation_features(op,payload=None):
    if op=='configure':
        return ['battle_assist'] if (payload or {}).get('battle_assist',{}).get('enabled') else []
    if op in ('identity','stop'):return []
    result=['ui']
    if op.startswith('desire_'):result.append('desire')
    elif op.startswith(('tomb_','arena_','free_summon','pet_hatch_','pet_fodder_')):result.append('daily')
    return result
