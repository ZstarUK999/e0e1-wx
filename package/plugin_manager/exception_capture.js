// Passive observers: do not suppress errors or change promise handling.
(() => {
  const g=globalThis;
  if(g.__e0e1ExceptionCapture)return {installed:true,nativeError:g.__e0e1ExceptionCapture.nativeError,nativePromise:g.__e0e1ExceptionCapture.nativePromise};
  const seen=new Map(),detach=[];
  let windowStart=0,count=0;
  function field(obj,key){
    try {
      for(let cur=obj,n=0;cur && n<3;cur=Object.getPrototypeOf(cur),n++){
        const d=Object.getOwnPropertyDescriptor(cur,key);
        if(d)return 'value' in d?d.value:undefined;
      }
    }catch(_){}
  }
  function text(v){return typeof v==='string'?v.slice(0,8000):typeof v==='number'||typeof v==='boolean'?String(v):undefined;}
  function report(kind,value,meta){
    try{
      const out={kind,time:new Date().toISOString(),...meta};
      if(value!==null && (typeof value==='object'||typeof value==='function')){
        for(const key of ['name','message','errMsg','errno','code','status','reason','stack']){
          const v=text(field(value,key));if(v!==undefined)out[key]=v;
        }
        if(!Object.keys(out).some(k=>['message','errMsg','stack','code'].includes(k)))out.detail='Object without primitive error fields';
      }else out.message=text(value)||String(value);
      const signature=JSON.stringify({...out,time:undefined}),now=Date.now();
      if(seen.has(signature)&&now-seen.get(signature)<30000)return;
      if(now-windowStart>=30000){windowStart=now;count=0;}
      if(count>=20)return;
      if(seen.size>=100)seen.clear();seen.set(signature,now);count++;
      g.console.error('[plugin.exception]',JSON.stringify(out));
    }catch(_){}
  }
  const wx=g.wx;
  function native(on,off,cb){try{if(wx&&typeof wx[on]==='function'){wx[on](cb);detach.push(()=>{if(typeof wx[off]==='function')wx[off](cb);});return true;}}catch(_){}return false;}
  const nativeError=native('onError','offError',e=>report('wx.onError',e));
  const nativePromise=native('onUnhandledRejection','offUnhandledRejection',e=>report('wx.onUnhandledRejection',field(e,'reason')??e));
  if(typeof g.addEventListener==='function'){
    const error=e=>report('error',e.error||e.message,{file:e.filename,line:e.lineno,column:e.colno});
    const rejection=e=>report('unhandledrejection',e.reason);
    g.addEventListener('error',error);g.addEventListener('unhandledrejection',rejection);
    detach.push(()=>{g.removeEventListener('error',error);g.removeEventListener('unhandledrejection',rejection);});
  }
  g.__e0e1ExceptionCapture={nativeError,nativePromise,dispose(){for(const fn of detach){try{fn();}catch(_){}}seen.clear();delete g.__e0e1ExceptionCapture;}};
  g.console.info('[plugin.ui]','全局异常捕获已启用：微信错误='+nativeError+'；Promise='+nativePromise);
  return {installed:true,nativeError,nativePromise};
})()
