/* ===== e0e1 probe (appended) ===== */
;(function () {
  var info = {
    ts: new Date().toISOString(),
    loc: (typeof location !== 'undefined' ? location.href : 'n/a'),
    hasWindow: typeof window !== 'undefined',
    hasRequire: typeof require === 'function',
    keys: (function () { try { return Object.keys(window).length; } catch (e) { return -1; } })(),
    tt: typeof window.tt,
    System: typeof window.System,
    canvas: typeof window.canvas,
    GameGlobal: typeof window.GameGlobal
  };
  var s = JSON.stringify(info);
  try { require('fs').writeFileSync('C:/Users/AshenZhou/AppData/Local/Temp/e0e1_game_probe.txt', s); } catch (e) { info.fsErr = String(e); s = JSON.stringify(info); }
  try { localStorage.setItem('__e0e1_probe__', s); } catch (e) {}
  try { window.tt && window.tt.setStorageSync && window.tt.setStorageSync('__e0e1_probe__', s); } catch (e) {}
  try { document.title = 'E0E1_' + Date.now(); } catch (e) {}
})();
/* ===== end e0e1 probe ===== */
