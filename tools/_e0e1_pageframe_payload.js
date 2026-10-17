window.__e0e1__ = { ts: Date.now(), stage: 'doc-start' };
(function () {
  var TAG = '__e0e1__';
  function note(k, v) {
    try { localStorage.setItem(TAG + '_' + k, String(v)); } catch (e) {}
    try { if (window.tt && window.tt.setStorageSync) window.tt.setStorageSync(TAG + '_' + k, String(v)); } catch (e) {}
  }
  note('loc', location.href);
  note('ua', navigator.userAgent);
  note('hasRequire', typeof require);
  note('hasNodeProcess', typeof process);
  note('keys', Object.keys(window).length);

  // channel A: network beacons (may be blocked by PNA)
  (function () {
    var u = 'http://127.0.0.1:9999/PF?loc=' + encodeURIComponent(location.href) + '&ts=' + Date.now();
    try { fetch(u); } catch (e) {}
    try { var x = new XMLHttpRequest(); x.open('GET', u, true); x.send(); } catch (e) {}
    try { new Image().src = u; } catch (e) {}
  })();

  // channel B: game's own storage bridge -> disk (no network needed)
  var n = 0;
  var iv = setInterval(function () {
    n++;
    try {
      note('tick' + n, JSON.stringify({
        t: n,
        tt: typeof window.tt,
        canvas: typeof window.canvas,
        System: typeof window.System,
        keys: Object.keys(window).length
      }));
      if (window.tt && window.tt.setStorageSync) {
        note('tt_ready_tick', n);
        clearInterval(iv);
      }
    } catch (e) { note('tickErr', String(e)); }
    if (n > 60) clearInterval(iv);
  }, 500);

  // channel C: visible title change
  try { document.title = 'E0E1_' + Date.now(); } catch (e) {}
})();
