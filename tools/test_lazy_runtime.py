import asyncio
from package.plugin_manager.lazy_runtime import operation_features, factory_source
from package.plugin_manager.transport import PluginTransport
from tools.test_plugin_runtime import FakeCdp


def test_bootstrap_never_embeds_feature_sources_and_registers_each_once():
    async def run():
        fake=FakeCdp();transport=PluginTransport(cdp=fake)
        await transport.connect(62000);transport.session_id='injected';await transport.install()
        expressions=[p['expression'] for m,p in fake.messages if m=='Runtime.evaluate']
        bootstrap=next(e for e in expressions if 'createPluginRuntime' in e)
        for name in ('createEnergyRuntime','createDailyRuntime','createDesireRuntime','createBattleAssistRuntime','createAutomationOverlay'):
            assert name not in bootstrap
        await transport.call('identity');await transport.call('configure',{'battle_assist':{'enabled':False}})
        assert not any('r.register(' in p.get('expression','') for _,p in fake.messages if p)
        await transport.call('inspect');await transport.call('inspect')
        registrations=[p['expression'] for _,p in fake.messages if p and 'r.register(' in p.get('expression','')]
        assert len(registrations)==1 and 'createEnergyRuntime' in registrations[0]
        assert 'function createDailyRuntime' not in registrations[0]
        assert 'function createDesireRuntime' not in registrations[0]
        await transport.call('desire_bag_stats')
        assert len(transport._lazy_registered)==2
        transport.invalidate();assert not transport._lazy_registered
        await transport.close()
    asyncio.run(run())


def test_dependency_mapping_and_factory_isolation():
    assert operation_features('identity')==[]
    assert operation_features('configure',{'battle_assist':{'enabled':False}})==[]
    assert operation_features('configure',{'battle_assist':{'enabled':True}})==['battle_assist']
    assert operation_features('player_information')==['ui']
    assert operation_features('tomb_raid')==['ui','daily']
    assert operation_features('desire_compose_once')==['ui','desire']
    assert 'createDesireRuntime' not in factory_source('daily')
    assert 'function createDailyRuntime' not in factory_source('ui')
