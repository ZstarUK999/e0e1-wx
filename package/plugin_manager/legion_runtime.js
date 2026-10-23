// Reuse the game's public legion preview. Never replace the player's own legion data.
async function readLegionPerspective(g, id) {
  function pack(info) {
    if(!info || !Number.isSafeInteger(Number(info.id)) || Number(info.id)<=0)return null;
    const members=[];
    if(!info.members || typeof info.members.forEach!=='function')throw Error('阴司接口未返回成员列表');
    const keys=['name','level','sName','sId','fightPower','maxFightPower','job','contrib','contribDay','isOnline','lastOnlineTime','joinTime','passStageId'];
    info.members.forEach((m,key)=>{
      if(members.length>=500)return;
      const row={id:String(m.id||key)};
      for(const k of keys)if(['string','number','boolean'].includes(typeof m[k]))row[k]=typeof m[k]==='string'?m[k].slice(0,160):m[k];
      members.push(row);
    });
    const out={id:String(info.id),members};
    for(const k of ['name','sName','serverId','level','leaderId','leaderName','memberNum','memberNumMax','fightPower','totalPower','notice'])if(['string','number','boolean'].includes(typeof info[k]))out[k]=typeof info[k]==='string'?info[k].slice(0,1000):info[k];
    return out;
  }
  if(id!==null && id!==undefined){
    const n=Number(id);if(!Number.isSafeInteger(n)||n<=0)throw Error('请输入有效的阴司ID');
    const [{GET_MODULE},{ModuleLocalType}]=await Promise.all([g.System.import('chunks:///_virtual/module-manager.ts'),g.System.import('chunks:///_virtual/base-module.ts')]);
    const module=GET_MODULE(ModuleLocalType.LEGION);
    let actual='未返回';
    for(let attempt=0;attempt<2;attempt++){
      const result=await module.sendGetLegionPreview(n,false);
      // Legacy clients return the legion directly; current clients return
      // {legion, seasonScore}. Check the actual legion, not the envelope.
      const info=result && Object.prototype.hasOwnProperty.call(result,'legion')?result.legion:result;
      if(!info)throw Error('阴司不存在或当前账号无法查看（请求ID='+n+'）');
      if(info.id===undefined)throw Error('阴司接口返回结构异常（请求ID='+n+'，字段='+Object.keys(result||{}).join(',')+'）');
      actual=String(info.id);
      if(Number(info.id)===n)return pack(info);
      // Recheck a transient/default preview rather than accepting foreign data.
      if(attempt===0 && typeof g.setTimeout==='function')await new Promise(resolve=>g.setTimeout(resolve,200));
    }
    throw Error('阴司接口返回的ID不匹配（请求ID='+n+'，返回ID='+actual+'，已复核2次）');
  }
  const params=g.UIManager&&g.UIManager.ins&&g.UIManager.ins.viewParams;
  const pages=Object.values(params||{});
  const detail=pages.find(p=>p&&p.showing&&String(p.cfgId||(p.cfg&&p.cfg.id)||'')==='LegionInfoUI');
  if(detail)return detail.ui&&detail.ui.legionInfo?pack(detail.ui.legionInfo):null;
  for(const p of pages){
    if(!p||!p.showing||!p.ui)continue;
    const name=String(p.cfgId||(p.cfg&&p.cfg.id)||'');
    if(!/^Legion/.test(name))continue;
    const info=p.ui.legionInfo || ((name==='LegionUI'||name==='LegionMainUI')&&p.ui.module&&p.ui.module.legionInfo);
    if(info&&info.members)return pack(info);
  }
  return null;
}

// Only public read interfaces; errors never become completed/missing IDs.
async function scanLegionPlayer(g, id) {
  const n=Number(id);
  if(!Number.isInteger(n)||n<10000000||n>99999999)throw Error('玩家ID必须为8位整数');
  const {GoodFriendService}=await g.System.import('chunks:///_virtual/define-index.ts');
  const reply=await GoodFriendService.search({targetId:n});
  if(!reply || typeof reply.code!=='number')throw Error('好友查询未返回有效回执');
  if(reply.code!==0){
    const message=String(reply.error||'好友查询失败');
    if(reply.code===330015 && /未找到对方数据/.test(message))return null;
    if(/(玩家|角色|用户|目标).{0,6}(不存在|未找到)|未找到.{0,6}(玩家|角色|用户)/.test(message))return null;
    throw Error(message+' ('+reply.code+')');
  }
  const info=reply.getData().info;
  if(!info)return null;
  if(Number(info.id)!==n)throw Error('好友查询返回ID不匹配');
  const row={id:String(n)};
  for(const key of ['name','fightPower','legionId','legionName','sId','sName']){
    if(!['string','number'].includes(typeof info[key]))throw Error('好友查询缺少字段：'+key);
    row[key]=typeof info[key]==='string'?info[key].slice(0,160):info[key];
  }
  if(Number.isFinite(info.lOnlineTime)&&info.lOnlineTime>0)row.lastOnlineTime=info.lOnlineTime;
  if(typeof info.online==='boolean')row.online=info.online;
  return row;
}

async function searchScanLegion(g, text) {
  const [{GET_MODULE},{ModuleLocalType}]=await Promise.all([
    g.System.import('chunks:///_virtual/module-manager.ts'),g.System.import('chunks:///_virtual/base-module.ts')]);
  const reply=await GET_MODULE(ModuleLocalType.LEGION).sendSearchLegion(String(text).trim());
  if(!reply)throw Error('阴司搜索冷却中，请稍后重试');
  if(reply.err)throw Error(String(reply.err.error||'搜索阴司失败'));
  const info=reply.resp && reply.resp.legionData;
  if(!info || !info.id)throw Error('未找到阴司');
  return readLegionPerspective(g,String(info.id));
}

async function scanLegionPlayers(g, ids) {
  if(!Array.isArray(ids)||!ids.length||ids.length>10||new Set(ids.map(String)).size!==ids.length)throw Error('批量查询须为1至10个不同玩家ID');
  return Promise.all(ids.map(async id=>{
    try{return {id:String(id),value:await scanLegionPlayer(g,id)};}
    catch(e){return {id:String(id),error:String(e.message||e)};}
  }));
}
