"""HTML 报告模板字符串；渲染时用 __PAYLOAD__ 占位符替换为 JSON。"""

HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>战斗伤害报告</title>
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
    --series-3: #1baf7a;
    --series-4: #eda100;
    --series-5: #e87ba4;
    --series-6: #008300;
    --series-7: #4a3aa7;
    --series-8: #e34948;
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
      --series-3: #199e70;
      --series-4: #c98500;
      --series-5: #d55181;
      --series-6: #008300;
      --series-7: #9085e9;
      --series-8: #e66767;
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
    --series-3: #199e70;
    --series-4: #c98500;
    --series-5: #d55181;
    --series-6: #008300;
    --series-7: #9085e9;
    --series-8: #e66767;
  }

  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
    background: var(--page);
    color: var(--text-primary);
  }
  .viz-root { background: var(--page); color: var(--text-primary); padding: 28px 24px 56px; }
  .wrap { max-width: 1180px; margin: 0 auto; }

  .page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 20px; }
  h1 { font-size: 20px; font-weight: 600; margin: 0 0 4px; letter-spacing: .01em; }
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
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px 16px;
  }
  .tile .label { display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
  .tile .value { font-size: 22px; font-weight: 600; }
  .tile.hero .value { font-size: 48px; line-height: 1.05; font-weight: 600; }
  .tile .hint { display: block; font-size: 12px; color: var(--text-muted); margin-top: 4px; }

  .card {
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
    padding: 18px; margin-bottom: 16px;
  }
  .card h2 { font-size: 15px; font-weight: 600; margin: 0 0 4px; }
  .card .note { font-size: 12px; color: var(--text-secondary); margin: 0 0 12px; line-height: 1.6; }

  .filters {
    display: flex; flex-wrap: wrap; align-items: center; gap: 12px 18px;
    padding: 12px 14px; margin-bottom: 16px;
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
  }
  .filters label { font-size: 13px; color: var(--text-secondary); display: inline-flex; align-items: center; gap: 6px; }
  .filters select {
    font: inherit; font-size: 13px; padding: 4px 8px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--surface-1); color: var(--text-primary);
  }

  .plot { position: relative; margin-bottom: 6px; }
  .plot + .plot { margin-top: 14px; }
  svg { display: block; width: 100%; height: auto; }
  .grid-line { stroke: var(--grid); stroke-width: 1; }
  .axis-line { stroke: var(--axis); stroke-width: 1; }
  .tick-text { fill: var(--text-muted); font-size: 11px; font-variant-numeric: tabular-nums; }
  .series-line { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
  .series-dot { stroke: var(--surface-1); stroke-width: 2; }
  .end-label { fill: var(--text-secondary); font-size: 11px; }
  .ref-line { stroke: var(--text-muted); stroke-width: 1; }
  .ref-label { fill: var(--text-muted); font-size: 10px; }
  .crosshair { stroke: var(--axis); stroke-width: 1; }

  .tooltip {
    position: absolute; pointer-events: none; z-index: 5;
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 10px; font-size: 12px; min-width: 210px; max-width: 320px;
    box-shadow: 0 4px 14px rgba(0, 0, 0, .12);
  }
  .tooltip .tt-head { color: var(--text-secondary); font-size: 11px; margin-bottom: 6px; }
  .tooltip .tt-row { display: flex; align-items: center; gap: 8px; padding: 2px 0; }
  .tooltip .tt-key { width: 14px; height: 2px; border-radius: 1px; flex: none; }
  .tooltip .tt-val { font-weight: 600; font-variant-numeric: tabular-nums; margin-left: auto; color: var(--text-primary); }
  .tooltip .tt-name { color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tooltip .tt-sep {
    display: flex; align-items: center; gap: 8px; margin: 7px 0 3px; padding-top: 6px;
    border-top: 1px solid var(--border);
  }
  .tooltip .tt-sep-text { font-size: 11px; color: var(--text-primary); font-weight: 600; }
  .tooltip .tt-sub { padding: 1px 0; }
  .tooltip .tt-sub .tt-name { padding-left: 22px; font-size: 11px; }
  .tooltip .tt-sub .tt-val { font-weight: 600; font-size: 11px; }

  .legend { display: flex; flex-wrap: wrap; gap: 6px 10px; margin-top: 10px; }
  .chip {
    display: inline-flex; align-items: center; gap: 7px; font-size: 12px;
    padding: 5px 10px; border: 1px solid var(--border); border-radius: 999px;
    cursor: pointer; color: var(--text-primary); background: var(--surface-1);
  }
  .chip input { margin: 0; cursor: pointer; }
  .chip .key { width: 14px; height: 2px; border-radius: 1px; flex: none; }
  .chip .chip-val { color: var(--text-secondary); font-variant-numeric: tabular-nums; }
  .chip.off { opacity: .45; }

  .cap-note { margin: 10px 0 0; font-size: 12px; color: var(--text-secondary); }

  table { border-collapse: collapse; width: 100%; font-size: 12px; }
  th, td { text-align: right; padding: 6px 8px; border-bottom: 1px solid var(--grid); font-variant-numeric: tabular-nums; }
  th:first-child, td:first-child { text-align: left; }
  thead th { color: var(--text-secondary); font-weight: 600; }
  .table-scroll { max-height: 420px; overflow: auto; }

  .tree { font-size: 13px; }
  .tree-row { display: flex; align-items: center; gap: 8px; padding: 5px 0; }
  .tree-row .nm { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tree-row .meta { color: var(--text-secondary); font-size: 12px; }
  .tree-row .val { margin-left: auto; color: var(--text-secondary); font-variant-numeric: tabular-nums; }
  .tree-l1 { font-weight: 600; }
  .tree-l2 { padding-left: 26px; }
  .tree-l3 { padding-left: 52px; color: var(--text-secondary); }
  .tree-row input { cursor: pointer; }
  .tag { font-size: 11px; color: var(--text-secondary); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; }

  ul.zero { margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.9; }
  ul.zero .meta { color: var(--text-secondary); }

  .attr-pick { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
  .attr-pick input[type=range] { width: 260px; }
  .attr-pick .sec { font-variant-numeric: tabular-nums; font-weight: 600; min-width: 54px; }
  .attr-delta { font-variant-numeric: tabular-nums; }
  .attr-delta.up { color: var(--text-primary); font-weight: 600; }
  .attr-delta.down { color: var(--text-secondary); }
  .cap-note { margin: 10px 0 0; font-size: 12px; color: var(--text-secondary); }
  .players { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  @media (max-width: 860px) { .players { grid-template-columns: 1fr; } }
  .player { border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
  .player h3 { font-size: 13px; font-weight: 600; margin: 0 0 8px; }
  .player .who { font-size: 13px; margin-bottom: 4px; }
  .player .who .muted { color: var(--text-secondary); font-size: 12px; }
  .player h4 { font-size: 12px; font-weight: 600; margin: 12px 0 4px; color: var(--text-secondary); }
  .player ul { margin: 0; padding-left: 16px; font-size: 12px; line-height: 1.8; }
  .player .attrs { display: grid; grid-template-columns: 1fr auto; gap: 2px 12px; font-size: 12px; }
  .player .attrs span:nth-child(even) { font-variant-numeric: tabular-nums; text-align: right; }
  .empty { font-size: 12px; color: var(--text-muted); }
</style>
</head>
<body>
<div class="viz-root">
  <div class="wrap">
    <header class="page-head">
      <div>
        <h1>战斗伤害报告</h1>
        <p class="sub" id="meta-sub"></p>
      </div>
      <button class="btn" id="theme-toggle" type="button">切换深浅色</button>
    </header>

    <div class="stats" id="stats"></div>

    <section class="card" id="pvp-card" hidden>
      <h2>分数与伤害</h2>
      <p class="note" id="pvp-note"></p>
      <div class="plot" id="plot-score"><svg id="svg-score" role="img" aria-label="双方分数曲线"></svg><div class="tooltip" id="tip-score" hidden></div></div>
      <div class="plot" id="plot-dmg"><svg id="svg-dmg" role="img" aria-label="双方每秒伤害"></svg><div class="tooltip" id="tip-dmg" hidden></div></div>
      <div class="plot" id="plot-share"><svg id="svg-share" role="img" aria-label="伤害天平"></svg><div class="tooltip" id="tip-share" hidden></div></div>
    </section>

    <section class="card" id="players-card" hidden>
      <h2>对战双方</h2>
      <p class="note">从战斗数据里读到的双方信息；字段按实际下发情况显示，缺失即为空。</p>
      <div class="players" id="players"></div>
    </section>

    <section class="card" id="attr-card" hidden>
      <h2>双方属性</h2>
      <p class="note" id="attr-note"></p>
      <div class="attr-pick">
        <label>秒
          <input type="range" id="attr-sec" min="0" max="0" value="0">
        </label>
        <span class="sec" id="attr-sec-label">0s</span>
        <span class="sub" id="attr-hint"></span>
      </div>
      <div class="table-scroll"><table id="attr-table"></table></div>
      <div class="legend" id="attr-picks"></div>
      <div class="legend" id="attr-legend"></div>
      <div class="plot"><svg id="svg-attr" role="img" aria-label="双方属性变化曲线"></svg><div class="tooltip" id="tip-attr" hidden></div></div>
      <p class="cap-note" id="attr-cap" hidden></p>
    </section>

    <div class="filters" role="group" aria-label="图表筛选">
      <label>视角
        <select id="side">
          <option value="self">我方</option>
          <option value="other">敌方</option>
        </select>
      </label>
      <label>层级
        <select id="level">
          <option value="cat">类别</option>
          <option value="book">天书</option>
          <option value="branch">觉醒分支</option>
          <option value="skill">技能</option>
        </select>
      </label>
      <label>视图
        <select id="view">
          <option value="dps">每秒伤害</option>
          <option value="cum">累计伤害</option>
        </select>
      </label>
      <label>口径
        <select id="scope">
          <option value="all">全部目标</option>
          <option value="boss">仅对 BOSS</option>
        </select>
      </label>
      <label><input type="checkbox" id="show-table"> 显示数据表</label>
      <button class="btn" id="sel-all" type="button">全选本层</button>
      <button class="btn" id="sel-none" type="button">清空</button>
    </div>

    <section class="card">
      <div class="card-head">
        <h2 id="chart-title"></h2>
        <p class="note" id="chart-sub"></p>
      </div>
      <div class="plot"><svg id="svg-main" role="img" aria-label="伤害拆解曲线"></svg><div class="tooltip" id="tip-main" hidden></div></div>
      <div class="legend" id="legend"></div>
      <p class="cap-note" id="cap-note" hidden></p>
    </section>

    <section class="card" id="table-card" hidden>
      <h2>数据表</h2>
      <p class="note">与图表同源的数值，横向滚动查看全部时间点。</p>
      <div class="table-scroll"><table id="table"></table></div>
    </section>

    <section class="card">
      <h2>天书 → 觉醒分支 → 技能</h2>
      <p class="note">勾选框只对当前「层级」生效。天书合计包含该天书所有技能（含召唤物/施法），
        分支只统计该分支技能放出的伤害；分支的属性加成混在全局属性里，无法从伤害数字中剥离。</p>
      <div class="tree" id="drill"></div>
    </section>

    <section class="card" id="zero-card" hidden>
      <h2>已激活但本场零伤害的分支</h2>
      <p class="note">这些分支本场点了但没打出伤害：可能只贡献了属性加成，
        也可能被同本更高阶分支的技能覆盖（getEvolutionSkillId 取最大 skillId 替换主技能）。</p>
      <ul class="zero" id="zero-list"></ul>
    </section>
  </div>
</div>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("payload").textContent);
  var MAX_SERIES = 8;
  // 我方固定用 1 号色、敌方固定用 2 号色：颜色跟实体，不跟排名，也不随筛选变化
  var SELF_SLOT = 1, OTHER_SLOT = 2;

  var state = { level: "cat", view: "dps", scope: "all", side: "self", selected: {} };

  function fmt(n) {
    n = Number(n) || 0;
    if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + "亿";
    if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(2) + "万";
    return String(Math.round(n));
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }
  function cumulative(values) {
    var out = [], sum = 0;
    for (var i = 0; i < values.length; i++) { sum += values[i]; out.push(sum); }
    return out;
  }
  function svgEl(tag, attrs) {
    var e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  // 当前视角的数据（self 的字段就在顶层，other 在 DATA.other 下）
  function sd() {
    return state.side === "other" ? (DATA.other || null) : DATA;
  }

  // ── 通用折线图 ──
  // opts: { height, yFormat, refLine:{value,label}, yMin, yMax }
  function drawLine(svg, tip, series, opts) {
    opts = opts || {};
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var W = 1000;
    var H = opts.height || 220;
    var PAD = { t: 14, r: 78, b: 30, l: 60 };
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);

    var n = 0;
    series.forEach(function (s) { n = Math.max(n, s.values.length); });
    if (!n) return;

    var maxV = 0, minV = 0;
    series.forEach(function (s) {
      s.values.forEach(function (v) { if (v > maxV) maxV = v; if (v < minV) minV = v; });
    });
    if (opts.yMin !== undefined) minV = opts.yMin;
    if (opts.yMax !== undefined) maxV = opts.yMax;
    if (opts.refLine && opts.refLine.value > maxV) maxV = opts.refLine.value;
    if (maxV === minV) maxV = minV + 1;
    var span = maxV - minV;

    var plotW = W - PAD.l - PAD.r, plotH = H - PAD.t - PAD.b;
    function xOf(i) { return PAD.l + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW); }
    function yOf(v) { return PAD.t + plotH - ((v - minV) / span) * plotH; }

    for (var g = 0; g <= 4; g++) {
      var v = minV + (span / 4) * g, y = yOf(v);
      svg.appendChild(svgEl("line", { class: "grid-line", x1: PAD.l, x2: PAD.l + plotW, y1: y, y2: y }));
      var t = svgEl("text", { class: "tick-text", x: PAD.l - 8, y: y + 4, "text-anchor": "end" });
      t.textContent = (opts.yFormat || fmt)(v);
      svg.appendChild(t);
    }
    svg.appendChild(svgEl("line", { class: "axis-line", x1: PAD.l, x2: PAD.l + plotW, y1: PAD.t + plotH, y2: PAD.t + plotH }));

    var step = Math.max(1, Math.ceil(n / 8));
    for (var i = 0; i < n; i += step) {
      var xt = svgEl("text", { class: "tick-text", x: xOf(i), y: PAD.t + plotH + 16, "text-anchor": "middle" });
      // 秒数可能跳号（快进时采样不连续），标签要用真实秒，不能用下标
      xt.textContent = ((opts && opts.xLabels && opts.xLabels[i] !== undefined) ? opts.xLabels[i] : i) + "s";
      svg.appendChild(xt);
    }

    if (opts && opts.markerIndex !== undefined && opts.markerIndex >= 0 && opts.markerIndex < n) {
      var mx = xOf(opts.markerIndex);
      svg.appendChild(svgEl("line", { class: "ref-line", x1: mx, x2: mx, y1: PAD.t, y2: PAD.t + plotH }));
      var mv = (opts.xLabels && opts.xLabels[opts.markerIndex] !== undefined) ? opts.xLabels[opts.markerIndex] : opts.markerIndex;
      var ml = svgEl("text", { class: "ref-label", x: mx + 4, y: PAD.t + 10 });
      ml.textContent = mv + "s";
      svg.appendChild(ml);
    }

    if (opts.refLine) {
      var ry = yOf(opts.refLine.value);
      svg.appendChild(svgEl("line", { class: "ref-line", x1: PAD.l, x2: PAD.l + plotW, y1: ry, y2: ry }));
      var rl = svgEl("text", { class: "ref-label", x: PAD.l + plotW + 6, y: ry + 3 });
      rl.textContent = opts.refLine.label;
      svg.appendChild(rl);
    }

    series.forEach(function (s) {
      var pts = [];
      for (var i = 0; i < n; i++) pts.push(xOf(i) + "," + yOf(s.values[i] || 0));
      var line = svgEl("polyline", { class: "series-line", points: pts.join(" ") });
      line.style.stroke = "var(--series-" + s.slot + ")";
      svg.appendChild(line);
      var last = n - 1;
      var dot = svgEl("circle", { class: "series-dot", cx: xOf(last), cy: yOf(s.values[last] || 0), r: 4 });
      dot.style.fill = "var(--series-" + s.slot + ")";
      svg.appendChild(dot);
      if (series.length <= 4) {
        var lb = svgEl("text", { class: "end-label", x: xOf(last) + 9, y: yOf(s.values[last] || 0) + 4 });
        lb.textContent = (opts.yFormat || fmt)(s.values[last] || 0);
        svg.appendChild(lb);
      }
    });

    // 十字准线：一次列出该时刻所有系列
    var hair = svgEl("line", { class: "crosshair", y1: PAD.t, y2: PAD.t + plotH });
    hair.style.display = "none";
    svg.appendChild(hair);
    var wrap = svg.parentNode;
    svg.addEventListener("pointermove", function (ev) {
      if (!series.length) return;
      var rect = svg.getBoundingClientRect();
      var px = (ev.clientX - rect.left) / rect.width * W;
      var idx = 0, best = Infinity;
      for (var i = 0; i < n; i++) {
        var d = Math.abs(xOf(i) - px);
        if (d < best) { best = d; idx = i; }
      }
      hair.setAttribute("x1", xOf(idx));
      hair.setAttribute("x2", xOf(idx));
      hair.style.display = "";
      tip.hidden = false;
      while (tip.firstChild) tip.removeChild(tip.firstChild);
      var headSec = (opts && opts.xLabels && opts.xLabels[idx] !== undefined) ? opts.xLabels[idx] : idx;
      tip.appendChild(el("div", "tt-head", headSec + "s"));
      series.forEach(function (s) {
        var row = el("div", "tt-row");
        var key = el("span", "tt-key");
        key.style.background = "var(--series-" + s.slot + ")";
        row.appendChild(key);
        row.appendChild(el("span", "tt-name", s.label));
        row.appendChild(el("span", "tt-val", (opts.yFormat || fmt)(s.values[idx] || 0)));
        tip.appendChild(row);
      });

      // 这一秒的伤害来源：按来源列出双方各自的 Top N
      var tops = opts && opts.topSources;
      if (tops && tops.length) {
        var limit = opts.topN || 5;
        tops.forEach(function (src) {
          var list = (src.bySecond && src.bySecond[idx]) || [];
          if (!list.length) return;
          var head = el("div", "tt-sep");
          var hk = el("span", "tt-key");
          hk.style.background = "var(--series-" + src.slot + ")";
          head.appendChild(hk);
          head.appendChild(el("span", "tt-sep-text",
            src.label + " 来源 Top" + Math.min(limit, list.length)));
          tip.appendChild(head);
          list.slice(0, limit).forEach(function (item) {
            var row = el("div", "tt-row tt-sub");
            var label = item.name + (item.origin ? " · " + item.origin : "");
            row.appendChild(el("span", "tt-name", label));
            row.appendChild(el("span", "tt-val", (opts.yFormat || fmt)(item.dmg)));
            tip.appendChild(row);
          });
        });
      }
      var wr = wrap.getBoundingClientRect();
      var left = ev.clientX - wr.left + 14;
      if (left + tip.offsetWidth > wr.width) left = ev.clientX - wr.left - tip.offsetWidth - 14;
      tip.style.left = Math.max(0, left) + "px";
      tip.style.top = Math.min(Math.max(0, wr.height - tip.offsetHeight - 4), ev.clientY - wr.top - 12) + "px";
    });
    svg.addEventListener("pointerleave", function () {
      tip.hidden = true;
      hair.style.display = "none";
    });
  }

  // ── PVP 三图 ──
  function renderPvp() {
    var pvp = DATA.pvp;
    if (!pvp) return;
    document.getElementById("pvp-card").hidden = false;
    var derived = pvp.derived || [];
    var shareFmt = function (v) { return (v * 100).toFixed(0) + "%"; };

    var note = "分数增量 =（本秒我方伤害占比 − 0.5）× PVPBaseBonus × PVPInitVariable^第几秒；" +
      "时间权重 PVPInitVariable=" + (pvp.cfg && pvp.cfg.PVPInitVariable) +
      "，所以越往后同一占比换到的分数越高。胜利线 = 2 × PVPInitScore；" +
      "时限 PVPLimitTime=" + (pvp.cfg && pvp.cfg.PVPLimitTime) +
      " 秒（跳过时本地会把整场跑到分出胜负或到时限，所以时间轴就是模拟实际跑到的秒数）。";
    if (pvp.skipped) {
      note += " 本场点了跳过：好友切磋是本地快进，模拟照常跑完，数据完整；" +
              "其它 PVP 的跳过走服务端结算、本地不补算，曲线只到跳过那一刻为止。";
    }
    document.getElementById("pvp-note").textContent = note;

    var seconds = derived.map(function (d) { return d.sec; });
    drawLine(document.getElementById("svg-score"), document.getElementById("tip-score"), [
      { label: "我方分数", slot: SELF_SLOT, values: derived.map(function (d) { return d.selfScore; }) },
      { label: "敌方分数", slot: OTHER_SLOT, values: derived.map(function (d) { return d.otherScore; }) }
    ], { height: 200, xLabels: seconds, refLine: { value: pvp.winLine, label: "胜利线" } });

    // 分数只按「对敌方英雄」的伤害结算，所以这里的来源也取 boss 口径，才对得上曲线数值
    var tops = [];
    if (DATA.perSecondBossTop) tops.push({ label: "我方", slot: SELF_SLOT, bySecond: DATA.perSecondBossTop });
    if (DATA.other && DATA.other.perSecondBossTop) {
      tops.push({ label: "敌方", slot: OTHER_SLOT, bySecond: DATA.other.perSecondBossTop });
    }
    drawLine(document.getElementById("svg-dmg"), document.getElementById("tip-dmg"), [
      { label: "我方每秒伤害", slot: SELF_SLOT, values: derived.map(function (d) { return d.selfDmg; }) },
      { label: "敌方每秒伤害", slot: OTHER_SLOT, values: derived.map(function (d) { return d.otherDmg; }) }
    ], { height: 200, xLabels: seconds, topSources: tops, topN: 5 });

    drawLine(document.getElementById("svg-share"), document.getElementById("tip-share"), [
      { label: "我方伤害占比", slot: SELF_SLOT, values: derived.map(function (d) { return d.share === null ? 0.5 : d.share; }) }
    ], { height: 180, xLabels: seconds, yFormat: shareFmt, yMin: 0, yMax: 1, refLine: { value: 0.5, label: "五五开" } });
  }

  // ── 双方属性：按秒对比 + 属性变化曲线 ──
  var attrState = { sec: 0, picked: [] };
  var ATTR_MAX_SERIES = 4;   // 每条属性画双方两条线，4 条属性 = 8 条线（配色上限）

  // 百分比属性：compAttributes 里存的是比率（9.2518 = 925.18%、2.135 = 213.5%），要 ×100。
  // （实测 logs/damage_curve_*.json 确认；AttrCfg.style/parse 的换算不等同于这一步，别再改回 ÷100）
  function pctText(num) {
    var p = num * 100;
    if (Math.abs(p) >= 10) return String(Math.round(p));       // 925% / 214% / 164%
    return String(Math.round(p * 10) / 10);                    // 小于 10% 保留一位：0.6%
  }

  function fmtAttr(meta, value) {
    if (value === undefined || value === null) return "—";
    var num = Number(value) || 0;
    if (meta && meta.percent) return pctText(num) + "%";
    return fmt(num);
  }

  function attrMetaOf(pvp, key) {
    var list = pvp.attrMeta || [];
    for (var i = 0; i < list.length; i++) if (list[i].key === key) return list[i];
    for (var j = 0; j < list.length; j++) if (String(list[j].key) === String(key)) return list[j];
    return { key: key, label: String(key), note: String(key), percent: false };
  }

  function renderAttrTable(pvp, seconds, meta) {
    var table = document.getElementById("attr-table");
    while (table.firstChild) table.removeChild(table.firstChild);
    var snapshot = pvp.attrSeconds[attrState.sec] || { self: {}, other: {} };
    var thead = document.createElement("thead");
    var hr = document.createElement("tr");
    hr.appendChild(el("th", null, "属性"));
    hr.appendChild(el("th", null, "我方"));
    hr.appendChild(el("th", null, "敌方"));
    hr.appendChild(el("th", null, "我方 − 敌方"));
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    meta.forEach(function (m) {
      var a = snapshot.self ? snapshot.self[m.key] : undefined;
      var b = snapshot.other ? snapshot.other[m.key] : undefined;
      // 不跳过没值的行：全都列出来，读不到就显示 —，这样能一眼看出哪些属性没采到
      var tr = document.createElement("tr");
      tr.appendChild(el("td", null, m.note));
      tr.appendChild(el("td", null, fmtAttr(m, a)));
      tr.appendChild(el("td", null, fmtAttr(m, b)));
      var delta = (a === undefined || b === undefined) ? null : (Number(a) - Number(b));
      var cell = el("td", "attr-delta" + (delta === null ? "" : (delta > 0 ? " up" : (delta < 0 ? " down" : ""))),
        delta === null ? "—" : fmtAttr(m, delta));
      tr.appendChild(cell);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    document.getElementById("attr-sec-label").textContent =
      (seconds[attrState.sec] !== undefined ? seconds[attrState.sec] : attrState.sec) + "s";
  }

  function renderAttrLegend(pvp, meta) {
    var box = document.getElementById("attr-legend");
    while (box.firstChild) box.removeChild(box.firstChild);
    meta.forEach(function (m) {
      var idx = attrState.picked.indexOf(m.key);
      if (idx < 0) return;
      [["我方", SELF_SLOT], ["敌方", OTHER_SLOT]].forEach(function (pair) {
        var chip = el("span", "chip");
        var key = el("span", "key");
        key.style.background = "var(--series-" + (idx * 2 + (pair[0] === "我方" ? 1 : 2)) + ")";
        chip.appendChild(key);
        chip.appendChild(el("span", "nm", m.label + " · " + pair[0]));
        box.appendChild(chip);
      });
    });
  }

  function renderAttrChart(pvp, seconds, meta) {
    var svg = document.getElementById("svg-attr");
    var tip = document.getElementById("tip-attr");
    var series = [];
    attrState.picked.forEach(function (key, idx) {
      var m = attrMetaOf(pvp, key);
      series.push({
        label: m.label + " 我方", slot: idx * 2 + 1,
        values: pvp.attrSeconds.map(function (a) { return (a.self && a.self[key] !== undefined) ? a.self[key] : 0; })
      });
      series.push({
        label: m.label + " 敌方", slot: idx * 2 + 2,
        values: pvp.attrSeconds.map(function (a) { return (a.other && a.other[key] !== undefined) ? a.other[key] : 0; })
      });
    });
    // 勾的全是百分比属性时，纵轴和 tooltip 也按 % 显示；混了数值类（攻击）就退回原始值
    var allPercent = attrState.picked.length > 0 && attrState.picked.every(function (key) {
      return attrMetaOf(pvp, key).percent;
    });
    drawLine(svg, tip, series, {
      height: 300, xLabels: seconds, markerIndex: attrState.sec,
      yFormat: allPercent ? function (v) { return pctText(Number(v) || 0) + "%"; } : fmt
    });

    var cap = document.getElementById("attr-cap");
    var hasPercent = attrState.picked.some(function (key) { return attrMetaOf(pvp, key).percent; });
    cap.hidden = false;
    cap.textContent = hasPercent
      ? "百分比属性已换算成整数百分数（23000 → 230%）；最终PVP增伤 = 本方PVP增伤 − 对方PVP减伤。"
      : "最多同时勾 " + ATTR_MAX_SERIES + " 条属性（每条画双方两条线，配色槽位共 8 个）；最终PVP增伤 = 本方PVP增伤 − 对方PVP减伤。";
  }

  function renderAttrs() {
    var pvp = DATA.pvp;
    if (!pvp || !pvp.attrSeconds || !pvp.attrSeconds.length) return;
    document.getElementById("attr-card").hidden = false;
    var meta = pvp.attrMeta || [];
    var seconds = pvp.attrSeconds.map(function (a) { return a.sec; });

    document.getElementById("attr-note").textContent =
      "战斗过程中双方属性（含 buff 带来的变化）。拖动滑块选秒看即时对比，" +
      "或在下方勾选属性画变化曲线 —— 两种视图联动。" +
      "表里 — 表示该秒没读到这个属性；百分比类已换算成整数百分数（如 230%）。";

    var slider = document.getElementById("attr-sec");
    slider.max = String(pvp.attrSeconds.length - 1);
    slider.value = String(attrState.sec);
    slider.addEventListener("input", function (e) {
      attrState.sec = Number(e.target.value);
      renderAttrTable(pvp, seconds, meta);
      renderAttrChart(pvp, seconds, meta);
    });

    // 属性勾选（单独容器，不与曲线图例混用，否则会被 renderAttrLegend 覆盖）
    document.getElementById("attr-hint").textContent = "曲线属性：";
    var legend = document.getElementById("attr-picks");
    meta.forEach(function (m) {
      var chip = el("label", "chip" + (attrState.picked.indexOf(m.key) >= 0 ? "" : " off"));
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = attrState.picked.indexOf(m.key) >= 0;
      cb.addEventListener("change", function () {
        var at = attrState.picked.indexOf(m.key);
        if (cb.checked) {
          if (at < 0 && attrState.picked.length >= ATTR_MAX_SERIES) {
            cb.checked = false;
            return;
          }
          if (at < 0) attrState.picked.push(m.key);
        } else if (at >= 0) {
          attrState.picked.splice(at, 1);
        }
        renderAttrLegend(pvp, meta);
        renderAttrChart(pvp, seconds, meta);
        syncAttrChips();
      });
      chip.appendChild(cb);
      chip.appendChild(el("span", "nm", m.label));
      legend.appendChild(chip);
    });

    renderAttrTable(pvp, seconds, meta);
    renderAttrLegend(pvp, meta);
    renderAttrChart(pvp, seconds, meta);
  }

  function syncAttrChips() {
    var pvp = DATA.pvp;
    if (!pvp) return;
    var meta = pvp.attrMeta || [];
    var chips = document.getElementById("attr-picks").children;
    for (var i = 0; i < chips.length; i++) {
      var chip = chips[i];
      var cb = chip.children && chip.children[0];
      if (!cb || cb.type !== "checkbox") continue;
      var key = meta[i] ? meta[i].key : null;
      if (key === null) continue;
      chip.className = "chip" + (attrState.picked.indexOf(key) >= 0 ? "" : " off");
    }
  }

  // ── 玩家数据 ──
  function renderPlayers() {
    var side = sd();
    var players = side && side.players;
    if (!players) return;
    if (!players.self && !players.other) return;
    document.getElementById("players-card").hidden = false;
    var box = document.getElementById("players");
    while (box.firstChild) box.removeChild(box.firstChild);
    [["我方", players.self, players.heroAttrs], ["敌方", players.other, null]].forEach(function (pair) {
      var title = pair[0], p = pair[1], attrs = pair[2];
      var card = el("div", "player");
      card.appendChild(el("h3", null, title));
      if (!p) {
        card.appendChild(el("div", "empty", "未读到该方队伍数据"));
        box.appendChild(card);
        return;
      }
      var who = el("div", "who");
      who.appendChild(document.createTextNode(String(p.name || p.sName || ("roleId " + (p.roleId !== undefined ? p.roleId : "?")))));
      var bits = [];
      if (p.level !== undefined) bits.push("Lv" + p.level);
      if (p.fightPower !== undefined) bits.push("战力 " + p.fightPower);
      if (p.roleId !== undefined) bits.push("ID " + p.roleId);
      if (bits.length) {
        var muted = el("span", "muted", "  · " + bits.join(" · "));
        who.appendChild(muted);
      }
      card.appendChild(who);

      function section(label, items, render) {
        if (!items || !items.length) return;
        card.appendChild(el("h4", null, label));
        var ul = el("ul");
        items.forEach(function (item) { ul.appendChild(el("li", null, render(item))); });
        card.appendChild(ul);
      }
      section("天书", p.books, function (b) { return b.name + (b.level ? " Lv" + b.level : ""); });
      section("觉醒分支", p.awakenings, function (a) {
        return a.bookName + " · " + a.branchName + " Lv" + a.level + "（" + a.pathName + "）";
      });
      section("鬼仆", p.pets, function (pet) {
        return (pet.name || ("鬼仆" + pet.cfgId)) + (pet.skillLevel ? " 技能Lv" + pet.skillLevel : "");
      });
      section("三尸", p.desires, function (d) { return d.name; });
      section("脸谱", p.equipment, function (e) {
        return (e.name || ("装备" + e.configId)) + (e.level ? " Lv" + e.level : "");
      });

      if (attrs && attrs.length) {
        card.appendChild(el("h4", null, "局内属性"));
        var grid = el("div", "attrs");
        attrs.forEach(function (a) {
          grid.appendChild(el("span", null, a.label));
          grid.appendChild(el("span", null, String(a.value)));
        });
        card.appendChild(grid);
      }
      box.appendChild(card);
    });
  }

  // ── 拆解图 ──
  function levelItems() {
    var side = sd();
    if (!side) return [];
    var items = [];
    if (state.level === "cat") {
      (side.curves || []).forEach(function (c) {
        if (c.key === "__total") return;
        items.push({ id: "cat:" + c.key, label: c.label, meta: "", dmg: c.dmg,
                     all: c.perSecond || [], boss: c.bossPerSecond || [], cum: c.cumulative || [] });
      });
    } else if (state.level === "book") {
      (side.books || []).forEach(function (b) {
        items.push({ id: "book:" + b.bookId, label: b.name || ("天书" + b.bookId), meta: "", dmg: b.dmg,
                     all: b.perSecond || [], boss: b.bossPerSecond || [], cum: b.cumulative || [] });
      });
    } else if (state.level === "branch") {
      (side.branches || []).forEach(function (b) {
        items.push({ id: "branch:" + b.branchId,
                     label: (b.bookName ? b.bookName + " · " : "") + (b.name || ("分支" + b.branchId)),
                     meta: "Lv" + b.level + " " + (b.pathName || ""), dmg: b.dmg,
                     all: b.perSecond || [], boss: b.bossPerSecond || [], cum: b.cumulative || [] });
      });
    } else {
      (side.skills || []).forEach(function (s) {
        var meta = [];
        if (s.bookName) meta.push(s.bookName);
        if (s.branchName) meta.push(s.branchName + " Lv" + s.branchLevel);
        if (s.origin) meta.push(s.origin);
        if (s.kind) meta.push(s.kind);
        items.push({ id: "skill:" + s.skillId, label: s.name || ("技能" + s.skillId),
                     meta: meta.join(" · "), dmg: s.dmg,
                     all: s.perSecond || [], boss: s.bossPerSecond || [], cum: s.cumulative || [] });
      });
    }
    items.forEach(function (it, i) { it.slot = i < MAX_SERIES ? (i + 1) : null; });
    return items;
  }

  function visibleSeries(items) {
    var out = [];
    items.forEach(function (it) {
      if (!it.slot || !state.selected[it.id]) return;
      var raw = state.scope === "boss" ? it.boss : it.all;
      var values = state.view === "cum" ? (state.scope === "boss" ? cumulative(raw) : it.cum) : raw;
      out.push({ item: it, values: values, slot: it.slot, label: it.label });
    });
    return out;
  }

  function renderMain() {
    var items = levelItems();
    var shown = visibleSeries(items);
    var side = sd() || {};
    var viewName = state.view === "cum" ? "累计伤害" : "每秒伤害";
    var scopeName = state.scope === "boss" ? "（仅对 BOSS）" : "（全部目标）";
    var sideName = state.side === "other" ? "敌方" : "我方";
    document.getElementById("chart-title").textContent = sideName + " · " + viewName + scopeName;
    document.getElementById("chart-sub").textContent =
      "每格 1s，共 " + shown.length + " 条曲线" + (side.truncated ? "；原始事件已截断，曲线仍完整" : "");

    drawLine(document.getElementById("svg-main"), document.getElementById("tip-main"), shown, { height: 320 });

    var note = document.getElementById("cap-note");
    if (items.length > MAX_SERIES) {
      note.hidden = false;
      note.textContent = "本层共 " + items.length + " 项，配色槽位只有 8 个：第 9 项及之后不参与绘图（不生成新颜色），请用数据表查看或换一层级。";
    } else {
      note.hidden = true;
    }
    renderLegend(items);
    renderTable(shown);
  }

  function renderLegend(items) {
    var box = document.getElementById("legend");
    while (box.firstChild) box.removeChild(box.firstChild);
    items.forEach(function (it) {
      if (!it.slot) return;
      var chip = el("label", "chip" + (state.selected[it.id] ? "" : " off"));
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = !!state.selected[it.id];
      cb.addEventListener("change", function () {
        state.selected[it.id] = cb.checked;
        renderMain();
        syncTree();
      });
      var key = el("span", "key");
      key.style.background = "var(--series-" + it.slot + ")";
      chip.appendChild(cb);
      chip.appendChild(key);
      chip.appendChild(el("span", "nm", it.label));
      chip.appendChild(el("span", "chip-val", fmt(it.dmg)));
      box.appendChild(chip);
    });
  }

  function renderTable(shown) {
    var card = document.getElementById("table-card");
    if (!document.getElementById("show-table").checked) { card.hidden = true; return; }
    card.hidden = false;
    var table = document.getElementById("table");
    while (table.firstChild) table.removeChild(table.firstChild);
    var n = 0;
    shown.forEach(function (s) { n = Math.max(n, s.values.length); });
    var thead = document.createElement("thead");
    var hr = document.createElement("tr");
    hr.appendChild(el("th", null, "时间"));
    shown.forEach(function (s) { hr.appendChild(el("th", null, s.label)); });
    hr.appendChild(el("th", null, "合计"));
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    for (var i = 0; i < n; i++) {
      var tr = document.createElement("tr");
      tr.appendChild(el("td", null, i + "s"));
      var sum = 0;
      shown.forEach(function (s) {
        var v = s.values[i] || 0;
        sum += v;
        tr.appendChild(el("td", null, String(Math.round(v))));
      });
      tr.appendChild(el("td", null, String(Math.round(sum))));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
  }

  function renderTree() {
    var side = sd();
    var box = document.getElementById("drill");
    while (box.firstChild) box.removeChild(box.firstChild);
    if (!side) return;
    (side.books || []).forEach(function (b) {
      box.appendChild(treeRow("tree-l1", "book:" + b.bookId, b.name || ("天书" + b.bookId), "", b.dmg));
      (b.branches || []).forEach(function (br) {
        box.appendChild(treeRow("tree-l2", "branch:" + br.branchId, br.name || ("分支" + br.branchId),
          "Lv" + br.level + " " + (br.pathName || ""), br.dmg));
      });
      var rest = (side.skills || []).filter(function (s) {
        return s.bookId === b.bookId && !s.branchId;
      });
      rest.forEach(function (s) {
        box.appendChild(treeRow("tree-l3", "skill:" + s.skillId, s.name,
          (s.origin || "") + (s.kind ? " · " + s.kind : ""), s.dmg));
      });
    });
    var loose = (side.skills || []).filter(function (s) { return !s.bookId; });
    if (loose.length) {
      box.appendChild(el("div", "tree-row tree-l1", "其它技能（普攻 / 符咒 / 鬼仆 / 三尸 …）"));
      loose.forEach(function (s) {
        box.appendChild(treeRow("tree-l3", "skill:" + s.skillId, s.name,
          (s.origin || s.catLabel || "") + (s.kind ? " · " + s.kind : ""), s.dmg));
      });
    }
    syncTree();
  }

  function treeRow(cls, id, name, meta, dmg) {
    var row = el("div", "tree-row " + cls);
    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.dataset.id = id;
    cb.addEventListener("change", function () {
      state.selected[id] = cb.checked;
      renderMain();
      syncTree();
    });
    row.appendChild(cb);
    row.appendChild(el("span", "nm", name));
    if (meta) row.appendChild(el("span", "tag", meta));
    row.appendChild(el("span", "val", fmt(dmg)));
    return row;
  }

  function syncTree() {
    var prefix = state.level + ":";
    var boxes = document.querySelectorAll("#drill input[type=checkbox]");
    for (var i = 0; i < boxes.length; i++) {
      var cb = boxes[i];
      var mine = cb.dataset.id.indexOf(prefix) === 0;
      cb.disabled = !mine;
      cb.checked = mine ? !!state.selected[cb.dataset.id] : false;
      cb.style.visibility = mine ? "" : "hidden";
    }
  }

  function selectLevelAll() {
    var items = levelItems();
    state.selected = {};
    items.forEach(function (it) { if (it.slot) state.selected[it.id] = true; });
    renderMain();
    syncTree();
  }

  function init() {
    var side = sd() || {};
    document.getElementById("meta-sub").textContent =
      "World #" + (side.instanceId !== undefined ? side.instanceId : "?") +
      " · 战斗类型 " + (side.battleType !== undefined ? side.battleType : "?") +
      " · seed " + (side.seed !== undefined ? side.seed : "?") +
      " · 时长 " + (Number(side.duration) || 0).toFixed(1) + "s" +
      " · " + (side.eventCount || 0) + " 条伤害事件";

    var stats = document.getElementById("stats");
    function tile(cls, label, value, hint) {
      var d = el("div", "tile" + (cls ? " " + cls : ""));
      d.appendChild(el("span", "label", label));
      d.appendChild(el("span", "value", value));
      if (hint) d.appendChild(el("span", "hint", hint));
      return d;
    }
    if (DATA.pvp) {
      var gap = (DATA.pvp.finalSelfScore || 0) - (DATA.pvp.finalOtherScore || 0);
      stats.appendChild(tile("hero", "我方分数", String((DATA.pvp.finalSelfScore || 0).toFixed(1)),
        gap >= 0 ? "领先 " + gap.toFixed(1) : "落后 " + (-gap).toFixed(1)));
      stats.appendChild(tile("", "敌方分数", String((DATA.pvp.finalOtherScore || 0).toFixed(1)), ""));
      stats.appendChild(tile("", "胜利线", String(DATA.pvp.winLine || 0), "先到者胜"));
      stats.appendChild(tile("", "战斗时长", (Number(side.duration) || 0).toFixed(1) + "s", ""));
    } else {
      stats.appendChild(tile("hero", "总伤害", fmt(side.totalDamage || 0), ""));
      stats.appendChild(tile("", "对敌方英雄", fmt(side.bossDamage || 0), ""));
      stats.appendChild(tile("", "事件数", String(side.eventCount || 0), ""));
      stats.appendChild(tile("", "战斗时长", (Number(side.duration) || 0).toFixed(1) + "s", ""));
    }

    renderPvp();
    renderAttrs();
    renderPlayers();
    selectLevelAll();
    renderTree();

    var zeroes = ((side.activeBranches) || []).filter(function (a) { return !a.dealtDamage; });
    if (zeroes.length) {
      document.getElementById("zero-card").hidden = false;
      var ul = document.getElementById("zero-list");
      zeroes.forEach(function (z) {
        var li = document.createElement("li");
        li.appendChild(document.createTextNode(z.bookName + " · " + z.branchName));
        li.appendChild(el("span", "meta", "  Lv" + z.level + " · " + z.pathName +
          " · skillIds [" + (z.skillIds || []).join(", ") + "]"));
        ul.appendChild(li);
      });
    }

    document.getElementById("side").addEventListener("change", function (e) {
      state.side = e.target.value;
      selectLevelAll();
      renderPlayers();
      renderTree();
    });
    document.getElementById("level").addEventListener("change", function (e) {
      state.level = e.target.value;
      selectLevelAll();
      syncTree();
    });
    document.getElementById("view").addEventListener("change", function (e) {
      state.view = e.target.value;
      renderMain();
    });
    document.getElementById("scope").addEventListener("change", function (e) {
      state.scope = e.target.value;
      renderMain();
    });
    document.getElementById("show-table").addEventListener("change", renderMain);
    document.getElementById("sel-all").addEventListener("click", function () {
      selectLevelAll();
      syncTree();
    });
    document.getElementById("sel-none").addEventListener("click", function () {
      state.selected = {};
      renderMain();
      syncTree();
    });
    document.getElementById("theme-toggle").addEventListener("click", function () {
      var cur = document.documentElement.getAttribute("data-theme");
      var dark = cur ? cur === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
      document.documentElement.setAttribute("data-theme", dark ? "light" : "dark");
    });
    window.addEventListener("resize", renderMain);
  }

  init();
})();
</script>
</body>
</html>
"""
