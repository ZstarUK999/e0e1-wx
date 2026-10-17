import io, os, shutil, sys

FS = r'C:/Users/AshenZhou/AppData/Roaming/douyin/microGameCache/resource/file-server.js'
BAK = FS + '.e0e1bak'

HOOK = r'''
;(function(){
  var fs=require('fs'), path=require('path');
  var LOG='C:/Users/AshenZhou/AppData/Local/Temp/e0e1_fs.log';
  var PAYLOAD='C:/Users/AshenZhou/AppData/Local/Temp/e0e1_payload.js';
  function w(s){try{fs.appendFileSync(LOG,s+'\n')}catch(e){}}
  globalThis.__E0E1__=function(root){
    w('=== server start root='+root+' pid='+process.pid);
    return function(req,res,next){
      var u=String(req.url||'').split('?')[0];
      w(new Date().toISOString()+' '+req.method+' '+req.url);
      if(u==='/__e0e1__.js'){
        res.setHeader('Content-Type','application/javascript');
        try{res.end(fs.readFileSync(PAYLOAD));}catch(e){res.end('/* no payload */');}
        return;
      }
      if(/\.html?$/i.test(u)){
        var rel=u.replace(/^\/+/,'');
        if(rel.indexOf('resource/')===0) rel=rel.slice('resource/'.length);
        var f=path.join(root,rel);
        try{
          var html=fs.readFileSync(f,'utf8');
          var tag='<script src="/__e0e1__.js"></script>';
          if(/<\/head>/i.test(html)) html=html.replace(/<\/head>/i,tag+'</head>');
          else html=tag+html;
          res.setHeader('Content-Type','text/html; charset=utf-8');
          res.end(html); w('    -> injected '+f); return;
        }catch(e){ w('    -> html fail '+f+' '+String(e && e.message)); }
      }
      next();
    };
  };
})();
'''.strip()

MARKER = 'globalThis.__E0E1__'
MOUNT = 's.use("/resource",o.default.static(e))'
NEW_MOUNT = 's.use(globalThis.__E0E1__(e)),' + MOUNT

s = io.open(FS, encoding='utf-8').read()

if MARKER in s:
    print('already patched')
    sys.exit(0)

if not os.path.exists(BAK):
    shutil.copy2(FS, BAK)

if MOUNT not in s:
    print('MOUNT not found - abort')
    sys.exit(1)

s = s.replace(MOUNT, NEW_MOUNT, 1)
if s.startswith('/*!'):
    i = s.find('*/') + 2
    s = s[:i] + '\n' + HOOK + '\n' + s[i:]
else:
    s = HOOK + '\n' + s

io.open(FS, 'w', encoding='utf-8').write(s)
print('patched', len(s))
