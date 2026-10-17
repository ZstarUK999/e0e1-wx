/* ===== e0e1 probe (appended by e0e1-wx, removable) ===== */
;(function () {
  var fs = null;
  try { fs = require('fs'); } catch (e) {}
  var OUT = 'C:/Users/AshenZhou/AppData/Local/Temp/e0e1_douyin_probe.txt';
  var lines = [];
  function log(s) { lines.push(String(s)); try { fs && fs.writeFileSync(OUT, lines.join('\n')); } catch (e) {} }
  try {
    log('TS=' + new Date().toISOString());
    log('pid=' + (typeof process !== 'undefined' ? process.pid : 'n/a'));
    log('location=' + (typeof location !== 'undefined' ? location.href : 'n/a'));
    log('has_require=' + (typeof require === 'function'));
    log('has_fs=' + !!fs);
    log('self===window=' + (typeof window !== 'undefined' && self === window));
    var names = [];
    try { for (var k in window) names.push(k); } catch (e) {}
    log('window_keys=' + names.length);
    ['tt', 'define', 'require', 'System', 'canvas', '__tt_define__', '__tt_require__', 'TMAConfig', 'GameGlobal', 'ttJSBridge', 'ttJSCore']
      .forEach(function (n) { log('  win.' + n + '=' + (typeof window[n])); });
    // watch for game runtime appearing later
    var t0 = Date.now();
    var iv = setInterval(function () {
      try {
        var w = window;
        log('tick@' + (Date.now() - t0) + 'ms tt=' + (typeof w.tt) + ' System=' + (typeof w.System) +
            ' canvas=' + (typeof w.canvas) + ' keys=' + Object.keys(w).length);
      } catch (e) { log('tick err ' + e); }
      if (Date.now() - t0 > 20000) clearInterval(iv);
    }, 2000);
  } catch (e) { log('FATAL ' + e); }
})();
/* ===== end e0e1 probe ===== */
