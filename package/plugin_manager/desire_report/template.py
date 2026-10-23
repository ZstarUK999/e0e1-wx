"""三尸合成报告模板；渲染时用 __PAYLOAD__ 占位符替换为 JSON。

图表是手写原生 JS 生成内联 SVG，不引第三方库，单文件离线可用。
样式与配色沿用 PVP 伤害报告那一套（CSS 变量 + 深浅色切换）。
"""

HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>三尸合成报告</title>
<style>
  .viz-root {
    color-scheme: light;
    --surface-1: #fcfcfb;
    --page: #f9f9f7;
    --text-primary: #0b0b0b;
    --text-secondary: #52514e;
    --text-muted: #898781;
    --grid: #e1e0d9;
    --axis: #c3c2b7;
    --border: rgba(11, 11, 11, 0.10);
    --series-1: #2a78d6;
    --series-2: #eb6834;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) .viz-root {
      color-scheme: dark;
      --surface-1: #1a1a19;
      --page: #0d0d0d;
      --text-primary: #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted: #898781;
      --grid: #2c2c2a;
      --axis: #383835;
      --border: rgba(255, 255, 255, 0.10);
      --series-1: #3987e5;
      --series-2: #d95926;
    }
  }
  :root[data-theme="dark"] .viz-root {
    color-scheme: dark;
    --surface-1: #1a1a19;
    --page: #0d0d0d;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted: #898781;
    --grid: #2c2c2a;
    --axis: #383835;
    --border: rgba(255, 255, 255, 0.10);
    --series-1: #3987e5;
    --series-2: #d95926;
  }

  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
    background: var(--page); color: var(--text-primary);
  }
  .viz-root { background: var(--page); color: var(--text-primary); padding: 28px 24px 56px; }
  .wrap { max-width: 1180px; margin: 0 auto; }

  .page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 20px; }
  h1 { font-size: 20px; font-weight: 600; margin: 0 0 4px; }
  .sub { margin: 0; font-size: 13px; color: var(--text-secondary); }
  .btn {
    font: inherit; font-size: 13px; padding: 6px 12px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--surface-1);
    color: var(--text-primary); cursor: pointer;
  }
  .btn:hover { background: var(--grid); }

  .stats { display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 12px; margin-bottom: 20px; }
  @media (max-width: 720px) { .stats { grid-template-columns: 1fr 1fr; } }
  .tile {
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px;
  }
  .tile .label { display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
  .tile .value { font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .tile.hero .value { font-size: 48px; line-height: 1.05; font-weight: 600; }
  .tile .hint { display: block; font-size: 12px; color: var(--text-muted); margin-top: 4px; }

  .card {
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
    padding: 18px; margin-bottom: 16px;
  }
  .card h2 { font-size: 15px; font-weight: 600; margin: 0 0 4px; }
  .card h3 { font-size: 13px; font-weight: 600; margin: 18px 0 6px; color: var(--text-secondary); }
  .card h3:first-of-type { margin-top: 4px; }
  .card .note { font-size: 12px; color: var(--text-secondary); margin: 0 0 12px; line-height: 1.6; }

  .filters {
    display: flex; flex-wrap: wrap; align-items: flex-end; gap: 12px 18px;
    padding: 12px 14px; margin: 12px 0;
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
  }
  .filters label { font-size: 13px; color: var(--text-secondary); display: inline-flex; flex-direction: column; gap: 6px; }
  .filters select, .filters input {
    font: inherit; font-size: 13px; padding: 4px 8px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--surface-1); color: var(--text-primary);
  }

  .plot { position: relative; margin-bottom: 6px; }
  svg { display: block; width: 100%; height: auto; }
  .grid-line { stroke: var(--grid); stroke-width: 1; }
  .axis-line { stroke: var(--axis); stroke-width: 1; }
  .tick-text { fill: var(--text-muted); font-size: 11px; font-variant-numeric: tabular-nums; }
  .bar { shape-rendering: crispEdges; }
  .bar-label { fill: var(--text-secondary); font-size: 11px; font-variant-numeric: tabular-nums; }
  .band-hit { fill: var(--text-primary); opacity: .07; pointer-events: none; }

  .tooltip {
    position: absolute; pointer-events: none; z-index: 5;
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 10px; font-size: 12px; min-width: 180px;
    box-shadow: 0 4px 14px rgba(0, 0, 0, .12);
  }
  .tooltip .tt-head { color: var(--text-secondary); font-size: 11px; margin-bottom: 6px; }
  .tooltip .tt-row { display: flex; align-items: center; gap: 8px; padding: 2px 0; }
  .tooltip .tt-key { width: 14px; height: 2px; border-radius: 1px; flex: none; }
  .tooltip .tt-val { font-weight: 600; font-variant-numeric: tabular-nums; margin-left: auto; color: var(--text-primary); }
  .tooltip .tt-name { color: var(--text-secondary); }

  .legend { display: flex; flex-wrap: wrap; gap: 6px 10px; margin-top: 10px; }
  .chip {
    display: inline-flex; align-items: center; gap: 7px; font-size: 12px;
    padding: 5px 10px; border: 1px solid var(--border); border-radius: 999px;
    color: var(--text-primary); background: var(--surface-1);
  }
  .chip .key { width: 14px; height: 10px; border-radius: 2px; flex: none; }
  .cap-note { margin: 10px 0 0; font-size: 12px; color: var(--text-secondary); line-height: 1.7; }

  table { border-collapse: collapse; width: 100%; font-size: 12px; }
  th, td { text-align: right; padding: 6px 8px; border-bottom: 1px solid var(--grid); font-variant-numeric: tabular-nums; }
  th:first-child, td:first-child { text-align: left; }
  thead th { color: var(--text-secondary); font-weight: 600; }
  .table-scroll { max-height: 420px; overflow: auto; }
  .empty { font-size: 12px; color: var(--text-muted); }
</style>
</head>
<body>
<div class="viz-root">
  <div class="wrap">
    <header class="page-head">
      <div>
        <h1>三尸合成报告</h1>
        <p class="sub" id="meta-sub"></p>
      </div>
      <button class="btn" id="theme-toggle" type="button">切换深浅色</button>
    </header>

    <div class="stats" id="stats"></div>

    <section class="card">
      <h2>三尸合成概率</h2>
      <p class="note">批次选择会同步筛选全部统计和图表；不选批次表示全部；可按时间顺序仅显示筛选结果的前 N 次合成，留空显示全部。日期统计在当前结果内计算。
        「配置表概率」是二合一在该材料品质上的理论成功率，读自游戏内的合成配置表。</p>

      <h3>1 · 总表</h3>
      <div id="table-total"></div>

      <h3>2 · 按种类</h3>
      <div id="table-kind"></div>

      <h3>3 · 按品质</h3>
      <div id="table-quality"></div>

      <h3>4 · 自由选择批次</h3>
      <div class="filters">
        <label>批次（可多选，Ctrl/Shift 或拖动）
          <select id="batch" multiple size="6"></select>
        </label>
        <label>显示前多少次合成<input id="attempt-limit" type="number" min="1" step="1" placeholder="全部" inputmode="numeric"></label>
        <button class="btn" id="batch-apply" type="button">应用</button>
      </div>
      <div id="table-batch"></div>

      <h3>5 · 选择日期范围</h3>
      <div class="filters">
        <label>起始日期<input type="date" id="date-from"></label>
        <label>结束日期<input type="date" id="date-to"></label>
        <button class="btn" id="date-apply" type="button">应用</button>
      </div>
      <div id="table-date"></div>
    </section>

    <section class="card">
      <h2>连续失败次数分布</h2>
      <p class="note">统计的是「连续失败了多少次才等到下一次成功」：每次成功结束一段，段内的失败次数就是横轴 k。
        末尾还没被成功终结的那一段是截断观测，不计入分布，单独标注。</p>
      <div class="filters">
        <label>理论成功率 p（%）
          <input type="number" id="p-input" min="0.1" max="100" step="0.1" value="30">
        </label>
        <span class="sub" id="p-hint"></span>
      </div>
      <div class="plot">
        <svg id="svg-hist" role="img" aria-label="连续失败次数分布直方图"></svg>
        <div class="tooltip" id="tip-hist" hidden></div>
      </div>
      <div class="legend">
        <span class="chip"><span class="key" style="background:var(--series-1)"></span>实测</span>
        <span class="chip"><span class="key" style="background:var(--series-2);opacity:.4"></span>理论（二项式）</span>
      </div>
      <p class="cap-note" id="hist-cap"></p>
    </section>
  </div>
</div>
<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("payload").textContent);
  var ALL_RECORDS = DATA.records || [];
  var RECORDS = ALL_RECORDS.slice();
  var COLS = [
    { k: "name", t: "" }, { k: "n", t: "合成次数" }, { k: "ok", t: "成功" }, { k: "fail", t: "失败" },
    { k: "rate", t: "成功率" }, { k: "avg", t: "平均连续失败" }, { k: "max", t: "最长连续失败" },
    { k: "cfg", t: "配置表概率" }
  ];

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }
  function svgEl(tag, attrs) {
    var e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }
  function pct(v) { return (v * 100).toFixed(1) + "%"; }

  // ── 统计 ──
  // rows 必须是原始时间顺序。每次成功结束一段，段内失败数进 gaps；末尾未结束的一段单独返回。
  function gapsOf(rows) {
    var gaps = [], run = 0;
    rows.forEach(function (r) { if (r.ok) { gaps.push(run); run = 0; } else { run += 1; } });
    return { gaps: gaps, trailing: run };
  }
  function summarize(rows) {
    var n = rows.length, ok = 0;
    rows.forEach(function (r) { if (r.ok) ok += 1; });
    var g = gapsOf(rows).gaps;
    var sum = g.reduce(function (a, b) { return a + b; }, 0);
    return { n: n, ok: ok, fail: n - ok, rate: n ? ok / n : 0,
             avg: g.length ? sum / g.length : 0, max: g.length ? Math.max.apply(null, g) : 0, trailing: gapsOf(rows).trailing };
  }
  function cfgOf(quality) {
    var v = (DATA.cfg_ratio || {})[String(quality)];
    return (v === undefined || v === null) ? null : v;
  }
  function rowFor(name, rows, quality) {
    var s = summarize(rows);
    return { name: name, n: s.n, ok: s.ok, fail: s.fail, rate: s.rate, avg: s.avg, max: s.max,
             cfg: quality === undefined ? null : cfgOf(quality) };
  }

  function renderTable(host, rows) {
    host.innerHTML = "";
    if (!rows || !rows.length) { host.appendChild(el("p", "empty", "没有符合条件的记录")); return; }
    var wrap = el("div", "table-scroll"), table = document.createElement("table");
    var thead = document.createElement("thead"), head = document.createElement("tr");
    COLS.forEach(function (c) { head.appendChild(el("th", null, c.t)); });
    thead.appendChild(head); table.appendChild(thead);
    var tbody = document.createElement("tbody");
    rows.forEach(function (r) {
      var line = document.createElement("tr");
      COLS.forEach(function (c) {
        var td = document.createElement("td");
        if (c.k === "name") td.textContent = r.name;
        else if (c.k === "rate") td.textContent = r.n ? pct(r.rate) : "—";
        else if (c.k === "avg") td.textContent = r.n ? r.avg.toFixed(2) : "—";
        else if (c.k === "cfg") td.textContent = (r.cfg === null) ? "—" : (r.cfg.toFixed(1) + "%");
        else td.textContent = r[c.k];
        line.appendChild(td);
      });
      tbody.appendChild(line);
    });
    table.appendChild(tbody); wrap.appendChild(table); host.appendChild(wrap);
  }

  // ── 柱状图（手写内联 SVG，纵轴从 0 起）──
  function drawBars(svg, tip, series, opts) {
    opts = opts || {};
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var W = 1000, H = opts.height || 280, PAD = { t: 16, r: 24, b: 38, l: 60 };
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    var n = 0;
    series.forEach(function (s) { if (s.values.length > n) n = s.values.length; });
    if (!n) return;
    var maxV = 0;
    series.forEach(function (s) { s.values.forEach(function (v) { if (v > maxV) maxV = v; }); });
    if (!(maxV > 0)) maxV = 1;
    var plotW = W - PAD.l - PAD.r, plotH = H - PAD.t - PAD.b;
    var band = plotW / n, bw = Math.min(band * 0.36, 30);
    function xOf(k) { return PAD.l + k * band; }
    function yOf(v) { return PAD.t + plotH - (v / maxV) * plotH; }
    function baseY() { return PAD.t + plotH; }

    for (var g = 0; g <= 4; g++) {
      var v = (maxV / 4) * g, y = yOf(v);
      svg.appendChild(svgEl("line", { class: "grid-line", x1: PAD.l, x2: PAD.l + plotW, y1: y, y2: y }));
      var tk = svgEl("text", { class: "tick-text", x: PAD.l - 8, y: y + 4, "text-anchor": "end" });
      tk.textContent = String(Math.round(v * 10) / 10);
      svg.appendChild(tk);
    }
    svg.appendChild(svgEl("line", { class: "axis-line", x1: PAD.l, x2: PAD.l + plotW, y1: baseY(), y2: baseY() }));
    var step = Math.max(1, Math.ceil(n / 16));
    for (var k = 0; k < n; k += step) {
      var xt = svgEl("text", { class: "tick-text", x: xOf(k) + band / 2, y: baseY() + 16, "text-anchor": "middle" });
      xt.textContent = k;
      svg.appendChild(xt);
    }
    var hit = svgEl("rect", { class: "band-hit", y: PAD.t, height: plotH });
    hit.style.display = "none";
    svg.appendChild(hit);

    series.forEach(function (s, si) {
      for (var k = 0; k < n; k++) {
        var v = s.values[k] || 0;
        if (!(v > 0)) continue;
        var x = xOf(k) + band / 2 + (si === 0 ? -(bw + 3) : 3), y = yOf(v);
        var rect = svgEl("rect", { class: "bar", x: x, y: y, width: bw, height: baseY() - y });
        rect.style.fill = "var(--series-" + s.slot + ")";
        rect.style.opacity = si === 0 ? "0.92" : "0.34";
        if (si > 0) { rect.style.stroke = "var(--series-" + s.slot + ")"; rect.setAttribute("stroke-width", "1"); }
        svg.appendChild(rect);
        if (n <= 14) {
          var lb = svgEl("text", { class: "bar-label", x: x + bw / 2, y: y - 4, "text-anchor": "middle" });
          lb.textContent = String(Math.round(v * 10) / 10);
          svg.appendChild(lb);
        }
      }
    });

    var wrap = svg.parentNode;
    svg.addEventListener("pointermove", function (ev) {
      var box = svg.getBoundingClientRect();
      var px = (ev.clientX - box.left) / box.width * W;
      var idx = Math.floor((px - PAD.l) / band);
      if (idx < 0) idx = 0;
      if (idx > n - 1) idx = n - 1;
      hit.setAttribute("x", xOf(idx));
      hit.setAttribute("width", band);
      hit.style.display = "";
      tip.hidden = false;
      while (tip.firstChild) tip.removeChild(tip.firstChild);
      tip.appendChild(el("div", "tt-head", "连续失败 " + idx + " 次"));
      series.forEach(function (s) {
        var row = el("div", "tt-row"), key = el("span", "tt-key");
        key.style.background = "var(--series-" + s.slot + ")";
        row.appendChild(key);
        row.appendChild(el("span", "tt-name", s.label));
        row.appendChild(el("span", "tt-val", String(Math.round((s.values[idx] || 0) * 10) / 10)));
        tip.appendChild(row);
      });
      var host = wrap.getBoundingClientRect();
      tip.style.left = Math.min(Math.max(ev.clientX - host.left + 12, 0), Math.max(host.width - 200, 0)) + "px";
      tip.style.top = (ev.clientY - host.top + 12) + "px";
    });
    svg.addEventListener("pointerleave", function () { hit.style.display = "none"; tip.hidden = true; });
  }

  // ── 直方图数据 ──
  function histOf(rows) {
    var g = gapsOf(rows), gaps = g.gaps;
    var maxK = 0;
    gaps.forEach(function (v) { if (v > maxK) maxK = v; });
    var top = Math.max(maxK, 10), counts = [];
    for (var k = 0; k <= top; k++) counts.push(0);
    gaps.forEach(function (v) { if (v <= top) counts[v] += 1; });
    return { counts: counts, gaps: gaps.length, trailing: g.trailing, maxK: maxK };
  }
  function theoryOf(counts, gaps, p) {
    return counts.map(function (_, k) { return gaps * Math.pow(1 - p, k) * p; });
  }

  function drawHistogram(rows) {
    var hist = histOf(rows);
    var p = Number(document.getElementById("p-input").value) / 100;
    if (!(p > 0 && p < 1)) p = 0.3;
    var theory = theoryOf(hist.counts, hist.gaps, p);
    drawBars(document.getElementById("svg-hist"), document.getElementById("tip-hist"),
      [{ label: "实测", slot: 1, values: hist.counts },
       { label: "理论 p=" + (p * 100).toFixed(1) + "%", slot: 2, values: theory }],
      { height: 280 });
    var s = summarize(rows);
    document.getElementById("hist-cap").textContent =
      "间隔总数（成功次数）" + hist.gaps + " · 实测成功率 " + (rows.length ? pct(s.rate) : "—")
      + " · 最长连续失败 " + s.max + " 次"
      + (hist.trailing ? " · 末尾还有 " + hist.trailing + " 次连续失败未结束，未计入分布" : "")
      + "。理论频数 = 间隔总数 × (1−p)^k × p，也就是「连着失败 k 次后第 k+1 次成功」的二项式展开项，"
      + "默认 p=30%（官方宣称），可在上面改成实测值或其它假设来对照形状。";
    document.getElementById("p-hint").textContent =
      "当前 p=" + (p * 100).toFixed(1) + "%，实测成功率 " + (rows.length ? pct(s.rate) : "—");
  }

  // ── 初始化 ──
  function tile(host, label, value, hint, hero) {
    var box = el("div", "tile" + (hero ? " hero" : ""));
    box.appendChild(el("span", "label", label));
    box.appendChild(el("span", "value", value));
    if (hint) box.appendChild(el("span", "hint", hint));
    host.appendChild(box);
  }

  function init() {
    document.getElementById("meta-sub").textContent =
      "生成时间 " + (DATA.generated_at || "") + " · 日志 " + (DATA.log_path || "");

    function renderSelected() {
    var s = summarize(RECORDS);
    var stats = document.getElementById("stats");
    stats.innerHTML = "";
    tile(stats, "成功率", RECORDS.length ? pct(s.rate) : "—",
         s.n + " 次合成中成功 " + s.ok + " 次", true);
    tile(stats, "合成次数", String(s.n), "失败 " + s.fail + " 次");
    tile(stats, "平均连续失败", s.avg.toFixed(2), "两次成功之间的失败次数");
    tile(stats, "最长连续失败", String(s.max), s.trailing ? "末尾未结束 " + s.trailing + " 次" : "已全部结束");

    renderTable(document.getElementById("table-total"), RECORDS.length ? [rowFor("全部", RECORDS)] : []);

    var kindRows = [];
    (DATA.kinds || []).forEach(function (kind) {
      var rows = RECORDS.filter(function (r) { return r.kind === kind.id; });
      if (rows.length) kindRows.push(rowFor(kind.name, rows));
    });
    renderTable(document.getElementById("table-kind"), kindRows);

    var qualityRows = [];
    (DATA.qualities || []).forEach(function (q) {
      var rows = RECORDS.filter(function (r) { return r.quality === q.id; });
      if (rows.length) qualityRows.push(rowFor(q.name, rows, q.id));
    });
    renderTable(document.getElementById("table-quality"), qualityRows);

      drawHistogram(RECORDS);
      document.getElementById("date-apply").click();
    }

    var select = document.getElementById("batch");
    select.innerHTML = "";
    (DATA.batches || []).forEach(function (b) {
      var opt = document.createElement("option");
      opt.value = String(b.batch);
      opt.textContent = "第" + b.batch + "次，时间: " + b.started_at + "（" + b.count + " 次合成）";
      select.appendChild(opt);
    });

    document.getElementById("batch-apply").addEventListener("click", function () {
      var chosen = Array.prototype.filter.call(select.options, function (o) { return o.selected; })
        .map(function (o) { return Number(o.value); });
      RECORDS = chosen.length ? ALL_RECORDS.filter(function (r) { return chosen.indexOf(r.batch) >= 0; }) : ALL_RECORDS.slice();
      var limitText = document.getElementById("attempt-limit").value.trim();
      if (/^[1-9][0-9]*$/.test(limitText)) {
        var limit = Number(limitText);
        if (Number.isSafeInteger(limit)) RECORDS = RECORDS.slice(0, limit);
      }
      var rows = RECORDS;
      renderSelected();
      var out = chosen.map(function (b) {
        var sub = rows.filter(function (r) { return r.batch === b; });
        return rowFor("第" + b + "次", sub);
      });
      if (out.length > 1) out.push(rowFor("合计", rows));
      renderTable(document.getElementById("table-batch"), out);
    });

    document.getElementById("attempt-limit").addEventListener("input", function () { document.getElementById("batch-apply").click(); });
    select.addEventListener("change", function () { document.getElementById("batch-apply").click(); });

    document.getElementById("date-apply").addEventListener("click", function () {
      var from = document.getElementById("date-from").value;
      var to = document.getElementById("date-to").value;
      if (!from && !to) {
        renderTable(document.getElementById("table-date"), []);
        return;
      }
      var rows = RECORDS.filter(function (r) {
        var day = String(r.ts || "").slice(0, 10);
        if (!day) return false;
        if (from && day < from) return false;
        if (to && day > to) return false;
        return true;
      });
      var days = [];
      rows.forEach(function (r) {
        var day = String(r.ts || "").slice(0, 10);
        if (days.indexOf(day) < 0) days.push(day);
      });
      days.sort();
      var out = days.map(function (day) {
        return rowFor(day, rows.filter(function (r) { return String(r.ts || "").slice(0, 10) === day; }));
      });
      if (out.length > 1) out.push(rowFor("合计", rows));
      renderTable(document.getElementById("table-date"), out);
    });

    var pInput = document.getElementById("p-input");
    pInput.value = String(DATA.expected_rate === undefined ? 30 : DATA.expected_rate);
    pInput.addEventListener("input", function () { drawHistogram(RECORDS); });
    renderSelected();

    document.getElementById("theme-toggle").addEventListener("click", function () {
      var root = document.documentElement;
      var dark = root.getAttribute("data-theme") === "dark"
        || (!root.getAttribute("data-theme") && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
      root.setAttribute("data-theme", dark ? "light" : "dark");
    });
  }

  init();
})();
</script>
</body>
</html>
"""
