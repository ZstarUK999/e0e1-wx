// Auction deadlines use the game server clock; request spacing uses the local clock.
async function createAuctionAssistant(g) {
  const load=n=>g.System.import('chunks:///_virtual/'+n);
  const [base,mods,defs,configs,dates,services,ui,cfg,data]=await Promise.all(['base-module.ts','module-manager.ts','define-index.ts','configs.ts','date-util.ts','service-manager.ts','ui-manager.ts','ui-common-cfg.ts','server-data.ts'].map(load));
  const legion=()=>mods.GET_MODULE(base.ModuleLocalType.LEGION);
  const clock=()=>Number(dates.default.serverTime);
  const visible=()=>{const p=ui.UIManager.ins.find(cfg.CommonUICfgId.LegionAuctionUI);return !!(p && p.ui && p.ui.node && p.ui.node.isValid!==false);};
  let jobs=new Map(),timer=null,lease=0,generation=0,event=null,lastList=-Infinity,fixed=null,refreshSeq=0,acceptedSeq=0;
  const starts=new Map(),audit=[];
  const traceId=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,8);let auditSeq=0;
  function record(kind,fields={}){
    const entry={traceId,seq:++auditSeq,generation,kind,wallTime:Date.now(),serverTime:clock(),...fields};
    audit.push(entry);if(audit.length>200)audit.shift();
    if(g.console && typeof g.console.info==='function')g.console.info('[plugin.ui]','拍卖助手 '+JSON.stringify(entry));
  }
  function rows(source,preview){
    const l=legion();if(!l)return [];
    if(!source){source=l.auctionList || [];preview=l._isRealAuctionData===false;}
    const ord=new Map();
    return [...source].sort((a,b)=>a.cfgId-b.cfgId || a.id-b.id).map(a=>{
      const c=configs.AuctionCfg.getById(a.cfgId);if(!c)return null;
      const i=ord.get(a.cfgId)||0;ord.set(a.cfgId,i+1);const key=String(a.cfgId)+':'+i;
      if(preview)starts.set(key,Number(a.finalTime));
      return {key,id:a.id,cfgId:a.cfgId,name:c.name || String(a.cfgId),price:c.finalPrize,
        start:preview?Number(a.finalTime):(Number(a.activeTime)||starts.get(key)||0),end:Number(a.finalTime),preview,result:a.result,ownerId:a.ownerId,
        limited:!!(l.isServerAuctionLimitReached && a.type===1 && l.isServerAuctionLimitReached(a.cfgId))};
    }).filter(Boolean);
  }
  function stop(reason='已停止'){
    record('stop',{reason,heartbeatExpired:Date.now()>lease,visible:visible(),jobs:[...jobs.values()].map(j=>({key:j.key,id:j.id,sent:j.sent,status:j.status}))});
    generation++;if(timer!==null)g.clearInterval(timer);timer=null;
    for(const j of jobs.values())if(!j.done){j.done=true;j.status=reason;}
  }
  function valid(){return Date.now()<=lease && visible() && Number(data.ROLE.id)===event.role && Number(data.ROLE.legion.legionId)===event.legion;}
  function finish(){if([...jobs.values()].every(j=>j.done)){if(timer!==null){record('complete',{jobs:[...jobs.values()].map(j=>({key:j.key,id:j.id,sent:j.sent,status:j.status}))});g.clearInterval(timer);}timer=null;}}
  function status(){return {visible:visible(),now:clock(),rows:visible()?(fixed || rows()):[],jobs:[...jobs.values()].map(j=>({key:j.key,status:j.status,attempts:j.attempts,done:j.done,id:j.id || null,sent:j.sent || 0,lastError:j.lastError || null})),audit:audit.slice(),running:timer!==null};}
  function bindReal(real){
    fixed=real;
    for(const j of jobs.values()){
      const a=real.find(a=>a.key===j.key && a.cfgId===j.cfgId);
      if(!a){j.done=true;j.status='真实列表无此拍品';record('unmatched',{key:j.key,cfgId:j.cfgId});continue;}
      if(a.result>0){j.done=true;j.status=Number(a.ownerId)===Number(data.ROLE.id)?'已成交给我':'竞拍已结束';record('skip',{key:j.key,id:a.id,result:a.result,reason:j.status});continue;}
      if(a.limited){j.done=true;j.status='已达限购';record('skip',{key:j.key,id:a.id,reason:j.status});continue;}
      // activeTime is not the locally computed preview countdown. Preserve the
      // armed deadline; never reject a real auction ID just because times differ.
      j.id=a.id;j.status='已取得真实ID';
      record('matched',{key:j.key,id:j.id,cfgId:j.cfgId,previewStart:j.start,activeTime:a.start});
    }
  }
  async function refresh(gen){
    const seq=++refreshSeq,sentAt=Date.now();
    record('list-send',{request:seq});
    try{
      const r=await services.ServiceManager.ins.service(defs.AuctionService.getAuctionList,{},false);
      const ignored=gen!==generation || timer===null || !!fixed || seq<acceptedSeq || !valid();
      record('list-reply',{request:seq,elapsedMs:Date.now()-sentAt,count:r.resp && r.resp.itemList && r.resp.itemList.length,code:r.err && r.err.code,error:r.err && String(r.err.error || r.err.message || r.err),ignored});
      if(ignored)return;
      if(!r.err && r.resp && Array.isArray(r.resp.itemList) && r.resp.itemList.length){
        acceptedSeq=seq;
        const real=rows(r.resp.itemList,false);if(!real.length)return;
        const l=legion();l._auctionList=r.resp.itemList;l._isRealAuctionData=true;
        bindReal(real);tick();
      }
    }catch(e){record('list-exception',{request:seq,elapsedMs:Date.now()-sentAt,error:String(e.message||e)});if(gen===generation)for(const j of jobs.values())if(!j.done && !j.id)j.status='列表查询失败，继续等待';}
  }
  function send(j,gen){
    j.attempts++;j.pending++;j.next=Date.now()+50;j.status='请求中（'+j.attempts+'/3）';
    const attempt=j.attempts,sentAt=Date.now();
    Promise.resolve().then(()=>{
      if(gen!==generation || j.done || !valid())return null;
      j.sent=(j.sent || 0)+1;record('buy-send',{key:j.key,id:j.id,cfgId:j.cfgId,attempt,actualSent:j.sent,relativeToOpenMs:clock()-j.start});
      return services.ServiceManager.ins.service(defs.AuctionService.finalPrice,{id:j.id,cfgId:j.cfgId},false);
    }).then(r=>{
      if(r)record('buy-reply',{attempt,elapsedMs:Date.now()-sentAt,ignored:gen!==generation || j.done,key:j.key,id:j.id,cfgId:j.cfgId,ok:!r.err,code:r.err && r.err.code,error:r.err && String(r.err.error || r.err.message || r.err)});
      if(gen!==generation || j.done)return;
      j.pending--;
      if(!r){j.done=true;j.status='已停止';return;}
      if(!r.err){j.done=true;j.status='购买成功';if(r.resp && r.resp.item)legion().updateAuctionList([r.resp.item]);}
      else{
        const message=String(r.err.error || r.err.message || r.err);
        j.lastError=message;
        if(/竞拍已结束|拍卖已结束/.test(message)){j.done=true;j.status='竞拍已结束，停止';}
        else if(j.attempts>=3 && !j.pending){j.done=true;j.status='已请求3次：'+message;}
        else j.status='返回：'+message;
      }
      finish();
    }).catch(e=>{
      record('buy-exception',{attempt,elapsedMs:Date.now()-sentAt,key:j.key,id:j.id,error:String(e.message||e)});
      if(gen!==generation || j.done)return;
      j.pending--;j.lastError=String(e.message||e);
      if(j.attempts>=3 && !j.pending){j.done=true;j.status='3次请求结束：'+j.lastError;finish();}
    });
  }
  function tick(){
    if(timer===null)return;
    if(!valid()){stop('界面关闭或连接中断，已停止');return;}
    const now=clock(),gen=generation;
    if(!fixed){
      const due=[...jobs.values()].some(j=>!j.done && now>=j.start-500);
      if(due && now-lastList>=100){lastList=now;void refresh(gen);}
      return;
    }
    for(const j of jobs.values())if(!j.done && j.id && now>=j.start-500 && j.attempts<3 && Date.now()>=j.next)send(j,gen);
    finish();
  }
  return {
    revision:3,
    status(){lease=Date.now()+5000;if(!visible()){if(timer!==null)stop('已离开拍卖行');fixed=null;starts.clear();}return status();},
    arm(keys){
      if(!visible())throw Error('请先在游戏中进入阴司→拍卖行');
      if(timer!==null)throw Error('已有拍卖任务，请先停止');
      const current=rows(),now=clock(),selected=[...new Set(keys)];
      if(!selected.length)throw Error('请先勾选拍品');
      const pending=[];
      for(const key of selected){
        const a=current.find(a=>a.key===key);
        if(!a || !Number.isFinite(a.start) || a.start<=0 || now>=a.start || a.result>0 || a.limited)throw Error('所选拍品已开拍、不可购买或倒计时无效，请刷新选择');
        pending.push({key,cfgId:a.cfgId,start:a.start,next:0,attempts:0,sent:0,pending:0,done:false,status:'等待开拍前500ms'});
      }
      record('arm',{keys:selected,items:pending.map(j=>({key:j.key,cfgId:j.cfgId,openTime:j.start,triggerTime:j.start-500}))});
      generation++;fixed=null;jobs=new Map(pending.map(j=>[j.key,j]));event={role:Number(data.ROLE.id),legion:Number(data.ROLE.legion.legionId)};
      lease=Date.now()+5000;lastList=-Infinity;acceptedSeq=0;
      if(legion()._isRealAuctionData===true)bindReal(current);
      timer=g.setInterval(()=>{try{tick();}catch(e){record('timer-exception',{error:String(e.stack||e)});stop('定时器异常，已停止');}},10);return status();
    },
    stop(){stop('手动停止');return status();},destroy(){stop('助手已卸载');},tick
  };
}
