// @name 运行时性能诊断（60秒）
// @description 可选诊断；不发送游戏请求，60秒自动停止，可用 e0e1Perf.snapshot() 读取。
(function(g){
  if(g.e0e1Perf)g.e0e1Perf.stop();
  const clock=()=>g.performance && typeof g.performance.now==='function'?g.performance.now():Date.now();
  let enabled=false,timer=null,started=0,finished=0,until=0,last=0,metrics={},samples=[],wrappers=[],generation=0;
  function record(name,ms,error){if(!enabled)return;let m=metrics[name];if(!m){if(Object.keys(metrics).length>=64)name='other';m=metrics[name]||(metrics[name]={calls:0,totalMs:0,maxMs:0,errors:0});}m.calls++;m.totalMs+=ms;m.maxMs=Math.max(m.maxMs,ms);if(error)m.errors++;}
  function measure(name,fn,receiver,args){if(!enabled)return fn.apply(receiver,args||[]);const t=clock();try{return fn.apply(receiver,args||[]);}catch(e){record(name+'.errors',0,true);throw e;}finally{record(name,clock()-t,false);}}
  function wrap(owner,key,label){if(!owner || typeof owner[key]!=='function')return;const original=owner[key];if(original.__e0e1PerfWrapped)return;if(wrappers.length>=32)return;
    function wrapped(){if(!enabled)return original.apply(this,arguments);const t=clock(),epoch=generation;let result;
      try{result=measure(label+'.sync',original,this,arguments);}catch(e){throw e;}
      // Wall time includes server waits; it is not CPU time. Return the original Promise unchanged.
      if(result && typeof result.then==='function')Promise.resolve(result).then(()=>{if(epoch===generation)record(label+'.wall',clock()-t,false);},()=>{if(epoch===generation)record(label+'.wall',clock()-t,true);});
      return result;
    }
    wrapped.__e0e1PerfWrapped=true;owner[key]=wrapped;wrappers.push({owner,key,original,wrapped});
  }
  function attach(){['candidates','march','flags','attack','speedUp'].forEach(k=>wrap(g.e0e1Season,k,'season.'+k));wrap(g.__e0e1PluginRuntime,'dispatch','resident.dispatch');['damageCurveJson','damageCurveStatus','dumpTreasureMap'].forEach(k=>wrap(g,k,k));}
  function resource(){const out={};
    try{const s=typeof g.damageCurveStatus==='function'?g.damageCurveStatus():null;if(s)out.damage={hooked:s.hooked,sides:s.sides,pvpSamples:s.pvpSamples};}catch(_){}
    try{if(typeof g.treasureMapOverlayStatus==='function')out.treasure=g.treasureMapOverlayStatus();}catch(_){}
    try{if(g.performance && g.performance.memory)out.heapUsedBytes=g.performance.memory.usedJSHeapSize;}catch(_){}
    return out;
  }
  function snapshot(){return {enabled,elapsedMs:Math.max(0,(finished || clock())-started),metrics:JSON.parse(JSON.stringify(metrics)),samples:samples.slice(),notes:['sync为同步执行耗时；wall包含异步/网络等待，不是CPU耗时','嵌套统计不能相加；事件循环延迟不是FPS；堆内存可能不可用']};}
  function stop(){if(enabled)finished=clock();enabled=false;generation++;if(timer!==null)clearInterval(timer);timer=null;wrappers.forEach(w=>{if(w.owner[w.key]===w.wrapped)w.owner[w.key]=w.original;});wrappers=[];return snapshot();}
  function start(seconds){stop();metrics={};samples=[];enabled=true;generation++;finished=0;started=last=clock();until=started+Math.min(300,Math.max(5,Number(seconds)||60))*1000;attach();
    timer=setInterval(()=>{const now=clock();samples.push({atMs:now-started,lagMs:Math.max(0,now-last-1000),...resource()});if(samples.length>300)samples.shift();last=now;attach();if(now>=until){const result=stop();if(g.console)g.console.info('[e0e1 perf]',JSON.stringify(result));}},1000);return {enabled:true,seconds:(until-started)/1000};
  }
  g.e0e1Perf={start,stop,snapshot,measure};start(60);
})(globalThis);
