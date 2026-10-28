const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../package/plugin_manager/wechat_native_controls.js'),'utf8');
function context(){const ctx={rpc:{exports:{}},Process:{arch:'x64'}};vm.createContext(ctx);vm.runInContext(code,ctx);return ctx;}
function profileFixture(){
  const ctx=context();ctx.scans=0;
  vm.runInContext(`layoutFingerprint=module=>module.fingerprint;
    mainVtable=(module,rva)=>rva===1234;
    discoverVtables=module=>{scans++;return [1234];};`,ctx);
  return ctx;
}
test('unlisted version and arbitrary module size use metadata discovery',()=>{
  const ctx=profileFixture();
  const result=ctx.profileFor({path:'C:/Weixin/99.12.999.777/Weixin.dll',size:999999,fingerprint:'new-build'});
  assert.equal(result.version,'99.12.999.777');assert.equal(result.cached,false);assert.equal(ctx.scans,1);
  assert.deepEqual(Array.from(result.vtables),[1234]);
});
test('unchanged fingerprint reuses a structurally valid layout',()=>{
  const ctx=profileFixture();
  const result=ctx.profileFor({path:'C:/anything/Weixin.dll',fingerprint:'same'},
    {fingerprint:'same',vtables:[1234]});
  assert.equal(result.cached,true);assert.equal(ctx.scans,0);
});
test('updated module or corrupt virtual table triggers rediscovery',()=>{
  const ctx=profileFixture(),module={path:'C:/Weixin.dll',fingerprint:'new'};
  assert.equal(ctx.profileFor(module,{fingerprint:'old',vtables:[1234]}).cached,false);
  assert.equal(ctx.profileFor(module,{fingerprint:'new',vtables:[999]}).cached,false);
  assert.equal(ctx.scans,2);
});
test('a different architecture is rejected before native structure reads',()=>{
  const ctx=profileFixture();ctx.Process.arch='ia32';
  assert.throws(()=>ctx.profileFor({}),/x64/);assert.equal(ctx.scans,0);
});
test('discovery follows relocated Qt metadata and code references',()=>{
  const ctx=context();
  vm.runInContext(`
    const base=0x10000000,name=base+0x8000,header=name-120,meta=base+0x9000,
      data=base+0x9500,callback=base+0x3000,fn=base+0x2000,lea=fn+15,table=base+0xa000;
    class P {
      constructor(n){this.n=n;}add(n){return new P(this.n+Number(n));}sub(n){return new P(this.n-(n instanceof P?n.n:n));}
      equals(p){return this.n===p.n;}compare(p){return this.n-p.n;}toInt32(){return this.n|0;}
      toString(){return '0x'+this.n.toString(16);}
      readS32(){if(this.n===header)return -1;if(this.n===header+4)return 16;
        if(this.n===lea+3)return meta-(lea+7);return 0;}
      readU32(){return this.n===data?8:0;}
      readU8(){return this.n===fn-1?0xcc:0;}
      readS64(){return {toNumber:()=>this.n===header+16?120:0};}
      readPointer(){if(this.n===meta+16)return new P(data);if(this.n===meta+24)return new P(callback);throw Error('unmapped');}
    }
    ptr=value=>new P(Number(value));
    metadataName=p=>'mmui::MainWindow';executable=p=>p.n===callback;
    mainVtable=(module,rva)=>rva===table-base;
    scanModule=(module,pattern)=>{
      if(pattern.startsWith('6d 6d'))return [{address:new P(name)}];
      if(pattern===pointerPattern(new P(header)))return [{address:new P(meta+8)}];
      if(pattern==='48 8d 05')return [{address:new P(lea)}];
      if(pattern===pointerPattern(new P(fn)))return [{address:new P(table)}];return [];
    };
    Instruction={parse(p){const lengths=new Map([[fn,4],[fn+4,5],[fn+9,6],[lea,7],[lea+7,1]]);
      if(!lengths.has(p.n))throw Error('invalid instruction');
      return {mnemonic:p.n===lea+7?'ret':p.n===lea?'lea':'mov',next:p.add(lengths.get(p.n))};}};
    this.discovered=discoverVtables({base:new P(base),size:0x10000});
  `,ctx);
  assert.deepEqual(Array.from(ctx.discovered),[0xa000]);
});


test('Qt class names use bounded reads and reject corrupt headers before reading strings',()=>{
  const ctx=context();
  vm.runInContext(`
    let size=16,offset=24;this.reads=[];
    const text={readCString(n){reads.push(n);return 'mmui::MainWindow';}};
    const strings={add(n){if(n===4)return {readS32:()=>size};
      if(n===16)return {readS64:()=>({toNumber:()=>offset})};
      if(n===offset)return text;throw Error('unexpected offset');}};
    this.meta={add(){return {readPointer:()=>strings};}};
    this.setHeader=(n,o)=>{size=n;offset=o;};
  `,ctx);
  assert.equal(ctx.metadataName(ctx.meta),'mmui::MainWindow');
  assert.deepEqual(Array.from(ctx.reads),[16]);
  for(const [size,offset] of [[0,24],[1000000,24],[16,-1],[16,2**40]]) {
    ctx.setHeader(size,offset);
    assert.throws(()=>ctx.metadataName(ctx.meta),/Invalid Qt/);
  }
  assert.equal(ctx.reads.length,1);
});


test('injected scanner never calls native functions and requires verified host geometry',()=>{
  assert(!code.includes('new NativeFunction'));
  const ctx=context();
  assert.throws(()=>ctx.rpc.exports.snapshot(null,null),/host window geometry/);
});


test('persistent script rediscovers a replaced window without reinjection',()=>{
  const ctx=context();
  vm.runInContext(`
    let scans=0;this.getScans=()=>scans;
    const hwnd={equals:()=>true,toString:()=> '0x10'};
    const root={add:()=>({readPointer:()=>({readPointer:()=>hwnd})})};
    cachedRoot={stale:true};ptr=()=>hwnd;
    className=obj=>{if(obj.stale)throw Error('freed');return 'mmui::MainWindow';};
    profileFor=()=>({version:'test',fingerprint:'x',vtables:[]});
    mainWindow=()=>{scans++;return root;};
    rectangle=()=>({width:100,height:100});children=()=>[];
    Process.getModuleByName=()=>({});
  `,ctx);
  const geometry={hwnd:'0x10',origin:{x:0,y:0},clientSize:{width:100,height:100},scale:1};
  ctx.rpc.exports.snapshot(null,geometry);
  ctx.rpc.exports.snapshot(null,geometry);
  assert.equal(ctx.getScans(),1);
});


test('Discover cell private text is recognized even without an XTextView child',()=>{
  const ctx=context();
  vm.runInContext(`
    const object={add:offset=>({readPointer:()=>({base:'object',offset})})};
    const data={add:offset=>({readPointer:()=>({base:'private',offset})})};
    qstring=p=>p.base==='private' && p.offset===232?'小程序':null;
    this.label=controlLabel(object,data,'mmui::ExtensionDiscoverContentCell');
  `,ctx);
  assert.equal(ctx.label,'小程序');
});
