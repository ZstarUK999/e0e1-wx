"""Bounded passive memory sampling for failures that outlive the game window."""
from __future__ import annotations
import asyncio
import json
import logging
import time
import psutil

LOG=logging.getLogger('plugin_manager.memory')
LOG.propagate=False  # 文件日志单独接入此 logger，不传到父级或控制台。
HEALTH_EXPRESSION=r"""(() => {
 const g=globalThis,out={overlays:g.__e0e1GameOverlaysEnabled!==false};
 out.loadedFeatures=g.__e0e1PluginRuntime && g.__e0e1PluginRuntime.features?Object.keys(g.__e0e1PluginRuntime.features):[];
 function read(key,fn){try{out[key]=fn();}catch(e){out[key]={unavailable:true,error:String(e && (e.stack || e.message) || e).slice(0,1200)};}}
 read('battle',()=>g.__e0e1BattleAssist && g.__e0e1BattleAssist.resourceStatus?g.__e0e1BattleAssist.resourceStatus():null);
 read('automation',()=>g.__e0e1AutomationOverlay && g.__e0e1AutomationOverlay.resourceStatus?g.__e0e1AutomationOverlay.resourceStatus():null);
 read('treasure',()=>typeof g.treasureMapOverlayStatus==='function'?g.treasureMapOverlayStatus():null);
 read('damage',()=>{if(typeof g.damageCurveStatus!=='function')return null;const s=g.damageCurveStatus();return {running:s.running,hooked:s.hooked,pvpSamples:s.pvpSamples,sides:s.sides};});
 return out;
})()"""


def process_memory():
    rows=[]
    for proc in psutil.process_iter(['pid','name','exe']):
        try:
            if (proc.info.get('name') or '').lower()!='wechatappex.exe':continue
            path=(proc.info.get('exe') or '').lower().replace('/','\\')
            if 'radiumwmpf' not in path or 'wxwork' in path:continue
            info=proc.memory_info()
            rows.append({'pid':proc.pid,'privateBytes':getattr(info,'private',getattr(info,'pagefile',info.rss))})
        except (psutil.Error,OSError):continue
    rows.sort(key=lambda v:v['privateBytes'],reverse=True)
    result={'processCount':len(rows),'privateBytes':sum(v['privateBytes'] for v in rows),'largest':rows[:4]}
    try:
        proc=psutil.Process();info=proc.memory_info()
        result['python']={'pid':proc.pid,'rssBytes':info.rss,
            'privateBytes':getattr(info,'private',getattr(info,'pagefile',info.rss)),
            'threads':proc.num_threads()}
        if hasattr(proc,'num_handles'):result['python']['handles']=proc.num_handles()
    except (psutil.Error,OSError):pass
    return result


class RuntimeMemoryMonitor:
    def __init__(self, *, clock=time.monotonic, processes=process_memory):
        self.clock=clock;self.processes=processes;self.next_sample=0;self.session=None;self.last=None

    async def sample(self,transport,session):
        getter=getattr(transport,'memory_snapshot',None)
        if not session or not getter or not transport.connected:return
        now=self.clock()
        if session!=self.session:self.session=session;self.next_sample=0
        if now<self.next_sample:return
        self.next_sample=now+300
        result={'session':session,'pythonAsyncTasks':len(asyncio.all_tasks())}
        cdp=getattr(transport,'cdp',None)
        if cdp is not None:
            result['cdp']={'pending':len(getattr(cdp,'pending',{})),
                'cachedEvents':len(getattr(cdp,'events',[]))}

        try:result['native']=await asyncio.to_thread(self.processes)
        except Exception as exc:result['nativeUnavailable']=type(exc).__name__
        try:result['js']=await getter()
        except Exception as exc:result['jsUnavailable']=type(exc).__name__
        self.last=result
        LOG.info('运行内存诊断：%s',json.dumps(result,ensure_ascii=False,separators=(',',':')))
