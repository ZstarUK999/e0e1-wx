/* ===== e0e1 probe2 (appended) ===== */
;(function () {
  function d(v) { try { return String(v); } catch (e) { return 'ERR'; } }
  var parts = [];
  function p(k, v) { parts.push(k + '=' + encodeURIComponent(d(v))); }
  try {
    p('ts', Date.now());
    p('loc', typeof location !== 'undefined' ? location.href : 'na');
    p('isWorker', typeof WorkerGlobalScope !== 'undefined' && typeof self !== 'undefined' && self instanceof WorkerGlobalScope);
    p('hasWindow', typeof window !== 'undefined');
    p('hasDocument', typeof document !== 'undefined');
    p('hasSelf', typeof self !== 'undefined');
    p('require', typeof require);
    p('localStorage', typeof localStorage);
    p('tt', typeof (typeof window !== 'undefined' ? window.tt : (typeof tt !== 'undefined' ? tt : undefined)));
    p('System', typeof (typeof window !== 'undefined' ? window.System : undefined));
    p('canvas', typeof (typeof window !== 'undefined' ? window.canvas : undefined));
    p('importScripts', typeof importScripts);
    p('fetch', typeof fetch);
    p('XMLHttpRequest', typeof XMLHttpRequest);
    try { p('selfKeys', Object.keys(self).length); } catch (e) { p('selfKeys', 'ERR'); }
  } catch (e) { parts.push('FATAL=' + encodeURIComponent(d(e))); }
  var url = 'http://127.0.0.1:9999/probe?' + parts.join('&');
  try { fetch(url); } catch (e) {}
  try { if (typeof XMLHttpRequest !== 'undefined') { var x = new XMLHttpRequest(); x.open('GET', url, true); x.send(); } } catch (e) {}
  try { var i = new Image(); i.src = url; } catch (e) {}
})();
/* ===== end e0e1 probe2 ===== */
