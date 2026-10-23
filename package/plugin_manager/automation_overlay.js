// 两个平台共用的 Cocos 托管浮层。仅显示状态和请求停止，不发送游戏业务请求。
function createAutomationOverlay(g) {
  let data={active:false,run_id:'',task:'',status:''}, stopRequested=false;
  let cc=null, loading=null, panel=null, title=null, detail=null, exitLabel=null, timer=null;
  let lastUpdate=0, operation='', position=null, layoutPanel=null;
  const labelSizes=new WeakMap();
  const valid=node=>!!node && (cc && typeof cc.isValid==='function'?cc.isValid(node,true):node.isValid!==false);
  const snapshot=()=>({run_id:data.run_id,active:!!data.active,stop_requested:stopRequested});
  function unmount() {
    if(valid(panel))panel.destroy();
    panel=title=detail=exitLabel=null;layoutPanel=null;
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
    const size=dimensions(host),width=Math.min(420,size.width-24);let height=180;
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
      // Reuse glyphs for the continuously changing countdown instead of whole-string textures.
      if(cc.Label.CacheMode && cc.Label.CacheMode.CHAR!==undefined)l.cacheMode=cc.Label.CacheMode.CHAR;
      l.fontSize=size;l.lineHeight=size+5;l.color=new cc.Color(245,247,250,255);
      l.overflow=cc.Label.Overflow.CLAMP;l.horizontalAlign=cc.HorizontalTextAlignment.CENTER;
      l.enableWrapText=true;
      // Adding/enabling Label can resize its UITransform while overflow is NONE.
      // Apply the intended bounds after all Label properties are configured.
      n.getComponent(cc.UITransform).setContentSize(w,h);
      labelSizes.set(l,{width:w,height:h});
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
    title=label(panel,'托管状态（拖动）',width-24,32,0,53,21);
    title.enableWrapText=false;title.overflow=cc.Label.Overflow.SHRINK===undefined?cc.Label.Overflow.CLAMP:cc.Label.Overflow.SHRINK;
    detail=label(panel,'当前操作',width-24,52,0,9,17);
    const exit=node('退出托管',panel,150,34,0,-50);background(exit,150,34,[166,57,57,255]);
    exitLabel=label(exit,'按钮文字',180,30,0,0,18);
    exitLabel.enableWrapText=false;exitLabel.overflow=title.overflow;
    const graph=panel.getComponent(cc.Graphics);
    const setBounds=(l,w,h,x,y)=>{labelSizes.set(l,{width:w,height:h});l.node.getComponent(cc.UITransform).setContentSize(w,h);l.node.setPosition(x,y,0);};
    layoutPanel=()=>{
      const lines=Math.max(1,String(detail.string || '').split('\n').length);
      const detailHeight=lines*detail.lineHeight+8,nextHeight=32+detailHeight+34+52;
      if(nextHeight!==height){
        height=nextHeight;panel.getComponent(cc.UITransform).setContentSize(width,height);
        graph.clear();graph.fillColor=new cc.Color(24,30,42,235);graph.roundRect(-width/2,-height/2,width,height,10);graph.fill();
      }
      setBounds(title,width-24,32,0,height/2-28);
      setBounds(detail,width-32,detailHeight,0,height/2-52-detailHeight/2);
      exit.setPosition(0,-height/2+29,0);
      exit.getComponent(cc.UITransform).setContentSize(200,34);
      const buttonGraph=exit.getComponent(cc.Graphics);
      if(!exit.__overlayWide){buttonGraph.clear();buttonGraph.fillColor=new cc.Color(166,57,57,255);buttonGraph.roundRect(-100,-17,200,34,10);buttonGraph.fill();exit.__overlayWide=true;}
      setBounds(exitLabel,180,30,0,0);place();
    };
    const events=cc.Node.EventType;
    title.node.on(events.TOUCH_MOVE,event=>{
      const delta=event.getUIDelta();position.x+=delta.x;position.y+=delta.y;place();
      event.propagationStopped=true;
    });
    exit.on(events.TOUCH_END,event=>{event.propagationStopped=true;stop();});
  }
  function wrapText(value,width,size){
    return String(value).split('\n').map(line=>{
      let result='',used=0;
      for(const ch of line){
        const advance=size*(ch.codePointAt(0)>255?1:0.65);
        if(used && used+advance>width){result+='\n';used=0;}
        result+=ch;used+=advance;
      }
      return result;
    }).join('\n');
  }
  function setText(label,value) {
    const bounds=labelSizes.get(label);
    if(label===detail)value=wrapText(value,bounds.width-8,label.fontSize);
    if(label.string!==value){label.string=value;label.node.getComponent(cc.UITransform).setContentSize(bounds.width,bounds.height);}
  }
  function render() {
    if(!data.active){remove();return;}
    if(g.__e0e1GameOverlaysEnabled===false){unmount();return;}
    mount();if(!valid(panel))return;
    const stopping=stopRequested || data.phase==='stopping';
    setText(title,stopping?'正在退出托管':data.phase==='waiting'?'正在等待 · 托管正常':data.phase==='paused'?'托管已暂停':'正在托管 · 可拖动');
    if(!stopping && data.phase==='waiting') {
      const seconds=Number.isFinite(data.next_check_at)?Math.max(0,Math.ceil((data.next_check_at-Date.now())/1000)):null;
      const duration=seconds===null?'':seconds===0?'即将检查':
        `${Math.floor(seconds/3600)?Math.floor(seconds/3600)+'小时':''}${Math.floor(seconds%3600/60)?Math.floor(seconds%3600/60)+'分':''}${seconds%60}秒后检查`;
      setText(detail,data.next_task?`下次：${data.next_task}\n${duration}`:(data.status || '暂无启用的定时任务'));
    } else {
      setText(detail,[data.task || (stopping?'正在安全收尾':'当前任务'),operation || data.status || '正在扫描待执行任务'].join('\n'));
    }
    setText(exitLabel,stopRequested?'正在安全收尾…':'退出托管');
    layoutPanel();
  }
  const api={snapshot,
    resourceStatus:()=>({active:!!data.active,timer:timer!==null,panel:valid(panel)}),
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
