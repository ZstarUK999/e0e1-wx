// Read-only profile for Weixin 4.1.15.55 x64. No hooks, clicks, native Qt calls or writes.
function pointerPattern(p) {
  return p.toString().slice(2).padStart(16, '0').match(/../g).reverse().join(' ');
}
function className(object) {
  let code = object.readPointer().readPointer();
  for (let i = 0; i < 20; i++) {
    const instruction = Instruction.parse(code);
    if (instruction.mnemonic === 'lea' && instruction.opStr.startsWith('rax, [rip')) {
      const meta = instruction.next.add(instruction.operands[1].value.disp);
      const strings = meta.add(8).readPointer();
      return strings.add(strings.add(16).readS64().toNumber()).readCString();
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
function mainWindow(module) {
  // Confirm the profile by validating the function's static meta-object, not just an RVA.
  const vtables = [0x9369b78, 0x983bf88];
  const found = new Map();
  let scanned = 0;
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
              className(hit.address) === 'mmui::MainWindow') found.set(hit.address.toString(), hit.address);
        } catch (_) {}
      }
    }
  }
  if (found.size !== 1) throw Error('Expected one live MainWindow; found ' + found.size);
  return [...found.values()][0];
}
let cachedRoot = null;
rpc.exports.snapshot = function () {
  const module = Process.getModuleByName('Weixin.dll');
  if (!/[\\/]4\.1\.15\.55[\\/]/.test(module.path) || Process.arch !== 'x64' || module.size !== 204795904)
    throw Error('Unsupported Weixin build; profile requires validation');
  const root = cachedRoot || mainWindow(module);
  if(className(root)!=='mmui::MainWindow')throw Error('Cached root is no longer valid');
  cachedRoot=root;
  const rootRect = rectangle(root);
  const hwnd = root.add(40).readPointer().readPointer();
  const user = Process.getModuleByName('user32.dll');
  const getRect = new NativeFunction(user.getExportByName('GetClientRect'), 'int', ['pointer','pointer']);
  const toScreen = new NativeFunction(user.getExportByName('ClientToScreen'), 'int', ['pointer','pointer']);
  const isWindow = new NativeFunction(user.getExportByName('IsWindow'), 'int', ['pointer']);
  const physical = Memory.alloc(16), origin = Memory.alloc(8);origin.writeU64(0);
  if (!isWindow(hwnd) || !getRect(hwnd,physical) || !toScreen(hwnd,origin)) throw Error('Main window geometry unavailable');
  const scaleX = physical.add(8).readS32() / rootRect.width;
  const scaleY = physical.add(12).readS32() / rootRect.height;
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
      if (visible && ['mmui::XTabBarItem','mmui::XButton','mmui::XTextView'].includes(type)) {
        let label = null;try { label = qstring(data.add(200).readPointer()); } catch (_) {}
        if(!label && type==='mmui::XTextView')for(let offset=64;offset<512;offset+=8){
          try{const text=qstring(object.add(offset).readPointer());if(text==='小程序'){label=text;break;}}catch(_){}
        }
        if (label && ['发现','小程序','最近使用','微信','更多'].includes(label)) {
          const rect = rectangle(object);
          controls.push({type,label,object:object.toString(),localRect:rect,
            screenCenter:{x:Math.round(origin.readS32()+(x+rect.width/2)*scaleX),
              y:Math.round(origin.add(4).readS32()+(y+rect.height/2)*scaleY)}});
        }
      }
      // Before finding the sidebar, traverse only the known main-window container path.
      if (/Chat|Contact|Session|Message|Icon|Image|Badge|Timer|Animation/.test(type || '')) return;
      for (const child of children(object)) visit(child,depth+1,x,y,sidebar,visible);
    } catch (error) { if (/budget/.test(String(error))) throw error; }
  }
  // Root coordinates are screen placement; descendants are relative to its client origin.
  for (const child of children(root)) visit(child,1,0,0,false,true);
  return {pid:Process.id,version:'4.1.15.55',readOnly:true,root:root.toString(),hwnd:hwnd.toString(),scaleX,scaleY,origin:{x:origin.readS32(),y:origin.add(4).readS32()},clientSize:{width:physical.add(8).readS32(),height:physical.add(12).readS32()},controls};
};
