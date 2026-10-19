// 两个平台共用的 Cocos 托管浮层。仅显示状态和请求停止，不发送游戏业务请求。
function createAutomationOverlay(g) {
  let data={active:false,run_id:'',task:'',status:''}, stopRequested=false;
  let cc=null, loading=null, panel=null, title=null, detail=null, exitLabel=null, timer=null;
  let lastUpdate=0, operation='', position=null;
  const valid=node=>!!node && (cc && typeof cc.isValid==='function'?cc.isValid(node,true):node.isValid!==false);
  const snapshot=()=>({run_id:data.run_id,active:!!data.active,stop_requested:stopRequested});
  function unmount() {
    if(valid(panel))panel.destroy();
    panel=title=detail=exitLabel=null;
  }
  function remove() {
    if(timer!==null){clearInterval(timer);timer=null;}
    unmount();
  }
  function stop() {
    if(!data.active || stopRequested)return;
    stopRequested=true;operation='等待当前操作确认后返回主界面';render();
  }
  function dimensions(host) {
    const transform=host.getComponent(cc.UITransform);
    const visible=cc.view.getVisibleSize();
    return {width:transform && transform.width || visible.width,height:transform && transform.height || visible.height};
  }
  function mount() {
    const manager=g.UIManager && g.UIManager.ins;
    const host=manager && manager.system;
    if(!cc || !valid(host)){unmount();return;}
    if(valid(panel) && panel.parent===host)return;
    if(valid(panel))panel.destroy();
    const size=dimensions(host),width=Math.min(340,size.width-24),height=154;
    function node(name,parent,w,h,x,y) {
      const n=new cc.Node(name);n.layer=host.layer;
      n.addComponent(cc.UITransform).setContentSize(w,h);parent.addChild(n);n.setPosition(x,y,0);return n;
    }
    function background(n,w,h,color) {
      const graph=n.addComponent(cc.Graphics);graph.fillColor=new cc.Color(...color);
      graph.roundRect(-w/2,-h/2,w,h,10);graph.fill();
    }
    function label(parent,name,w,h,x,y,size) {
      const n=node(name,parent,w,h,x,y),l=n.addComponent(cc.Label);
      l.fontSize=size;l.lineHeight=size+5;l.color=new cc.Color(245,247,250,255);
      l.overflow=cc.Label.Overflow.CLAMP;l.horizontalAlign=cc.HorizontalTextAlignment.CENTER;
      return l;
    }
    panel=node('e0e1_automation_overlay',host,width,height,0,0);
    background(panel,width,height,[24,30,42,235]);
    panel.addComponent(cc.BlockInputEvents);
    if(!position)position={x:0,y:size.height/2-230};
    const place=()=>{
      position.x=Math.max(-size.width/2+width/2,Math.min(size.width/2-width/2,position.x));
      position.y=Math.max(-size.height/2+height/2,Math.min(size.height/2-height/2,position.y));
      panel.setPosition(position.x,position.y,0);
    };
    place();
    title=label(panel,'托管状态（拖动）',width-20,32,0,53,21);
    detail=label(panel,'当前操作',width-24,52,0,9,17);
    const exit=node('退出托管',panel,150,34,0,-50);background(exit,150,34,[166,57,57,255]);
    exitLabel=label(exit,'按钮文字',140,30,0,0,18);
    const events=cc.Node.EventType;
    title.node.on(events.TOUCH_MOVE,event=>{
      const delta=event.getUIDelta();position.x+=delta.x;position.y+=delta.y;place();
      event.propagationStopped=true;
    });
    exit.on(events.TOUCH_END,event=>{event.propagationStopped=true;stop();});
  }
  function render() {
    if(!data.active){remove();return;}
    if(g.__e0e1GameOverlaysEnabled===false){unmount();return;}
    mount();if(!valid(panel))return;
    const stopping=stopRequested || data.phase==='stopping';
    title.string=stopping?'正在退出托管':data.phase==='waiting'?'正在等待 · 托管正常':data.phase==='paused'?'托管已暂停':'正在托管 · 可拖动';
    if(!stopping && data.phase==='waiting') {
      const seconds=Number.isFinite(data.next_check_at)?Math.max(0,Math.ceil((data.next_check_at-Date.now())/1000)):null;
      const duration=seconds===null?'':seconds===0?'即将检查':
        `${Math.floor(seconds/3600)?Math.floor(seconds/3600)+'小时':''}${Math.floor(seconds%3600/60)?Math.floor(seconds%3600/60)+'分':''}${seconds%60}秒后检查`;
      detail.string=data.next_task?`下次：${data.next_task}\n${duration}`:(data.status || '暂无启用的定时任务');
    } else {
      detail.string=[data.task || (stopping?'正在安全收尾':'当前任务'),operation || data.status || '正在扫描待执行任务'].join('\n');
    }
    exitLabel.string=stopRequested?'正在安全收尾…':'退出托管';
  }
  const api={snapshot,
    shouldStop:()=>!!data.active && stopRequested,
    setOperation(text){operation=String(text || '').slice(0,120);if(operation)data.phase='running';if(data.active)render();},
    async update(value) {
      const next=value || {};
      if(next.run_id && next.run_id!==data.run_id){stopRequested=false;operation='';}
      if(next.task!==data.task)operation='';
      data={...data,...next};lastUpdate=Date.now();
      if(!data.active){remove();return snapshot();}
      if(!cc){
        if(!loading)loading=g.System.import('cc').then(module=>{cc=module;}).finally(()=>{loading=null;});
        await loading;
      }
      if(!data.active)return snapshot();
      render();
      if(timer===null)timer=setInterval(()=>{
        if(Date.now()-lastUpdate>12000){stopRequested=true;operation='连接中断，已暂停托管';}
        try{render();}catch(e){remove();}
      },500);
      return snapshot();
    },
    destroy(){data.active=false;stopRequested=true;remove();}
  };
  return api;
}
