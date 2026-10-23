import asyncio
import os
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from package.daily_tasks.pet_fodder import next_fodder_merge,PetFodderTask
from package.daily_tasks.scheduler import ExecutionUncertain
from package.plugin_manager.store import PluginConfigStore,default_config,validate_config
from package.plugin_manager.window import PluginWindow

def pet(id,progress,quality=2,eligible=True):
    return dict(id=id,progress=progress,quality=quality,eligible=eligible)

@pytest.mark.parametrize('pets,expected',[
    ([pet(1,0),pet(2,0),pet(3,1),pet(4,1)],(1,2)),
    ([pet(1,0),pet(2,1),pet(3,1)],(2,3)),
    ([pet(1,0),pet(2,1),pet(3,3),pet(4,3)],(3,4)),
    ([pet(1,7),pet(2,3),pet(3,3)],(1,2)),
    ([pet(1,7),pet(2,0,3),pet(3,0,3)],(2,3)),
    ([pet(1,0,4),pet(2,0,4),pet(3,0,3),pet(4,0,3)],(3,4)),
    ([pet(1,0,5),pet(2,0,5)],None),
    ([pet(1,0,eligible=False),pet(2,0)],None),
    ([pet(1,0),pet(2,1),pet(3,3)],None),
])
def test_pair_order(pets,expected):
    result=next_fodder_merge(pets)
    assert (result['target_id'],result['material_id'])==expected if expected else result is None

def test_task_failure_then_extra_three_and_stop_before_hell():
    class Game:
        def __init__(self):
            self.pets={p['id']:p for p in [pet(1,3),pet(2,3),pet(3,3),pet(4,3,3),pet(5,3,3),pet(6,3,3),pet(7,3,4),pet(8,3,4),pet(9,3,4)]};self.actions=[]
        async def home(self):pass
        async def pet_fodder_state(self):return {'pets':[dict(p) for p in self.pets.values()]}
        async def pet_fodder_merge(self,pair):
            a,b=self.pets[pair['target_id']],self.pets.pop(pair['material_id']);self.actions.append(pair)
            a['progress']+=b['progress']+1
            advanced=a['progress']>=(8 if a['quality']==2 else 10)
            if advanced:a['quality']+=1;a['progress']=0
            return {'confirmed':True,'advanced':advanced}
    async def run():
        g=Game();result=await PetFodderTask(g).run(SimpleNamespace(stop_requested=lambda:False))
        assert result.status=='success';assert [p['quality'] for p in g.actions]==[2,2,3,3,4,4]
        assert [p['target_progress'] for p in g.actions]==[3,7,3,7,3,7]
        assert next_fodder_merge(list(g.pets.values())) is None
        assert any(p['quality']==5 for p in g.pets.values())
    asyncio.run(run())

def test_unknown_receipt_stops_without_a_second_merge():
    class Game:
        calls=0
        async def home(self):pass
        async def pet_fodder_state(self):return {'pets':[pet(1,0),pet(2,0)]}
        async def pet_fodder_merge(self,pair):self.calls+=1;return {'confirmed':False}
    async def run():
        g=Game()
        with pytest.raises(ExecutionUncertain):await PetFodderTask(g).run(SimpleNamespace(stop_requested=lambda:False))
        assert g.calls==1
    asyncio.run(run())

def test_config_migration_gui_and_scheduler_registration(tmp_path):
    app=QApplication.instance() or QApplication([]);old=default_config();old['daily']['tasks'].pop('pet_fodder')
    assert validate_config(old)['daily']['tasks']['pet_fodder']['enabled'] is False
    bad=default_config();bad['daily']['tasks']['pet_fodder']['params']={'max_quality':5}
    with pytest.raises(ValueError):validate_config(bad)
    store=PluginConfigStore(tmp_path/'pets.json');window=PluginWindow(store)
    panel=window.task_panels['pet_fodder'];panel.enabled.setChecked(True)
    assert PluginConfigStore(store.path).snapshot()['daily']['tasks']['pet_fodder']['enabled']
    assert window.items['pet_hatch'].text(0)=='鬼仆'
    from package.plugin_manager.automation import AutomationScheduler
    from package.plugin_manager.state import RuntimeState
    assert 'pet_fodder' in AutomationScheduler(object(),RuntimeState(),window).capabilities
    window.deleteLater();app.processEvents()
