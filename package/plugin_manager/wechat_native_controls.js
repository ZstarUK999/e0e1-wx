// Read-only Qt metadata discovery; no Weixin version or fixed module RVA dependency. No hooks, clicks, native Qt calls or writes.
function probeTrace(phase,details) {
  if(typeof send==='function')send({type:'wechat-native-probe',phase,...details});
}
function pointerPattern(p) {
  return p.toString().slice(2).padStart(16, '0').match(/../g).reverse().join(' ');
}
function className(object) {
  let code = object.readPointer().readPointer();
  for (let i = 0; i < 20; i++) {
    const instruction = Instruction.parse(code);
    if (instruction.mnemonic === 'lea' && instruction.opStr.startsWith('rax, [rip')) {
      const meta = instruction.next.add(instruction.operands[1].value.disp);
      return metadataName(meta);
    }
    if (instruction.mnemonic === 'ret') break;
    code = instruction.next;
  }
  return null;
}
function qstring(header) {
  const size = header.add(4).readS32(), offset = header.add(16).readS64().toNumber();
  if (size < 1 || size > 100 || offset < 24 || offset > 4096) return null;
  return header.add(offset).readUtf16String(size);
}
function controlLabel(object,data,type) {
  let label=null;
  try {label=qstring(data.add(200).readPointer());}catch(_){}
  // Discover renders its text inside the cell's private data instead of a
  // separate XTextView. Search bounded fields, without a build-specific RVA.
  if(!label && ['mmui::XTextView','mmui::ExtensionDiscoverContentCell'].includes(type))
    for(const base of [data,object])for(let offset=64;offset<512;offset+=8) {
      try {if(qstring(base.add(offset).readPointer())==='小程序')return '小程序';}catch(_){}
    }
  return label;
}
function children(object) {
  const data = object.add(8).readPointer();
  if (!data.add(8).readPointer().equals(object)) throw Error('QObject ownership mismatch');
  const list = data.add(24).readPointer();
  if (list.isNull()) return [];
  const begin = list.add(8).readS32(), end = list.add(12).readS32();
  if (begin < 0 || end < begin || end - begin > 2000) throw Error('Invalid child list');
  return Array.from({length: end - begin}, (_, i) => list.add(16 + (begin + i) * 8).readPointer());
}
function rectangle(object) {
  const data = object.add(40).readPointer();
  const a = Array.from(new Int32Array(data.add(20).readByteArray(16)));
  if (a[2] < a[0] || a[3] < a[1] || a[2] - a[0] > 30000 || a[3] - a[1] > 30000)
    throw Error('Invalid QWidget rectangle');
  return {x: a[0], y: a[1], width: a[2] - a[0] + 1, height: a[3] - a[1] + 1};
}
function scanModule(module, pattern, protection='r--') {
  const hits=[];
  for(const range of module.enumerateRanges(protection)) {
    try { for(const hit of Memory.scanSync(range.base,range.size,pattern))hits.push(hit); } catch(_) {}
  }
  return hits;
}
function executable(pointer) {
  const range=Process.findRangeByAddress(pointer);
  return !!range && range.protection.includes('x');
}
function metadataName(meta) {
  const strings=meta.add(8).readPointer();
  const size=strings.add(4).readS32(),offset=strings.add(16).readS64().toNumber();
  if(!Number.isSafeInteger(offset) || size<1 || size>256 || offset<24 || offset>1024*1024)
    throw Error('Invalid Qt class-name header');
  return strings.add(offset).readCString(size);
}
function mainVtable(module,rva) {
  try {
    if(!Number.isSafeInteger(rva) || rva<0 || rva+24>=module.size)return false;
    const table=module.base.add(rva);
    if(![0,8,16].every(offset=>executable(table.add(offset).readPointer())))return false;
    const holder=Memory.alloc(Process.pointerSize);holder.writePointer(table);
    return className(holder) === 'mmui::MainWindow';
  } catch(_) { return false; }
}
function layoutFingerprint(module) {
  return module.size+':'+Checksum.compute('sha256',module.base.readByteArray(4096));
}
function discoverVtables(module) {
  const name='mmui::MainWindow';
  const pattern=Array.from(name).map(c=>c.charCodeAt(0).toString(16)).join(' ')+' 00';
  probeTrace('metadata-scan',{moduleSize:module.size});
  const names=scanModule(module,pattern);
  if(names.length>16)throw Error('Qt主窗口类型候选过多，结构尚未确认');
  const metas=new Set();
  for(const hit of names) {
    // Qt's relative string header points back to its own class name.
    for(let distance=24;distance<16384;distance+=8) {
      try {
        const header=hit.address.sub(distance);
        if(header.readS32()!==-1 || header.add(4).readS32()!==name.length ||
           header.add(16).readS64().toNumber()!==distance)continue;
        for(const ref of scanModule(module,pointerPattern(header))) {
          const meta=ref.address.sub(8),data=meta.add(16).readPointer();
          if(metadataName(meta)===name && data.readU32()>0 && data.readU32()<32 &&
             executable(meta.add(24).readPointer()))metas.add(meta.toString());
        }
      } catch(_) {}
    }
  }
  if(!metas.size)throw Error('未找到可校验的Qt主窗口元数据，等待窗口就绪或检查控件结构');
  const functions=new Set();
  for(const hit of scanModule(module,'48 8d 05','r-x')) {
    try {
      const target=hit.address.add(7).add(hit.address.add(3).readS32());
      if(!metas.has(target.toString()) || Instruction.parse(hit.address.add(7)).mnemonic!=='ret')continue;
      // Find the preceding function boundary, then verify instruction boundaries.
      // No absolute address or release-specific displacement is assumed.
      for(let distance=0;distance<=96;distance++) {
        const start=hit.address.sub(distance);
        if(distance!==0 && start.sub(1).readU8()!==0xcc)continue;
        let pc=start;
        for(let i=0;i<32 && pc.compare(hit.address)<=0;i++) {
          if(pc.equals(hit.address)){functions.add(start.toString());break;}
          const instruction=Instruction.parse(pc);
          if(['ret','int3','jmp'].includes(instruction.mnemonic))break;
          pc=instruction.next;
        }
      }
    } catch(_) {}
  }
  const tables=new Set();
  for(const address of functions)for(const ref of scanModule(module,pointerPattern(ptr(address)))) {
    const rva=ref.address.sub(module.base).toInt32();
    if(mainVtable(module,rva))tables.add(rva);
  }
  if(!tables.size || tables.size>16)throw Error('Qt主窗口虚表自动定位未通过结构校验');
  return [...tables];
}
function profileFor(module,saved) {
  if(Process.arch!=='x64')throw Error('当前Qt控件读取仅支持x64架构：'+Process.arch);
  const fingerprint=layoutFingerprint(module);
  const valid=saved && saved.fingerprint===fingerprint && Array.isArray(saved.vtables) &&
    saved.vtables.length>0 && saved.vtables.length<=16 && saved.vtables.every(rva=>mainVtable(module,rva));
  const version=module.path.split(/[\\/]/).slice(-2,-1)[0] || 'unknown';
  return {fingerprint,version,cached:!!valid,vtables:valid?saved.vtables:discoverVtables(module)};
}
function mainWindow(module, profile, ownedHwnd) {
  // Confirm the profile by validating the function's static meta-object, not just an RVA.
  const vtables = profile.vtables;
  const found = new Map();
  let scanned = 0;
  probeTrace('root-scan',{});
  for (const range of Process.enumerateRanges('rw-')) {
    if (range.file || range.size > 64 * 1024 * 1024) continue;
    scanned += range.size;
    if (scanned > 768 * 1024 * 1024) throw Error('Probe memory budget exceeded');
    for (const rva of vtables) {
      let hits;
      try { hits = Memory.scanSync(range.base, range.size, pointerPattern(module.base.add(rva))); }
      catch (_) { continue; }
      for (const hit of hits) {
        try {
          const data = hit.address.add(8).readPointer();
          if (data.add(8).readPointer().equals(hit.address) && data.add(16).readPointer().isNull() &&
              className(hit.address) === 'mmui::MainWindow' && hit.address.add(40).readPointer().readPointer().equals(ownedHwnd)) found.set(hit.address.toString(), hit.address);
        } catch (_) {}
      }
    }
  }
  if (found.size !== 1) throw Error('Expected one live MainWindow; found ' + found.size);
  probeTrace('root-found',{scanned});
  return [...found.values()][0];
}
let cachedRoot = null;
rpc.exports.snapshot = function (savedLayout, geometry) {
  if(!geometry || !geometry.hwnd || !geometry.origin || !geometry.clientSize || !Number.isFinite(geometry.scale))
    throw Error('Verified host window geometry is required');
  const ownedHwnd=ptr(geometry.hwnd);
  probeTrace('snapshot-start',{});
  const module = Process.getModuleByName('Weixin.dll');
  let profile=profileFor(module,savedLayout);
  let root=cachedRoot;
  if(root) {
    try {
      if(className(root)!=='mmui::MainWindow' || !root.add(40).readPointer().readPointer().equals(ownedHwnd))root=null;
    } catch(_) {root=null;}
    cachedRoot=root;
  }
  if(!root) {
    try {root=mainWindow(module,profile,ownedHwnd);}
    catch(error) {
      if(!profile.cached)throw error;
      profile=profileFor(module,null);
      root=mainWindow(module,profile,ownedHwnd);
    }
  }
  if(className(root)!=='mmui::MainWindow')throw Error('Cached root is no longer valid');
  cachedRoot=root;
  const rootRect = rectangle(root);
  const hwnd = root.add(40).readPointer().readPointer();
  if(!hwnd.equals(ownedHwnd))throw Error('Main window ownership changed');
  const scaleX = geometry.clientSize.width / rootRect.width;
  const scaleY = geometry.clientSize.height / rootRect.height;
  const expectedScale=geometry.scale;
  if(!Number.isFinite(scaleX) || !Number.isFinite(scaleY) || scaleX<0.5 || scaleX>4 ||
     Math.abs(scaleX-scaleY)>0.02 || Math.abs(scaleX-expectedScale)>0.02)
    throw Error('Qt控件几何结构与实际窗口DPI不一致，停止点击');
  probeTrace('control-traversal',{});
  const controls = [], seen = new Set();let visited = 0;
  function visit(object, depth, x, y, sidebar, visible) {
    if (depth > 22 || seen.has(object.toString())) return;
    if (++visited > 2000) throw Error('Control traversal budget exceeded');
    seen.add(object.toString());
    try {
      const data = object.add(8).readPointer(), type = className(object);
      const widget = !!(data.add(32).readU32() & 1);
      if (widget) { const rect = rectangle(object); x += rect.x; y += rect.y;
        visible=visible && !!(object.add(40).readPointer().add(8).readU32() & 0x8000); }
      sidebar = sidebar || type === 'mmui::MainTabBar';
      if (visible && ['mmui::XTabBarItem','mmui::XButton','mmui::XTextView','mmui::ExtensionDiscoverContentCell'].includes(type)) {
        const label=controlLabel(object,data,type);
        if (label && ['发现','小程序','最近使用','微信','更多'].includes(label)) {
          const rect = rectangle(object);
          controls.push({type,label,object:object.toString(),localRect:rect,
            screenCenter:{x:Math.round(geometry.origin.x+(x+rect.width/2)*scaleX),
              y:Math.round(geometry.origin.y+(y+rect.height/2)*scaleY)}});
        }
      }
      // Before finding the sidebar, traverse only the known main-window container path.
      if (/Chat|Contact|Session|Message|Icon|Image|Badge|Timer|Animation/.test(type || '')) return;
      for (const child of children(object)) visit(child,depth+1,x,y,sidebar,visible);
    } catch (error) { if (/budget/.test(String(error))) throw error; }
  }
  // Root coordinates are screen placement; descendants are relative to its client origin.
  for (const child of children(root)) visit(child,1,0,0,false,true);
  probeTrace('snapshot-complete',{visited,controls:controls.length});
  return {pid:Process.id,version:profile.version,layout:{fingerprint:profile.fingerprint,vtables:profile.vtables},layoutCached:profile.cached,readOnly:true,root:root.toString(),hwnd:hwnd.toString(),scaleX,scaleY,origin:{x:geometry.origin.x,y:geometry.origin.y},clientSize:geometry.clientSize,controls};
};
