const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const profile=JSON.parse(fs.readFileSync(path.join(__dirname,'config/androws/a66d9388ff0b6fbd79045551e9d5b22dadc460ebd1b5659733361921617e22f6.json'),'utf8'));
const source=fs.readFileSync(path.join(__dirname,'hook_androws.js'),'utf8').replace('@@CONFIG@@',JSON.stringify(profile));
function fixture(appid=profile.TargetAppId,wrongBytes=false) {
  const memory=new Map(), writes=[], hooks=[];
  const signatures=new Map([[0x25de1d0,'415741565657534881ec9001000089d3'],[0x2d8f6b0,'4157415641554154565755534881ecb8'],[0x92f39c0,'5657534881ec900100004889ce488b05']]);
  class Pointer {
    constructor(n){this.n=Number(n);}
    add(n){return new Pointer(this.n+Number(n));}
    readPointer(){if(!memory.has(this.n))throw Error('unmapped pointer');return new Pointer(memory.get(this.n));}
    readS8(){return memory.get(this.n)||0;}
    readU8(){return this.readS8();}
    readU32(){return memory.get(this.n)||0;}
    readInt(){return this.readU32();}
    readUtf8String(){return memory.get(this.n)||'';}
    readByteArray(){return Uint8Array.from(Buffer.from(wrongBytes?'00'.repeat(16):signatures.get(this.n),'hex')).buffer;}
    writeUtf8String(v){writes.push([this.n,v]);memory.set(this.n,v);}
    writeInt(v){writes.push([this.n,v]);memory.set(this.n,v);}
    writeU8(v){this.writeInt(v);}
    writeU64(v){this.writeInt(v);}
  }
  memory.set(1000+64,2000);memory.set(2000+1480,4000);memory.set(4000+8,5000);
  memory.set(5000+1416,7000);memory.set(7000+16,8000);memory.set(8000+456,1005);
  memory.set(2000+152,appid);memory.set(2000+152+23,appid.length);
  const context={rpc:{exports:{}},Process:{getModuleByName:()=>({path:'C:\\Tencent\\Androws\\WmpfRuntime\\v\\runtime\\flue.dll',base:new Pointer(0)})},
    ptr:n=>new Pointer(n),send:()=>{},NativeFunction:function(){return ()=>{};},NativeCallback:function(f){return f;},
    Interceptor:{attach:(p,h)=>{hooks.push(h);return {detach(){}};},replace(){},flush(){}}};
  vm.runInNewContext(source,context);
  return {context,memory,writes,hooks,Pointer};
}
{
  const f=fixture();assert.equal(f.context.rpc.exports.install(),true);
  const args=[new f.Pointer(1000),new f.Pointer(0)];f.hooks[0].onEnter(args);
  assert.equal(args[1].n,1);
  assert.equal(f.memory.get(8456),1101);
  assert.equal(f.memory.get(5600),'ws://127.0.0.1:9422');
  assert.deepEqual(f.writes.map(w=>w[0]),[5600,5623,8456]);
}
{
  const f=fixture('wx_other_game');f.context.rpc.exports.install();
  const args=[new f.Pointer(1000),new f.Pointer(0)];f.hooks[0].onEnter(args);
  assert.equal(args[1].n,0);assert.equal(f.writes.length,0);
}
{
  const f=fixture(profile.TargetAppId,true);
  assert.throws(()=>f.context.rpc.exports.install(),/指纹/);
  assert.equal(f.hooks.length,0);
}
console.log('Androws hook: target scope, field writes, fingerprint rejection passed');
