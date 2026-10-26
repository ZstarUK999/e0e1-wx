// Minimal resident: session ownership, command exclusion and lazy feature registry.
// Feature factories are supplied only when their feature is requested.
function createPluginRuntime(g,id,loader) {
  const factories={},features={},loading={};
  const requirements=op=>['ui',...(op.startsWith('desire_')?['desire']:
    /^(tomb_|arena_|free_summon|pet_hatch_|pet_fodder_)/.test(op)?['daily']:[])];
  const resident={id,config:null,stopped:false,pending:false,features,
    register(name,factory){if(!factories[name])factories[name]=factory;},
    async ensure(name){
      if(Object.prototype.hasOwnProperty.call(features,name))return features[name];
      if(!loading[name])loading[name]=(async()=>{
        const value=factories[name]?await factories[name](g,resident):loader?await loader(name,resident):undefined;
        if(value===undefined)throw Error('功能脚本尚未加载：'+name);
        features[name]=value;
        if(g.console)g.console.info('[plugin.ui]','按需加载功能：'+name);
        return value;
      })().finally(()=>{delete loading[name];});
      return loading[name];
    },
    async configure(args){
      args=args||{};
      g.__e0e1GameOverlaysEnabled=!args.ui || args.ui.game_overlays!==false;
      const assist=args.battle_assist||{enabled:false};
      if(assist.enabled)await (await this.ensure('battle_assist')).configure(assist);
      else if(features.battle_assist)await features.battle_assist.configure(assist);
      this.config=args;
      return {status:'ok',value:true};
    },
    async dispatch(op,args){
      args=args||{};
      if(op==='configure')return this.configure(args);
      if(op==='stop'){
        if(features.battle_assist)features.battle_assist.destroy();
        if(features.automation_overlay)features.automation_overlay.destroy();
        this.stopped=true;return {status:'ok',value:true};
      }
      if(this.stopped && !['inspect','capture','restore','home'].includes(op))
        return {status:'unavailable',message:'插件已停止'};
      if(this.pending)return {status:'uncertain',message:'上一条命令尚未结束'};
      if(op==='identity'){
        const r=g.ROLE||{},role=r.id!=null?String(r.id):'',hero=r.heroId!=null?String(r.heroId):'';
        return {status:'ok',value:{player_id:role||hero,role_id:role,hero_id:hero,
          name:String(r.userInfo && r.userInfo.name||''),
          legion_name:String(r.legion && (r.legion.legionName||r.legion.name)||r.legionName||'')}};
      }
      this.pending=true;
      try {
        for(const name of requirements(op))await this.ensure(name);
        return await features.ui.dispatch(op,args);
      }finally{this.pending=false;}
    }
  };
  return resident;
}
