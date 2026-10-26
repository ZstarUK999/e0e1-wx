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
  .book-comparison { margin:8px 0; border:1px solid #e5e7eb; border-radius:8px; padding:8px 10px; }
  .book-comparison summary { cursor:pointer; }
  .book-comparison summary:hover { background:rgba(127,127,127,.06); }
  .book-main-levels { display:block; margin:5px 0 0 18px; line-height:1.8; }
  .book-level { display:inline-block; margin-right:12px; }
  .book-higher { color:#e5484d; }
  .book-lower { color:#169b63; }
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
  .bonus-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:12px; margin:14px 0; }
  .formula-comparison-body { max-height:none; overflow:visible; width:100%; }
  .formula-comparison-body table { table-layout:fixed; }
  .formula-comparison-body th, .formula-comparison-body td { white-space:normal; overflow-wrap:anywhere; }
  .formula-comparison-body .bonus-value { white-space:normal; }
  .formula-comparison-body details { max-height:none; overflow:visible; }
  .formula-name { font:inherit; font-size:18px; font-weight:700; background:none; border:0; padding:3px 5px; border-radius:4px; cursor:pointer; }
  .formula-name::before { content:"▸"; display:inline-block; margin-right:6px; transition:transform .16s ease; }
  .formula-name[aria-expanded="true"]::before { transform:rotate(90deg); }
  .formula-name:hover { background:rgba(127,127,127,.12); text-decoration:underline; }
  .formula-name:focus-visible { outline:2px solid currentColor; outline-offset:2px; }
  .formula-active { border-color:#e5484d; color:#e5484d; font-weight:700; }
  .formula-selected-zone { outline:1px solid var(--border); }
  .formula-plot { cursor:pointer; }
  .formula-plot .series-line { transition:stroke-width .18s ease; }
  .formula-plot:hover .series-line { stroke-width:4; }
  .formula-plot:hover .crosshair { stroke:#e5484d; stroke-width:3; }
  #factor-details > summary { font-size:19px; font-weight:700; padding:12px; border:2px solid #aeb8c5; border-radius:7px; cursor:pointer; }
  .formula-number { position:relative; display:inline-block; }
  .formula-number.has-variation { cursor:help; border-bottom:1px dashed currentColor; }
  .formula-hover-panel { display:none; position:absolute; top:100%; left:0; z-index:200; width:480px; max-width:80vw; max-height:360px; overflow:auto; padding:14px; background:var(--card,white); color:var(--text,#222); border:1px solid #bbc2cc; border-radius:8px; box-shadow:0 5px 20px #0003; text-align:left; font-size:14px; font-weight:400; white-space:normal; }
  .formula-number:hover > .formula-hover-panel,.formula-number:focus > .formula-hover-panel,.formula-number:focus-within > .formula-hover-panel { display:block; }
  .bonus-compare td:last-child .formula-hover-panel { left:auto; right:0; }
  .formula-parts { margin:12px 12px 26px 30px; padding:12px 16px; border-left:4px solid #aeb8c5; border-radius:6px; background:rgba(127,127,127,.035); }
  .formula-zone-row > td { border-top:2px solid #aeb8c5; padding-top:16px; padding-bottom:16px; background:rgba(127,127,127,.045); }
  .formula-drill-row > td { padding:0; border-bottom:2px solid #aeb8c5; }
  .formula-detail-table { font-size:14px; }
  .formula-equation { padding:8px 0; font-weight:600; }

  .formula-reveal { animation:formula-reveal .22s ease-out; }
  @keyframes formula-reveal { from {opacity:0; transform:translateY(6px);} to {opacity:1; transform:translateY(0);} }
  @media (prefers-reduced-motion:reduce) { .formula-reveal {animation:none;} .formula-plot .series-line {transition:none;} }
  .bonus-compare td { cursor:help; }
  .bonus-lower { color:#169b63; font-weight:600; }
  .bonus-diff { color:#111; background:#f5f5f5; font-weight:800; }
  .bonus-winner { color:#e5484d; font-weight:600; }
  .bonus-value { margin-left:10px; font-variant-numeric:tabular-nums; white-space:nowrap; }
  .bonus-compare td { vertical-align:top; width:40%; }
  .bonus-compare td:nth-child(2) { width:20%; text-align:center; }
  .bonus-compare details { font-size:12px; margin-top:4px; }
  .bonus-group { text-align:left; background:var(--bg-secondary); }
  .bonus-panel { border:1px solid var(--border); border-radius:8px; padding:12px; min-width:0; }
  .bonus-panel h3 { margin:0 0 8px; font-size:14px; }
  .bonus-panel p { font-size:12px; line-height:1.8; margin:4px 0; }
  .factor-entry { border-top:1px solid var(--border); padding:10px 0; }
  .factor-entry summary { cursor:pointer; font-size:13px; line-height:1.8; }
  .factor-sources { font-size:12px; line-height:1.7; min-width:240px; }
  .factor-change { font-size:12px; color:var(--text-secondary); }
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

    <details class="card" id="flag-card" hidden>
      <summary>战旗伤害 · 点击查看独立统计</summary>
      <p class="note">战旗伤害单独展示，不计入主图、伤害汇总和来源排名。原始记录及游戏分数保留。</p>
      <div id="flag-summary"></div>
      <div class="plot"><svg id="svg-flag" role="img" aria-label="双方战旗每秒伤害"></svg><div class="tooltip" id="tip-flag" hidden></div></div>
    </details>

    <section class="card" id="leifa-card" hidden>
      <h2>雷法尊者 · 独立伤害统计</h2>
      <p class="note" id="leifa-summary"></p>
    </section>

    <section class="card" id="players-card" hidden>
      <h2>对战双方</h2>
      <p class="note">从战斗数据里读到的双方信息；字段按实际下发情况显示，缺失即为空。</p>
      <div class="players" id="players"></div>
    </section>

    <section class="card" id="initial-attrs-card">
      <h2>开战初始属性对比</h2>
      <p class="note" id="initial-attrs-note">读取首次伤害前的双方属性快照。</p>
      <div class="formula-comparison-body" id="initial-attrs-table"></div>
    </section>

    <section class="card" id="attr-card" hidden>
      <h2>伤害乘区趋势</h2>
      <div class="filters">
        <label>计算方式 <select id="formula-type"><option value="book">天书伤害</option><option value="attack">普攻伤害</option><option value="card">符咒伤害</option><option value="skill">其他技能伤害</option></select></label>
        <label>具体技能 <select id="formula-skill"></select></label>
      </div>
      <div class="legend" id="formula-zone-picks"></div>
      <p class="note" id="formula-chart-note"></p>
      <div class="plot formula-plot"><svg id="svg-attr" role="button" tabindex="0" aria-label="点击某秒查看伤害乘区对比"></svg><div class="tooltip" id="tip-attr" hidden></div></div>
      <section id="formula-comparison" class="formula-reveal" hidden>
        <h3 id="formula-selected-sec"></h3>
        <button type="button" class="btn" id="open-damage-history" aria-controls="factor-details" aria-expanded="false">展开全部逐秒伤害明细（页面底部）</button>
        <p class="note">默认显示本秒最高值；数值变化时可悬停查看实际贡献和逐次结算。点击乘区展开属性，属性下可查看来源。红色为较高方，绿色为较低方，中间为我方减敌方；相等和缺失不标色。普攻不列天书专属属性，实际额外修正单独保留。</p>
        <div class="formula-comparison-body" id="bonus-summary"></div>
      </section>
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
    <details class="card" id="factor-details">
      <summary id="damage-history-summary">展开全部逐秒伤害明细 · 点击这里</summary>
      <p class="note">仅记录命中 BOSS 时的实际乘区和 Buff。同秒内不同状态分别保留；无命中不推算，真伤和秒杀另行标记。</p>
      <label><input type="checkbox" id="factor-all-seconds" checked> 展示全部秒的乘区记录</label>
      <div id="factor-history"></div>
    </details>
  </div>
</div>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
(function () {
  "use strict";
  var RAW_DATA = JSON.parse(document.getElementById("payload").textContent);

  function flagSkills(side) {
    return ((side && side.skills) || []).filter(function(s) { return s.cat === "flag"; });
  }
  function flagInterval(side, start, end) {
    if (!side) return 0;
    var skills = flagSkills(side), ids = {};
    skills.forEach(function(s) { ids[s.skillId] = true; });
    if (side.events && side.events.length && !side.truncated) {
      return side.events.reduce(function(sum,e) {
        return sum + (e.boss && (e.cat === "flag" || ids[e.skill]) && e.t >= start && e.t < end ? e.dmg : 0);
      }, 0);
    }
    return skills.reduce(function(sum,s) {
      var curve=s.bossPerSecond || [];
      for(var sec=Math.floor(start);sec<Math.ceil(end);sec++) sum+=Number(curve[sec] || 0);
      return sum;
    },0);
  }
  // 仅生成展示副本，原始载荷、事件和游戏分数不变。
  function withoutFlags(raw) {
    var data=JSON.parse(JSON.stringify(raw));
    function clean(side) {
      if(!side) return;
      var flags=flagSkills(side), ids={};
      flags.forEach(function(s){ids[s.skillId]=true;});
      var flagCurve=(side.curves || []).find(function(c){return c.key==='flag';});
      var flagTotal=(side.categories || []).find(function(c){return c.key==='flag';});
      side.totalDamage=Math.max(0,(side.totalDamage || 0)-(flagTotal ? flagTotal.dmg : flags.reduce(function(n,s){return n+s.dmg;},0)));
      side.bossDamage=Math.max(0,(side.bossDamage || 0)-flags.reduce(function(n,s){return n+(s.bossPerSecond || []).reduce(function(a,b){return a+b;},0);},0));
      side.eventCount=Math.max(0,(side.eventCount || 0)-flags.reduce(function(n,s){return n+(s.hits || 0);},0));
      side.categories=(side.categories || []).filter(function(c){return c.key!=='flag';});
      side.curves=(side.curves || []).filter(function(c){return c.key!=='flag';});
      side.curves.forEach(function(c){
        if(c.key!=='__total' || !flagCurve) return;
        c.dmg=side.totalDamage;
        ['perSecond','bossPerSecond'].forEach(function(key){c[key]=(c[key] || []).map(function(v,i){return Math.max(0,v-((flagCurve[key] || [])[i] || 0));});});
        var sum=0;c.cumulative=c.perSecond.map(function(v){return sum+=v;});
      });
      side.skills=(side.skills || []).filter(function(s){return s.cat!=='flag';});
      side.events=(side.events || []).filter(function(e){return e.cat!=='flag' && !ids[e.skill];});
      ['perSecondTop','perSecondBossTop'].forEach(function(key){
        side[key]=(side[key] || []).map(function(rows){return rows.filter(function(r){return r.cat!=='flag' && !ids[r.skillId];});});
      });
    }
    clean(data);clean(data.other);
    var previous=0;
    if(data.pvp) (data.pvp.derived || []).forEach(function(d){
      var end=Number(d.t!==undefined ? d.t : d.sec);
      d.selfDmg=Math.max(0,d.selfDmg-flagInterval(raw,previous,end));
      d.otherDmg=Math.max(0,d.otherDmg-flagInterval(raw.other,previous,end));
      var sum=d.selfDmg+d.otherDmg;d.share=sum ? d.selfDmg/sum : null;
      previous=end;
    });
    return data;
  }
  var DATA = withoutFlags(RAW_DATA);
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
      var segments=[],points=[];
      for(var i=0;i<n;i++){
        if(opts.gaps && (s.values[i]===null || s.values[i]===undefined)){if(points.length)segments.push(points);points=[];continue;}
        points.push(xOf(i)+','+yOf(s.values[i] || 0));
      }
      if(points.length)segments.push(points);
      // 缺少命中只连接趋势，不补造逐秒倍率；tooltip 仍读取原始空值。
      if(opts.connectGaps){
        var previous=-1;
        for(var next=0;next<n;next++){
          if(s.values[next]===null || s.values[next]===undefined)continue;
          if(previous>=0 && next>previous+1){
            var bridge=svgEl('line',{class:'series-gap',x1:xOf(previous),y1:yOf(s.values[previous]),x2:xOf(next),y2:yOf(s.values[next]),'stroke-dasharray':'5 4','stroke-width':2});
            bridge.style.stroke='var(--series-'+s.slot+')';bridge.style.opacity='.65';svg.appendChild(bridge);
          }
          previous=next;
        }
      }
      segments.forEach(function(pts){
        var line=svgEl('polyline',{class:'series-line',points:pts.join(' ')});
        line.style.stroke='var(--series-'+s.slot+')';line.style.setProperty('--hover-stroke',s.slot===SELF_SLOT ? '#e5484d' : '#169b63');svg.appendChild(line);
      });
      var last=n-1;
      if(opts.gaps)while(last>=0 && (s.values[last]===null || s.values[last]===undefined))last--;
      if(last<0)return;
      var dot=svgEl('circle',{class:'series-dot',cx:xOf(last),cy:yOf(s.values[last] || 0),r:4});dot.style.fill='var(--series-'+s.slot+')';svg.appendChild(dot);
      if(series.length<=4){var lb=svgEl('text',{class:'end-label',x:xOf(last)+9,y:yOf(s.values[last] || 0)+4});lb.textContent=(opts.yFormat || fmt)(s.values[last] || 0);svg.appendChild(lb);}
    });

    // 十字准线：一次列出该时刻所有系列
    var hair = svgEl("line", { class: "crosshair", y1: PAD.t, y2: PAD.t + plotH });
    hair.style.display = "none";
    svg.appendChild(hair);
    var wrap = svg.parentNode;
    var lastTipIndex=-1;
    svg.onpointermove = function (ev) {
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
      if(idx!==lastTipIndex){
      lastTipIndex=idx;
      while (tip.firstChild) tip.removeChild(tip.firstChild);
      var headSec = (opts && opts.xLabels && opts.xLabels[idx] !== undefined) ? opts.xLabels[idx] : idx;
      tip.appendChild(el("div", "tt-head", headSec + "s"));
      var secondTotal=opts.percentTotals ? Number(opts.percentTotals[idx]) || 0 : series.reduce(function(sum,s){return sum+Math.max(0,Number(s.values[idx]) || 0);},0);
      function shareText(value,total){return total>0 ? ' · '+(100*value/total).toFixed(2)+'%' : ' · —';}
      series.forEach(function (s) {
        var row = el("div", "tt-row");
        var key = el("span", "tt-key");
        key.style.background = "var(--series-" + s.slot + ")";
        row.appendChild(key);
        row.appendChild(el("span", "tt-name", s.label));
        var value=s.values[idx];
        row.appendChild(el("span", "tt-val", value===null ? '未命中' : (opts.yFormat || fmt)(value || 0)+(opts.showPercent ? shareText(value || 0,secondTotal) : '')));
        if(s.notes && s.notes[idx]) row.appendChild(el('span','factor-change',s.notes[idx]));
        tip.appendChild(row);
        var changes=typeof s.changes==='function' ? s.changes(idx) : s.changes && s.changes[idx];
        if(changes)changes.forEach(function(line){tip.appendChild(el('div','factor-change',line));});
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
            var label = (item.book ? item.book + " · " : "") + item.name + (item.origin ? " · " + item.origin : "");
            row.appendChild(el("span", "tt-name", label));
            row.appendChild(el("span", "tt-val", (opts.yFormat || fmt)(item.dmg)+(opts.showPercent ? shareText(item.dmg,((series.find(function(s){return s.slot===src.slot;}) || {}).values || [])[idx] || 0) : '')));
            tip.appendChild(row);
          });
        });
      }
      if(opts.onSelect) tip.appendChild(el('div','tt-head','点击查看 '+headSec+'s 的乘区对比'));
      }
      var wr = wrap.getBoundingClientRect();
      var left = ev.clientX - wr.left + 14;
      if (left + tip.offsetWidth > wr.width) left = ev.clientX - wr.left - tip.offsetWidth - 14;
      tip.style.left = Math.max(0, left) + "px";
      tip.style.top = Math.min(Math.max(0, wr.height - tip.offsetHeight - 4), ev.clientY - wr.top - 12) + "px";
    };
    svg.onpointerleave = function () {
      tip.hidden = true;hair.style.display = "none";
    };
    svg.onclick=opts.onSelect ? function(ev){
      var rect=svg.getBoundingClientRect(),px=(ev.clientX-rect.left)/rect.width*W,best=0;
      for(var i=1;i<n;i++) if(Math.abs(xOf(i)-px)<Math.abs(xOf(best)-px)) best=i;
      opts.onSelect(best);
    } : null;
    svg.onkeydown=opts.onSelect ? function(ev){
      if(ev.key==='Enter' || ev.key===' '){ev.preventDefault();opts.onSelect(Math.max(0,opts.markerIndex || 0));}
    } : null;
  }

  // 曲线点表示前后采样之间的增量，来源必须取同一时间窗口，而不是该点之后一秒。
  function pvpIntervalSources(side, derived) {
    if (!side) return [];
    var previous = 0;
    return derived.map(function(point) {
      var end = Number(point.t !== undefined ? point.t : point.sec), start = previous;
      previous = end;
      var totals = {};
      function add(id,name,origin,book,dmg) {
        if (!(dmg > 0)) return;
        var row=totals[id] || (totals[id]={skillId:Number(id),name:name,origin:origin,book:book,dmg:0});
        row.dmg+=dmg;
      }
      if (side.events && side.events.length) {
        side.events.forEach(function(e) {
          if(e.boss && e.t>=start && e.t<end) add(e.skill,e.skillName,e.origin,e.bookName,e.dmg);
        });
      } else {
        (side.skills || []).forEach(function(skill) {
          var sum=0,curve=skill.bossPerSecond || [];
          for(var sec=Math.floor(start);sec<Math.ceil(end);sec++) sum+=Number(curve[sec]||0);
          add(skill.skillId,skill.name,skill.origin,skill.bookName,sum);
        });
      }
      return Object.keys(totals).map(function(id){return totals[id];}).sort(function(a,b){return b.dmg-a.dmg;}).slice(0,8);
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
    document.getElementById('pvp-note').textContent += ' 伤害曲线及占比已排除战旗；分数为游戏原始结果，包含战旗影响。';
    var tops = [];
    if (DATA.perSecondBossTop) tops.push({ label: "我方", slot: SELF_SLOT, bySecond: pvpIntervalSources(DATA, derived) });
    if (DATA.other && DATA.other.perSecondBossTop) {
      tops.push({ label: "敌方", slot: OTHER_SLOT, bySecond: pvpIntervalSources(DATA.other, derived) });
    }
    drawLine(document.getElementById("svg-dmg"), document.getElementById("tip-dmg"), [
      { label: "我方每秒伤害", slot: SELF_SLOT, values: derived.map(function (d) { return d.selfDmg; }) },
      { label: "敌方每秒伤害", slot: OTHER_SLOT, values: derived.map(function (d) { return d.otherDmg; }) }
    ], { height: 200, xLabels: seconds, topSources: tops, topN: 5, showPercent:true });

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

  function bonusValue(attrs,key) {
    var value=attrs && attrs[key];
    return value===undefined || value===null || !Number.isFinite(Number(value)) ? null : Number(value);
  }
  function bothZero(left,right,key) {
    return bonusValue(left,key)===0 && bonusValue(right,key)===0;
  }
  function currentAttrSnapshot() {
    var rows=DATA.pvp && DATA.pvp.attrSeconds || [];
    return rows[typeof attrState!=='undefined' ? attrState.sec : 0] || {};
  }
  function visibleAttrMeta(pvp) {
    var snapshot=currentAttrSnapshot();
    return (pvp.attrMeta || []).filter(function(m){return !bothZero(snapshot.self,snapshot.other,m.key);});
  }
  function bonusSum(attrs,keys) {
    var sum=0;
    for(var i=0;i<keys.length;i++){var value=bonusValue(attrs,keys[i]);if(value===null) return null;sum+=value;}
    return sum;
  }
  function bonusPct(value) {return value===null ? '未采集' : pctText(value)+'%';}
  function bonusMultiplier(value) {return value===null || value===undefined ? '未采集' : '×'+Number(value).toFixed(4);}
  function briefSkillName(name){
    var text=String(name || ''),book=/【[^】]*天书】/.test(text);
    text=text.replace(/【[^】]*】/g,'').replace(/[-—·]?lv\d+$/i,'').replace(/^[-· ]+|[-· ]+$/g,'');
    if(book)text=text.replace(/觉醒(?:初阶)?/g,'');
    return text.replace(/[-—]+/g,'·');
  }
  function buffDisplayName(id){
    var reference=(((DATA.buffCatalog || {}).buffs || {})[String(id)]) || {};
    if(reference.displayName)return reference.displayName;
    if(reference.sources && reference.sources.length){var names=Array.from(new Set(reference.sources.map(briefSkillName)));return names.slice(0,2).join(' / ')+(names.length>2 ? '等来源' : '');}
    var tags={1:'冰冻',2:'眩晕',3:'迟缓',7:'霸体',23:'高级霸体'};
    if(tags[reference.tag])return tags[reference.tag]+'状态';
    if(reference.attributes && reference.attributes.length)return reference.attributes.map(function(a){return a.name;}).join('、')+'状态';
    if(reference.effects && reference.effects.some(function(effect){return /：DMG\(/.test(effect);}))return '周期伤害状态';
    return '未解析状态';
  }
  function buffSourceLabel(raw){
    var label=String(raw).replace('（服务端合并，未拆装备/养成）','').replace(/^(Buff：.+?) · (.+?)(（\d+层）)/,'$1$3；关联技能：$2');
    var match=label.match(/^Buff[： :]+(\d+)(（\d+层）)?/);if(!match)return label;
    var name=buffDisplayName(match[1]),text='Buff：'+name+' [ID '+match[1]+']'+(match[2] || '');
    var reference=(((DATA.buffCatalog || {}).buffs || {})[String(match[1])]) || {};
    if(reference.triggerDescription)text+='；'+reference.triggerDescription;
    var related=label.match(/；关联技能：([^；]+)/);
    if(!reference.suppressRelatedSkill && related && briefSkillName(related[1])!==name)text+='；关联技能：'+related[1];
    return text;
  }
  function briefSourceName(raw){
    var match=String(raw).match(/^Buff[： :]+(\d+)/);
    if(match){var reference=(((DATA.buffCatalog || {}).buffs || {})[String(match[1])]) || {};return buffDisplayName(match[1])+(reference.triggerDescription ? '（'+reference.triggerDescription+'）' : '');}
    return briefSkillName(String(raw).replace(/^技能：/,''));
  }
  function bossContributionLabel(key,label,value){
    var names={105:'普通伤害',119:'天书',120:'符咒',124:'最终伤害',134:'法器',709:'普攻'};
    var name=names[key] || String(label).replace(/减伤|减免|抵抗/g,'');
    return 'BOSS'+name+(value>0 ? '易伤收益' : value<0 ? '减伤抵扣' : '受击修正');
  }
  function bonusSourceLines(attrs,sources,keys,prefix,peer) {
    var lines=[];
    keys.forEach(function(key){
      if(bothZero(attrs,peer,key)) return;
      var value=bonusValue(attrs,key);if(value===null) return;
      var meta=attrMetaOf(DATA.pvp || {},key), rows=sources && sources[key];
      var label=(prefix || '')+meta.label+' = '+fmtAttr(meta,value);
      if(rows && rows.length) label+='；'+rows.map(function(r){return buffSourceLabel(r.label)+' '+fmtAttr(meta,r.value);}).join('；');
      else label+= rows ? '；当前无非零来源' : '；来源未采集';
      lines.push(label);
    });
    return lines;
  }
  function bonusComparisonRows(snapshot) {
    var self=snapshot.self || {},other=snapshot.other || {},pvp=DATA.pvp || {},used={};
    var groups=[],group;
    function start(label){group={label:label,rows:[]};groups.push(group);}
    function row(label,keys,percent,read,kind){
      if(keys.length && keys.every(function(key){return bothZero(self,other,key);})) return;
      var get=read || function(attrs){return bonusSum(attrs,keys);};
      group.rows.push({label:label,keys:keys,percent:percent,kind:kind,self:get(self,'self'),other:get(other,'other')});
    }
    function attr(key,label,percent){
      used[String(key)]=true;
      var meta=attrMetaOf(pvp,key);
      row(label || meta.label,[key],percent===undefined ? !!meta.percent : percent);
    }
    start('攻击');
    attr(1,'攻击',false);attr(2,'基础攻击',false);attr(19,'PVP固定攻击',false);
    row('攻击加成合计',[3,20],true);attr(3,'攻击加成',true);attr(20,'PVP攻击加成',true);
    start('通用与最终增伤');
    [[104,'普通增伤'],[105,'普通减伤'],[117,'PVP增伤'],[118,'PVP减伤'],['finalPvp','对抵后PVP增伤'],
     [123,'最终增伤'],[129,'PVP最终增伤'],[124,'最终减伤'],[125,'主线增伤'],[126,'主线减伤'],
     [1002,'护盾转增伤比例'],[1003,'被控减伤']].forEach(function(r){attr(r[0],r[1],true);});
    row('最终增伤合计',[123,129],true);
    row('通用乘区对抵参考',[104,105,117,118,123,129,124],false,function(attrs,side){
      var opponent=side==='self' ? other : self,context=snapshot[side+'Context'] || {};
      var dmg=bonusValue(attrs,104),red=bonusValue(opponent,105),pvpAdd=bonusValue(attrs,117);
      var pvpRed=context.opponentPvpRed!==undefined ? context.opponentPvpRed : bonusValue(opponent,118);
      var final=bonusSum(attrs,[123,129]),finalRed=bonusValue(opponent,124);
      return [dmg,red,pvpAdd,pvpRed,final,finalRed].some(function(v){return v===null;}) ? null :
        Math.max(.25,1+dmg-red)*Math.max(.5,1+pvpAdd-pvpRed)*Math.max(.25,1+final-finalRed);
    },'multiplier');
    start('天书、首领与技能类型增伤（同一类型乘区内相加，按命中条件生效）');
    [[115,'天书增伤'],[119,'天书减伤'],[109,'首领增伤'],[108,'精英增伤'],[127,'首领/精英通用增伤'],[128,'首领/精英通用减伤'],
     [116,'符咒增伤'],[120,'符咒减伤'],[708,'普攻增伤'],[709,'普攻减伤'],[131,'鬼仆增伤'],[133,'法器增伤'],[134,'法器减伤'],
     [110,'对空增伤'],[111,'对地增伤'],[113,'挑战增伤（目标生命>80%）'],[114,'审判增伤（目标生命<20%）'],
     [233,'紫天书增伤'],[234,'紫天书减伤'],[235,'橙天书增伤'],[236,'橙天书减伤'],[237,'红天书增伤'],[238,'红天书减伤']].forEach(function(r){attr(r[0],r[1],true);});
    start('法术暴击与普通暴击（触发条件和暴击伤害分开比较）');
    [[106,'法术暴击率'],[107,'法术暴击伤害'],[132,'法术暴击抵抗'],[130,'法术暴击伤害抵抗'],
     [101,'普通暴击率'],[102,'普通暴击伤害'],[103,'普通暴击抵抗'],[601,'鬼仆暴击率'],[602,'鬼仆暴击伤害']].forEach(function(r){attr(r[0],r[1],true);});
    ['火','水','风','土'].forEach(function(name,i){
      start(name+'系属性伤害');
      attr(201+i,name+'系伤害加成',true);attr(205+i,name+'系减伤',true);
      attr(209+i,name+'系天书增伤',true);attr(213+i,name+'系天书减伤',true);
      row(name+'系天书元素区合计',[201+i,209+i],true);
      attr(225+i,name+'系符咒增伤',true);attr(229+i,name+'系符咒减伤',true);
      attr(217+i,name+'系法术暴击伤害',true);attr(221+i,name+'系法术暴击伤害抵抗',true);
    });
    start('赛季与致命一击');
    [[200103,'赛季最终增伤'],[200104,'赛季最终减伤'],[200105,'致命一击率'],[200106,'致命一击率抵抗'],
     [200107,'致命一击伤害'],[200108,'致命一击伤害抵抗'],[200109,'群攻致命一击率'],[200110,'群攻致命一击率抵抗'],
     [200111,'群攻致命一击伤害'],[200112,'群攻致命一击伤害抵抗']].forEach(function(r){attr(r[0],r[1],true);});
    if(snapshot.selfContext && snapshot.selfContext.stamina || snapshot.otherContext && snapshot.otherContext.stamina){
      [['skillDamage','血月耐力：技能系数'],['finalDamage','血月耐力：最终伤害']].forEach(function(r){
        row(r[1],[],false,function(attrs,side){var context=snapshot[side+'Context'];return context && context.stamina ? context.stamina[r[0]] : null;},'multiplier');
      });
    }
    start('其他属性');
    (pvp.attrMeta || []).forEach(function(meta){if(!used[String(meta.key)]) attr(meta.key,meta.label,meta.percent);});
    return groups.filter(function(g){return g.rows.length;});
  }
  function renderBonusSummary(snapshot) {
    var box=document.getElementById('bonus-summary');while(box.firstChild) box.removeChild(box.firstChild);
    var table=el('table','bonus-compare'),head=el('thead'),header=el('tr');
    ['我方','差值（我方 − 敌方）','敌方'].forEach(function(label){header.appendChild(el('th',null,label));});head.appendChild(header);table.appendChild(head);
    var body=el('tbody');
    bonusComparisonRows(snapshot).forEach(function(group){
      var title=el('tr'),cell=el('th','bonus-group',group.label);cell.colSpan=3;title.appendChild(cell);body.appendChild(title);
      group.rows.forEach(function(row){
        var tr=el('tr'),a=row.self,b=row.other,delta=a===null || b===null ? null : a-b;
        function value(v){return v===null ? '—（未采集）' : row.kind==='multiplier' ? bonusMultiplier(v) : row.percent ? bonusPct(v) : fmt(v);}
        function sideCell(side,v,wins){
          var cell=el('td'),cut=row.label.indexOf('（'),shortName=cut<0 ? row.label : row.label.slice(0,cut);
          var name=el('span',wins ? 'bonus-winner' : (delta!==null && delta!==0 ? 'bonus-lower' : ''),shortName);cell.appendChild(name);
          if(cut>=0) cell.appendChild(el('span',null,row.label.slice(cut)));
          cell.appendChild(el('span','bonus-value',value(v)));
          var attrs=snapshot[side] || {},peer=snapshot[side==='self' ? 'other' : 'self'] || {};
          var lines=bonusSourceLines(attrs,snapshot[side+'Sources'],row.keys,'',peer);
          if(!lines.length) lines.push(v===null ? '该属性或组成项未采集，无法追溯来源。' : '该项来源未采集。');
          if(row.label==='通用乘区对抵参考') {
            lines.unshift('三个通用倍率分别对抵对方减伤并应用客户端倍率下限，再相乘。');
            lines=lines.concat(bonusSourceLines(peer,snapshot[(side==='self' ? 'other' : 'self')+'Sources'],[105,118,124],'对方抵扣：',attrs));
            var ctx=snapshot[side+'Context'];
            if(ctx && ctx.opponentPvpRed!==undefined) lines.push('PVP减伤实际取对局指标：'+bonusPct(ctx.opponentPvpRed));
          }
          if(row.label.indexOf('血月耐力')===0){var stamina=snapshot[side+'Context'];if(stamina && stamina.stamina) lines=['来源：血月耐力 '+stamina.stamina.energy+' 对应的游戏配置'];}
          cell.title=(side==='self' ? '我方 · ' : '敌方 · ')+row.label+'\n'+lines.join('\n');
          if(lines.length){var sources=el('details');sources.appendChild(el('summary',null,'来源'));lines.forEach(function(line){sources.appendChild(el('p','note',line));});cell.appendChild(sources);}
          return cell;
        }
        tr.appendChild(sideCell('self',a,delta!==null && delta>0));
        var difference=delta===null ? '—' : (delta>0 ? '+' : '')+(row.percent ? pctText(delta)+'个百分点' : row.kind==='multiplier' ? delta.toFixed(4) : fmt(delta));
        var middle=el('td','attr-delta bonus-diff',difference),opponentCell=sideCell('other',b,delta!==null && delta<0);
        middle.title='差值 = 我方 − 敌方'+(row.percent ? '（百分点）' : '')+'\n'+tr.children[0].title+'\n\n'+opponentCell.title;
        tr.appendChild(middle);tr.appendChild(opponentCell);body.appendChild(tr);
      });
    });
    table.appendChild(body);box.appendChild(table);
    box.appendChild(el('p','note','红色标识较高一方，绿色标识较低一方；相等或缺失不标色。百分比差值为百分点。通用乘区参考不包含元素、类型、暴击和条件效果，实际结算见下方命中记录。'));
  }

  // 同一秒有不同条件/来源时保留多个状态；每条变化与该技能针对同一目标的前一次实际命中相比。
  function factorRowsAt(side,sec,all) {
    return ((side && side.factorRows) || []).filter(function(row){return row.boss===true && (all || row.sec===sec);});
  }
  function previousFactor(side,row) {
    var previous=null,rows=(side && side.factorRows) || [];
    for(var i=0;i<rows.length;i++) {
      var candidate=rows[i];
      if(candidate===row) break;
      if(candidate.skillId===row.skillId && candidate.sourceId===row.sourceId && candidate.targetId===row.targetId && (!previous || candidate.lastT>previous.lastT)) previous=candidate;
    }
    return previous;
  }
  var FACTOR_META = [
    ['attack','攻击值',[1,2,3,19,20],[]],['coefficient','技能系数',[705,706],[]],
    ['damage','普通增伤区',[104,125,1002],[105,126,1003]],
    ['element','元素增伤区',[201,202,203,204,209,210,211,212],[205,206,207,208,213,214,215,216]],
    ['type','类型区（下列四项相加后 +1）',[],[]],
    ['targetType','↳ 目标类型增伤',[108,109,110,111,127],[128]],['hp','↳ 高低血量条件',[113,114],[]],
    ['skillType','↳ 天书/符咒/其他技能类型',[115,116,131,133,225,226,227,228,233,235,237],[119,120,134,229,230,231,232,234,236,238]],
    ['attackBonus','↳ 普攻增伤',[708],[709]],['pvp','PVP乘区（最低 ×0.5）',[117],[118]],
    ['final','最终增伤区（最低 ×0.25）',[123,129],[124]],
    ['crit','普通暴击区',[101,102],[103]],['skillCrit','法术/鬼仆暴击区',[106,107,601,602,217,218,219,220],[130,132,221,222,223,224]],
    ['season','赛季最终增伤区',[200103],[200104]],['staminaSkill','血月耐力：技能系数',[],[]],['staminaFinal','血月耐力：最终伤害',[],[]],
    ['spCrit','致命一击区',[200105,200107,200109,200111],[200106,200108,200110,200112]]
  ];
  function bossBuffLines(buff){
    var catalog=DATA.buffCatalog || {},reference=(catalog.buffs || {})[String(buff.id)] || {};
    var sources=(buff.configuredSources || []).map(function(source){return (source.origin ? source.origin+' / ' : '')+source.name;}),lines=[];
    if(!sources.length && reference.sources && reference.sources.length)lines.push('配置参考来源：'+reference.sources.join('、')+'（'+catalog.version+'）');
    else if(sources.length)lines.push('配置来源：'+Array.from(new Set(sources)).join('、'));
    else lines.push('授予来源未解析；保留 Buff ID '+buff.id+' 供核对');
    var changes=buff.changes || [];
    changes.forEach(function(change){
      var meta=(reference.attributes || []).find(function(a){return Number(a.key)===Number(change.key);});
      var percent=change.percent,value=change.value;
      if(percent===null && meta){percent=meta.percent;if(percent)value/=10000;}
      var name=meta ? meta.name : change.name,amount=percent ? bonusPct(value) : percent===null ? String(value)+'（原始值）' : fmt(value);
      var usage=change.usage || '';
      if([105,119,120,124,205,206,207,208,213,214,215,216,229,230,231,232].indexOf(Number(change.key))>=0 && value<0)usage='降低 BOSS 减伤，提升对应伤害；已包含在实际乘区中';
      if(Number(change.key)===13)usage='移动速度状态，不是伤害增伤乘区';
      lines.push((change.zone || '状态属性')+'：'+name+' '+amount+(usage ? '；'+usage : ''));
    });
    if(!changes.length)(reference.attributes || []).forEach(function(change){
      var n=Number(change.expression),amount=Number.isFinite(n) ? (change.percent ? bonusPct(n/10000) : fmt(n)) : String(change.expression);
      lines.push('配置每层效果：'+change.name+' '+amount+'（非本次实测值，实际以运行时层数和状态为准）');
    });
    var tag=buff.tag || reference.tag,states={1:'冰冻',2:'眩晕',3:'迟缓',7:'霸体',23:'高级霸体'};
    if(states[tag])lines.push('控制状态：'+states[tag]+'；不作为固定伤害乘区');
    (buff.effectDescriptions || reference.effects || []).forEach(function(effect){
      var match=String(effect).match(/^(.+?)：DMG\((.*)\)$/);
      var coefficient=match && (match[2]==='dmg/2' ? '按来源技能伤害参数的50%计算' : match[2]==='dmg' ? '使用来源技能伤害参数' : '技能系数 '+match[2]);
      lines.push(match ? match[1]+'伤害，'+coefficient+'；独立伤害事件，不是固定增伤倍率' : '配置机制：'+effect+'（参数以实际技能上下文为准）');
    });
    if(!changes.length && !(reference.attributes || []).length && !(buff.effectDescriptions || reference.effects || []).length && !states[tag])lines.push('未采集到可解释的属性或机制，所属乘区未确认，暂不判断其伤害影响');
    return lines;
  }
  function bossBuffHeading(buff){
    var reference=(((DATA.buffCatalog || {}).buffs || {})[String(buff.id)]) || {},name=buff.name;
    if(!name || /^Buff[ ：]*\d+$/.test(name))name=(buff.configuredSources || []).slice(0,2).map(function(source){return source.name;}).join(' / ') || buffDisplayName(buff.id);
    return name+' [ID '+buff.id+'] · '+buff.piles+'层';
  }
  function renderBossBuffs(entry,sources,inputs) {
    var details=el('details');details.appendChild(el('summary',null,'BOSS 身上 Buff（本次命中前）'));
    var buffs=sources.targetBuffs;
    if(!buffs || !buffs.length) details.appendChild(el('p','empty',buffs ? '本次命中前没有生效中的 Buff。' : '这条记录未采集 BOSS Buff。'));
    (buffs || []).forEach(function(buff){
      var line=el('div','bonus-panel');
      line.appendChild(el('p',null,bossBuffHeading(buff)+' · '+(buff.remainingSeconds===null ? '持续时间未提供' : '剩余约 '+buff.remainingSeconds+'s')));
      bossBuffLines(buff).forEach(function(text){line.appendChild(el('p','note',text));});
      details.appendChild(line);
    });
    entry.appendChild(details);
  }
  function factorPartLines(row,previous,zone) {
    var parts=(row.parts || {})[zone];if(!parts) return [];
    var old=(previous && previous.parts && previous.parts[zone]) || [];
    return parts.filter(function(part){return part.key===undefined || !bothZero(row.inputs && row.inputs.self,row.inputs && row.inputs.target,part.key);}).map(function(part){
      var name=attrMetaOf(DATA.pvp || {},part.key).label;
      var label=part.label || (part.side==='target' ? bossContributionLabel(part.key,name,part.value) : name);
      var before=old.find(function(p){return p.side===part.side && p.key===part.key && p.label===part.label;});
      var delta=before ? part.value-before.value : null;
      return label+' '+(part.value>=0 ? '+' : '')+bonusPct(part.value)+(delta===null ? '' : delta===0 ? '（不变）' : '（较前次 '+(delta>0 ? '+' : '')+pctText(delta)+'个百分点）');
    });
  }

  function renderFactorHistory(snapshot) {
    var box=document.getElementById('factor-history');while(box.firstChild) box.removeChild(box.firstChild);
    var all=document.getElementById('factor-all-seconds').checked,sec=snapshot.sec;
    if(![DATA,DATA.other].some(function(side){return side && side.factorRows && side.factorRows.length;})) {
      box.appendChild(el('p','empty','这份报告没有 BOSS 实际乘区记录；需使用更新后的采集器重新采集，旧伤害数值无法反推每个乘区及来源。'));return;
    }
    [['普攻','attack'],['天书','book'],['技能（符咒、鬼仆、法器等）','skill']].forEach(function(group){
      var panel=el('section','bonus-panel');panel.appendChild(el('h3',null,group[0]));
      var count=0;
      [['我方',DATA],['敌方',DATA.other]].forEach(function(pair){
        var side=pair[1];
        factorRowsAt(side,sec,all).filter(function(row){return row.group===group[1];}).forEach(function(row){
          count++;
          var entry=el('details','factor-entry'),prev=previousFactor(side,row),factors=row.factors || {};
          entry.appendChild(el('summary',null,row.sec+'s · '+pair[0]+' · '+(row.bookName ? row.bookName+' · ' : '')+row.name+
            ' · '+row.firstT.toFixed(3)+'–'+row.lastT.toFixed(3)+'s · '+row.hits+'次 · '+fmt(row.damage)+' · 目标 '+(row.targetName || row.targetId || '未知')));
          var sources=(side.factorSources || [])[row.sourceRef] || {};
          renderBossBuffs(entry,sources,row.inputs);
          if(row.trueDamage || row.seckill) {
            entry.appendChild(el('p','note',row.seckill ? '秒杀：绕过普通伤害乘区。' : '真实伤害：不按普通攻击 × 各增伤区结算。'));
            panel.appendChild(entry);return;
          }
          var inputs=row.inputs || {};
          var table=el('table'),head=el('tr');['乘区','本次结算值','较前一次变化','属性与来源'].forEach(function(label){head.appendChild(el('th',null,label));});table.appendChild(head);
          FACTOR_META.forEach(function(meta){
            var value=factors[meta[0]];if(value===undefined || value===null) return;
            var additive=['targetType','hp','skillType','attackBonus'].indexOf(meta[0])>=0;
            var text=meta[0]==='attack' ? fmt(value) : additive ? bonusPct(value) : bonusMultiplier(value);
            var tr=el('tr');tr.appendChild(el('td',null,meta[1]));tr.appendChild(el('td',null,text));
            var old=prev && prev.factors && prev.factors[meta[0]],delta=old===undefined || old===null ? null : value-old;
            tr.appendChild(el('td','factor-change',delta===null ? '首次记录' : (delta===0 ? '不变' : (delta>0 ? '+' : '')+(additive ? pctText(delta)+'个百分点' : meta[0]==='attack' ? fmt(delta) : delta.toFixed(4)))));
            var applied=(row.parts || {})[meta[0]], ownKeys=applied ? applied.filter(function(p){return p.side==='self';}).map(function(p){return p.key;}) : meta[2];
            var targetKeys=applied ? applied.filter(function(p){return p.side==='target';}).map(function(p){return p.key;}) : meta[3];
            var cell=el('td','factor-sources'),lines=factorPartLines(row,prev,meta[0]);
            if(meta[0]==='type') lines.push('1 + 首领/目标类型 '+bonusPct(factors.targetType)+' + 高低血量 '+bonusPct(factors.hp)+' + 天书/技能类型 '+bonusPct(factors.skillType)+' + 普攻 '+bonusPct(factors.attackBonus));
            lines=lines.concat(bonusSourceLines(inputs.self,sources.self,ownKeys,'来源：',inputs.target),bonusSourceLines(inputs.target,sources.target,targetKeys,'BOSS：',inputs.self));
            if(meta[0]==='coefficient') lines.unshift('本技能实际执行系数（含技能表达式修正）');
            if(meta[0]==='pvp' && row.context && row.context.opponentPvpRed!==undefined) lines.push('自身PVP增伤 '+bonusPct(bonusValue(inputs.self,117))+' − 对面PVP减伤 '+bonusPct(row.context.opponentPvpRed)+' = 对抵PVP增伤 '+bonusPct(bonusValue(inputs.self,117)===null ? null : bonusValue(inputs.self,117)-row.context.opponentPvpRed)+'；实际倍率 '+bonusMultiplier(factors.pvp)+'（最低 ×0.5）');
            if(meta[0]==='damage' && row.context && row.context.shieldRatio!==undefined) lines.push('英雄护盾/最大生命：'+bonusPct(row.context.shieldRatio)+'；护盾转增伤已计入本次倍率');
            if(meta[0].indexOf('stamina')===0) lines.push('来源：血月耐力 '+(row.context && row.context.stamina ? row.context.stamina.energy : '未知')+' 的原生配置');
            if(meta[0]==='spCrit') lines.push('本次'+(factors.spCritAoe ? '群攻' : '普通')+'致命一击条件');
            lines.forEach(function(text){cell.appendChild(el('div',null,text));});tr.appendChild(cell);table.appendChild(tr);
          });
          var scroll=el('div','table-scroll');scroll.appendChild(table);entry.appendChild(scroll);panel.appendChild(entry);
        });
        if(side && side.factorsTruncated) panel.appendChild(el('p','note',pair[0]+'乘区记录达到采集上限，部分状态未保留。'));
      });
      if(!count) panel.appendChild(el('p','empty',all ? '未记录到该类实际命中。' : sec+'s 未记录到该类实际命中。'));
      box.appendChild(panel);
    });
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
    hr.appendChild(el("th", null, "来源"));
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    meta.forEach(function (m) {
      var a = snapshot.self ? snapshot.self[m.key] : undefined;
      var b = snapshot.other ? snapshot.other[m.key] : undefined;
      if(bothZero(snapshot.self,snapshot.other,m.key)) return;
      // 缺失值保留为 —，只有双方明确为零才隐藏。
      var tr = document.createElement("tr");
      tr.appendChild(el("td", null, m.note));
      tr.appendChild(el("td", null, fmtAttr(m, a)));
      tr.appendChild(el("td", null, fmtAttr(m, b)));
      var delta = (a === undefined || b === undefined) ? null : (Number(a) - Number(b));
      var cell = el("td", "attr-delta" + (delta === null ? "" : (delta > 0 ? " up" : (delta < 0 ? " down" : ""))),
        delta === null ? "—" : fmtAttr(m, delta));
      tr.appendChild(cell);
      var sourceCell=el('td','factor-sources');
      bonusSourceLines(snapshot.self,snapshot.selfSources,[m.key],'我方：',snapshot.other).concat(bonusSourceLines(snapshot.other,snapshot.otherSources,[m.key],'敌方：',snapshot.self)).forEach(function(text){sourceCell.appendChild(el('div',null,text));});
      tr.appendChild(sourceCell);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    renderBonusSummary(snapshot);
    renderFactorHistory(snapshot);
    document.getElementById("attr-sec-label").textContent =
      (seconds[attrState.sec] !== undefined ? seconds[attrState.sec] : attrState.sec) + "s";
  }

  function renderAttrLegend(pvp, meta) {
    var box = document.getElementById("attr-legend");
    while (box.firstChild) box.removeChild(box.firstChild);
    meta.forEach(function (m) {
      var idx = attrState.picked.indexOf(m.key);
      var snapshot=currentAttrSnapshot();
      if (idx < 0 || bothZero(snapshot.self,snapshot.other,m.key)) return;
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
    var snapshot=currentAttrSnapshot();
    attrState.picked.filter(function(key){return !bothZero(snapshot.self,snapshot.other,key);}).forEach(function (key, idx) {
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
      ? "百分比属性按实际比率显示（2.3 → 230%）。"
      : "最多同时勾 " + ATTR_MAX_SERIES + " 条属性（每条画双方两条线，配色槽位共 8 个）。";
  }

  function renderAttrPicks(pvp,seconds) {
    var meta=visibleAttrMeta(pvp);
    attrState.picked=attrState.picked.filter(function(key){return meta.some(function(m){return m.key===key;});});
    // 属性勾选（单独容器，不与曲线图例混用，否则会被 renderAttrLegend 覆盖）
    document.getElementById("attr-hint").textContent = meta.length ? "曲线属性：" : "";
    var legend = document.getElementById("attr-picks");
    while(legend.firstChild) legend.removeChild(legend.firstChild);
    meta.forEach(function (m) {
      var chip = el("label", "chip" + (attrState.picked.indexOf(m.key) >= 0 ? "" : " off"));
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.dataset.key=String(m.key);
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

  }

  function renderLegacyAttrs() {
    var pvp = DATA.pvp;
    if (!pvp || !pvp.attrSeconds || !pvp.attrSeconds.length) return;
    document.getElementById("attr-card").hidden = false;
    var meta = pvp.attrMeta || [];
    var seconds = pvp.attrSeconds.map(function (a) { return a.sec; });

    document.getElementById("attr-note").textContent =
      "战斗过程中双方属性（含 buff 带来的变化）。拖动滑块选秒看即时对比，" +
      "或在下方勾选属性画变化曲线 —— 两种视图联动。" +
      "双方均为 0 的属性自动隐藏；表里 — 表示该秒没读到这个属性；百分比类按实际比率显示（如 2.3 → 230%）。";

    var slider = document.getElementById("attr-sec");
    slider.max = String(pvp.attrSeconds.length - 1);
    slider.value = String(attrState.sec);
    slider.addEventListener("input", function (e) {
      attrState.sec = Number(e.target.value);
      renderAttrPicks(pvp,seconds);
      renderAttrLegend(pvp,visibleAttrMeta(pvp));
      renderAttrTable(pvp, seconds, meta);
      renderAttrChart(pvp, seconds, meta);
    });

    renderAttrPicks(pvp,seconds);

    document.getElementById('factor-all-seconds').addEventListener('change',function(){renderFactorHistory(pvp.attrSeconds[attrState.sec] || {sec:0});});
    renderAttrTable(pvp, seconds, meta);
    renderAttrLegend(pvp, meta);
    renderAttrChart(pvp, seconds, meta);
  }

  function syncAttrChips() {
    var pvp = DATA.pvp;
    if (!pvp) return;
    var meta = visibleAttrMeta(pvp);
    var chips = document.getElementById("attr-picks").children;
    for (var i = 0; i < chips.length; i++) {
      var chip = chips[i];
      var cb = chip.children && chip.children[0];
      if (!cb || cb.type !== "checkbox") continue;
      var key = cb.dataset.key;
      if (key === null) continue;
      chip.className = "chip" + (attrState.picked.some(function(picked){return String(picked)===key;}) ? "" : " off");
    }
  }

  var formulaState={type:'book',skill:'all',zone:'damage',sec:null};
  var FORMULA_ZONES=[
    {key:'combined',label:'总乘积（除技能系数）',numeric:true},
    {key:'attack',label:'攻击区',numeric:true}, {key:'coefficient',label:'技能系数区'},
    {key:'damage',label:'普通增伤区'}, {key:'element',label:'元素增伤区'},
    {key:'type',label:'类型增伤区',parts:['targetType','hp','skillType','attackBonus']},
    {key:'crit',label:'普通暴击区'}, {key:'skillCrit',label:'法术/鬼仆暴击区'},
    {key:'pvp',label:'PVP增伤区'}, {key:'final',label:'最终增伤区'},
    {key:'staminaSkill',label:'耐力技能系数区'}, {key:'staminaFinal',label:'耐力最终伤害区'},
    {key:'season',label:'赛季最终增伤区'}, {key:'spCrit',label:'致命一击区'},
    {key:'settlement',label:'BOSS扣血结算（观测比）'}
  ];
  function formulaCategory(row,side){
    var category=row.category || ((side.skills || []).find(function(s){return s.skillId===row.skillId;}) || {}).cat;
    return row.group==='attack' ? 'attack' : row.group==='book' ? 'book' : category==='card' ? 'card' : 'skill';
  }
  function formulaUsesStandard(row){
    if(row.trueDamage || row.seckill || row.formulaMode==='independent')return false;
    var f=row.factors || {};
    // 旧归档兼容：未执行常规计算时，客户端乘区容器保持零初始化。
    return !(['attack','coefficient','damage','element','targetType','hp','skillType','attackBonus'].every(function(key){return f[key]===0;}));
  }
  var formulaRowCache=new WeakMap(),formulaEmptyRows=[];
  function formulaRows(side,sec,includeIndependent,zoneKey){
    if(!side)return [];
    var snapshots=side.factorSnapshots || formulaEmptyRows,actual=side.factorRows || formulaEmptyRows,cache=formulaRowCache.get(side);
    if(!cache || cache.type!==formulaState.type || cache.skill!==formulaState.skill || cache.snapshots!==snapshots || cache.actual!==actual || cache.sn!==snapshots.length || cache.an!==actual.length){
      cache={type:formulaState.type,skill:formulaState.skill,snapshots:snapshots,actual:actual,sn:snapshots.length,an:actual.length,groups:{}};formulaRowCache.set(side,cache);
    }
    var observed=['coefficient','settlement'].indexOf(zoneKey || formulaState.zone)>=0,key=(includeIndependent?'all':'normal')+(observed?':observed':':snapshot'),group=cache.groups[key];
    if(!group){
      function matches(row){return row.boss===true && (includeIndependent || formulaUsesStandard(row)) && formulaCategory(row,side)===formulaState.type && (formulaState.skill==='all' || String(row.skillId)===formulaState.skill);}
      var sampled=snapshots.filter(matches),records=!includeIndependent && !observed && sampled.length ? sampled : actual.filter(matches);
      group={rows:records,seconds:new Map()};records.forEach(function(row){var rows=group.seconds.get(row.sec);if(!rows){rows=[];group.seconds.set(row.sec,rows);}rows.push(row);});cache.groups[key]=group;
    }
    return sec===undefined ? group.rows : group.seconds.get(sec) || [];
  }
  function formulaFactorValue(row,key){
    var factors=row.factors || {};
    if(key!=='combined')return factors[key];
    var required=['attack','damage','element','type','pvp','final'];
    if(required.some(function(name){return !Number.isFinite(factors[name]);}) || ['crit','skillCrit','season','spCrit','staminaSkill','staminaFinal'].some(function(name){return factors[name]!==undefined && !Number.isFinite(factors[name]);}))return null;
    return required.concat(['crit','skillCrit','season','spCrit','staminaSkill','staminaFinal']).reduce(function(product,name){return product*(factors[name]===undefined ? 1 : factors[name]);},1);
  }
  function formulaStat(rows,key){
    var count=0,total=0,min=Infinity,max=-Infinity;
    rows.forEach(function(row){var value=formulaFactorValue(row,key);if(value===null || value===undefined || !Number.isFinite(value))return;
      var hits=Number(row.hits)||1;count+=hits;total+=value*hits;min=Math.min(min,value);max=Math.max(max,value);
    });
    return {value:count ? total/count : null,hits:count,min:count ? min : null,max:count ? max : null};
  }
  function formulaPvpAverage(rows){
    var own=0,red=0,count=0,complete=true;
    rows.forEach(function(row){
      var value=bonusValue(row.inputs && row.inputs.self,117),context=row.context || {};
      var opponent=context.opponentPvpRed!==undefined ? context.opponentPvpRed : bonusValue(row.inputs && row.inputs.target,118);
      if(value===null || opponent===null || !Number.isFinite(opponent)){complete=false;return;}
      var hits=Number(row.hits)||1;own+=value*hits;red+=opponent*hits;count+=hits;
    });
    return complete && count ? {own:own/count,red:red/count,net:(own-red)/count} : {own:null,red:null,net:null};
  }
  function formulaPvpText(rows){
    if(rows.length)rows=[rows.reduce(function(best,row){return row.factors.pvp>best.factors.pvp ? row : best;},rows[0])];
    var values=formulaPvpAverage(rows),actual=formulaStat(rows,'pvp');
    return '自身PVP增伤 '+bonusPct(values.own)+' − 对面PVP减伤 '+bonusPct(values.red)+' = 对抵PVP增伤 '+bonusPct(values.net)+
      '；实际PVP倍率 '+bonusMultiplier(actual.value)+'（最低 ×0.5）';
  }
  function formulaPartAllowed(key){
    // 普攻视图不把天书/符咒专属属性列入公式。实际倍率仍保留原值，差额列为实际附加修正。
    if(formulaState.type!=='attack' && [708,709,1004].indexOf(Number(key))>=0)return false;
    if(formulaState.type==='attack')return !([115,119,116,120,131,133,134,233,234,235,236,237,238].indexOf(Number(key))>=0 || key>=209 && key<=216 || key>=225 && key<=232);
    return true;
  }
  function formulaObservation(row,value,applicable){
    var start=Number.isFinite(row.firstT) ? row.firstT : row.sec,end=Number.isFinite(row.lastT) ? row.lastT : start;
    var time=Number(start).toFixed(2)+(end>start ? '–'+Number(end).toFixed(2) : '')+'s';
    return {row:row,value:value,hits:Number(row.hits)||1,applicable:applicable!==false,
      label:time+' · '+(row.name || '未知技能')+' · '+(row.sampleKind==='second' ? '属性快照' : (Number(row.hits)||1)+'次伤害结算')};
  }
  function formulaNumberInfo(observations,peak){
    var count=0,sum=0,min=Infinity,max=-Infinity;
    observations.forEach(function(record){count+=record.hits;sum+=record.value*record.hits;min=Math.min(min,record.value);max=Math.max(max,record.value);});
    return {records:observations,count:count,mean:count ? sum/count : null,peak:peak===undefined ? max : peak,variable:count>0 && max-min>1e-9};
  }
  function formulaZoneNumberInfo(rows,key){
    return formulaNumberInfo(rows.filter(function(row){return Number.isFinite(formulaFactorValue(row,key));}).map(function(row){return formulaObservation(row,formulaFactorValue(row,key));}));
  }
  function formulaPartNumberInfo(part,rows){
    if(!part)return null;
    return formulaNumberInfo(rows.map(function(row){var record=(part.records || []).find(function(r){return r.row===row;});return formulaObservation(row,record ? record.value : 0,!!record);}),part.peakValue);
  }
  function attachFormulaNumber(td,info,format){
    if(!info || !info.variable)return;
    var number=td.children[1];number.className+=' formula-number has-variation';number.tabIndex=0;td.title='';
    var panel=el('span','formula-hover-panel');panel.setAttribute('role','tooltip');
    panel.appendChild(el('strong',null,'本秒最高值 '+format(info.peak)+'；实际贡献（加权均值） '+format(info.mean)));
    var snapshot=info.records.some(function(record){return record.row.sampleKind==='second';});
    panel.appendChild(el('p','note',snapshot ? '按本秒技能属性快照等权平均，不代表Buff持续时间或实际伤害占比。' : '按本秒伤害结算次数加权，不代表Buff持续时间或伤害量占比。合并记录以时间范围及次数标明。'));
    var groups=[];info.records.forEach(function(record){var group=groups.find(function(g){return Math.abs(g.value-record.value)<1e-9;});if(!group){group={value:record.value,hits:0};groups.push(group);}group.hits+=record.hits;});
    panel.appendChild(el('p',null,'计算：('+groups.map(function(group){return format(group.value)+' × '+group.hits;}).join(' + ')+') ÷ '+info.count+' = '+format(info.mean)));
    info.records.forEach(function(record){panel.appendChild(el('p','note',record.label+'：'+(record.applicable ? format(record.value) : '不适用，贡献按0计')));});
    number.appendChild(panel);
  }
  function formulaParts(rows,zone,side){
    var currentRow=null,totals={},sourceTotals={},denominator=rows.reduce(function(n,r){return n+(Number(r.hits)||1);},0);
    function add(id,label,value,percent,sources,hits){
      if(value===null || value===undefined || !Number.isFinite(value))return;
      var item=totals[id] || (totals[id]={id:id,label:label,value:0,percent:percent,sources:[],applicableHits:0,records:[]});
      item.value+=value*hits;var record=item.records.find(function(r){return r.row===currentRow;});if(record)record.value+=value;else{item.records.push({row:currentRow,value:value});item.applicableHits+=hits;}
      sources.forEach(function(line){if(item.sources.indexOf(line)<0)item.sources.push(line);});
    }
    rows.forEach(function(row){
      currentRow=row;var provenance=(side.factorSources || [])[row.sourceRef] || {},hits=Number(row.hits)||1;
      if(zone.key==='combined'){
        ['attack','damage','element','type','crit','skillCrit','pvp','final','staminaSkill','staminaFinal','season','spCrit'].forEach(function(key){
          var meta=FORMULA_ZONES.find(function(z){return z.key===key;}),value=formulaFactorValue(row,key);
          if(value!==undefined && value!==null){add(key,(meta ? meta.label : key)+'（相乘）',value,false,['含攻击值；只乘大乘区一次，不含基础技能系数、扣血观测比及取整。先逐条相乘再取均值，并非各区均值相乘。每秒快照按未暴击/未触发随机效果的基础状态计算。'],hits);totals[key].multiplier=key!=='attack';}
        });return;
      }
      if(zone.key==='settlement'){
        var settlement=row.settlement || {},buffs=provenance.targetBuffs || [];
        var observed=['扣血结算观测值，不是新增固定增伤乘区；护盾、招架、免伤、秒伤上限、生命保底、剩余生命和取整均可能影响它。'];

        [['inputDamage','扣血前计算伤害'],['actualDamage','实际扣血'],['shieldBefore','结算前护盾'],['shieldAfter','结算后护盾'],
         ['hpBefore','结算前生命'],['hpMax','最大生命'],['parry','结算前招架次数'],['immunity','结算前伤害免疫状态'],
         ['hpHold','生命保底比例'],['capMax','每秒伤害上限'],['capUsed','本周期已累计伤害']].forEach(function(pair){
          add(pair[0],pair[1],settlement[pair[0]],pair[0]==='hpHold',observed,hits);
          if(pair[0]==='inputDamage' && totals[pair[0]])buffs.forEach(function(buff){bossBuffLines(buff).forEach(function(text){var line=bossBuffHeading(buff)+'：'+text;if(totals[pair[0]].sources.indexOf(line)<0)totals[pair[0]].sources.push(line);});});
        });
        return;
      }
      var keys=zone.parts || [zone.key],parts=[];
      keys.forEach(function(key){
        if(key==='attackBonus' && formulaState.type!=='attack')return;
        var actual=(row.parts || {})[key];
        if(key==='pvp'){
          var pvp=formulaPvpAverage([row]);actual=[];
          if(pvp.net!==null){actual=[{side:'self',key:117,label:'自身PVP增伤',value:pvp.own},
            {side:'opponent',key:118,label:'对面PVP减伤',value:-pvp.red}];
            var correction=row.factors.pvp-1-pvp.net;
            if(Math.abs(correction)>1e-8)actual.push({label:'PVP倍率下限/实际修正',value:correction});
          }
        }
        if(actual) actual.forEach(function(part){if(part.key===undefined || formulaPartAllowed(part.key)) parts.push(part);});
        else {
          if(row.parts || row.factors[key]===0)return;
          var meta=FACTOR_META.find(function(m){return m[0]===key;});
          if(meta) [['self',meta[2]],['target',meta[3]]].forEach(function(pair){pair[1].forEach(function(k){
            if(!formulaPartAllowed(k))return;
            var value=bonusValue((row.inputs || {})[pair[0]],k);
            if(value!==null)parts.push({key:k,side:pair[0],value:pair[0]==='target' ? -value : value});
          });});
        }
      });
      parts.forEach(function(part){
        var meta=attrMetaOf(DATA.pvp || {},part.key),label=part.label || (part.side==='target' ? bossContributionLabel(part.key,meta.label,part.value) : meta.label);
        var sources=part.key===undefined ? ['来源：游戏实际倍率中的条件效果/下限修正'] :
          bonusSourceLines((row.inputs || {})[part.side],provenance[part.side],[part.key],'',{});
        if(part.side==='opponent'){
          sources=['来源：对局中的对方 PVP 减伤 '+bonusPct(-part.value)+'；以实际对局指标为准。'];
          var peerKey=side===DATA ? 'other' : 'self';
          var snapshot=((DATA.pvp || {}).attrSeconds || []).find(function(item){return item.sec===row.sec;});
          if(snapshot)sources=sources.concat(bonusSourceLines(snapshot[peerKey],snapshot[peerKey+'Sources'],[118],'对方属性快照：',{}));
        }
        if(!sources.length)sources=['来源未采集'];
        var partId=(part.side || 'extra')+':'+(part.key===undefined ? label : part.key);
        add(partId,label,part.value,part.key===undefined || meta.percent,sources,hits);
        if(part.key!==undefined && ['self','target'].indexOf(part.side)>=0){
          var rawSources=(provenance[part.side] || {})[part.key];
          if(Array.isArray(rawSources)){
            var summary=sourceTotals[partId] || (sourceTotals[partId]={covered:0,items:{}}),current={};summary.covered+=hits;
            rawSources.forEach(function(source){
              var match=String(source.label).match(/^Buff[： :]+(\d+)/),id=match ? 'buff:'+match[1] : String(source.label);
              var entry=current[id] || (current[id]={name:briefSourceName(source.label),value:0});
              entry.value+=Number(source.value)*(part.side==='target' ? -1 : 1);
            });
            Object.keys(current).forEach(function(id){var entry=current[id],record=summary.items[id] || (summary.items[id]={name:entry.name,sum:0,hits:0,min:Infinity,max:-Infinity});
              record.sum+=entry.value*hits;record.hits+=hits;record.min=Math.min(record.min,entry.value);record.max=Math.max(record.max,entry.value);
            });
          }
        }
      });
      if(zone.key==='type' && formulaState.type==='attack'){
        var shown=parts.reduce(function(n,p){return n+p.value;},0),actual=row.factors.type-1;
        if(Math.abs(actual-shown)>1e-8)add('actual-extra','实际附加修正',actual-shown,true,['保留游戏实际类型区倍率；不作为天书专属属性列入普攻视图。'],hits);
      }
      if(zone.key==='coefficient')add('coefficient','本次技能表达式系数',row.factors.coefficient,false,
        ['来源：'+(row.bookName ? row.bookName+' · ' : '')+row.name],hits);
      if(zone.key.indexOf('stamina')===0 && row.context && row.context.stamina)add(zone.key,'耐力配置系数',row.factors[zone.key],false,
        ['来源：血月耐力 '+row.context.stamina.energy+' 的游戏配置'],hits);
    });
    return Object.keys(totals).map(function(key){var item=totals[key];var sum=item.value;item.peakValue=Math.max.apply(null,item.records.map(function(record){return record.value;}));item.value=denominator ? sum/denominator : null;if(zone.key==='element' && /^(self|target):\d+$/.test(key)){item.attributeValue=item.applicableHits ? sum/item.applicableHits : null;item.applicableFraction=denominator ? item.applicableHits/denominator : null;item.totalHits=denominator;}var summary=sourceTotals[key];
      if(summary && summary.covered===item.applicableHits && Object.keys(summary.items).length){
        var count=zone.key==='element' ? item.applicableHits : denominator;
        function amount(value){return item.percent ? (value>0 ? '+' : '')+Number((value*100).toFixed(4))+'%' : fmt(value);}
        item.sources=Object.keys(summary.items).map(function(id){var source=summary.items[id],weighted=source.sum/count;
          return source.name+'：本秒贡献 '+amount(weighted)+'；生效 '+source.hits+'/'+count+' 份记录；生效时 '+amount(source.min)+(Math.abs(source.max-source.min)>1e-9 ? '～'+amount(source.max) : '');
        });
      }
      if(key.indexOf('target:')===0){var attrKey=Number(key.split(':')[1]);item.label=bossContributionLabel(attrKey,attrMetaOf(DATA.pvp || {},attrKey).label,item.value);}return item;});
  }
  function formulaZones(){
    // 各按钮独立选择自己的数据源，不能依赖当前选中的乘区。
    return FORMULA_ZONES.filter(function(zone){
      var rows=formulaRows(DATA,undefined,false,zone.key).concat(formulaRows(DATA.other,undefined,false,zone.key));
      return rows.some(function(row){return formulaFactorValue(row,zone.key)!==null && formulaFactorValue(row,zone.key)!==undefined;});
    });
  }
  function formulaDifference(a,b,percent,numeric){
    if(a===null || b===null)return '—';var delta=a-b;
    return (delta>0?'+':'')+(percent ? pctText(delta)+'个百分点' : numeric ? fmt(delta) : delta.toFixed(4));
  }
  function formulaCompareRow(label,a,b,format,sourceA,sourceB,onExpand){
    var row=el('tr'),delta=a===null || b===null ? null : a-b;
    function cell(value,self){
      var td=el('td'),wins=delta!==null && (self ? delta>0 : delta<0),loses=delta!==null && delta!==0 && !wins;
      var name=el(onExpand ? 'button' : 'span',(wins?'bonus-winner':loses?'bonus-lower':'')+(onExpand?' formula-name':''),label);
      if(onExpand){name.type='button';name.onclick=onExpand;name.title='点击展开属性与来源';name.setAttribute('aria-expanded','false');}
      td.appendChild(name);td.appendChild(el('span','bonus-value',value===null ? '未命中/未采集' : format(value)));
      var lines=self ? sourceA : sourceB;
      td.title=label+'\n'+(lines.length ? lines.join('\n') : '来源未采集');
      if(!onExpand && lines.length){var details=el('details');details.appendChild(el('summary',null,'属性来源'));lines.forEach(function(line){details.appendChild(el('p','note',line));});td.appendChild(details);}
      return td;
    }
    var left=cell(a,true),right=cell(b,false);row.appendChild(left);
    var middle=el('td','bonus-diff',formulaDifference(a,b,format.percent,format.numeric));
    middle.title='差值 = 我方 − 敌方\n'+left.title+'\n\n'+right.title;row.appendChild(middle);row.appendChild(right);
    return row;
  }
  function formulaTableHead(table){var head=el('tr');['我方','差值（我方 − 敌方）','敌方'].forEach(function(label){head.appendChild(el('th',null,label));});table.appendChild(head);}
  function renderInitialAttributes(){
    var left=DATA.initialAttributes,right=DATA.other && DATA.other.initialAttributes;
    function valid(snapshot){return snapshot && snapshot.status==='captured' && snapshot.attributes;}
    var a=valid(left)?left.attributes:{},b=valid(right)?right.attributes:{};
    var note=document.getElementById('initial-attrs-note'),box=document.getElementById('initial-attrs-table');
    while(box.firstChild)box.removeChild(box.firstChild);
    if(!valid(left) && !valid(right)){
      note.textContent='未采集到开战初始属性。旧报告或开战后才开启的采集无法补齐，需在下一场开始前开启分析。';return;
    }
    note.textContent='战斗初始化完成、首次伤害前的面板属性；不依赖伤害命中记录。'
      +(valid(left)?' 我方 '+Number(left.time||0).toFixed(2)+'s。':' 我方初始快照缺失。')
      +(valid(right)?' 敌方 '+Number(right.time||0).toFixed(2)+'s。':' 敌方初始快照缺失。')
      +' 差值为我方减敌方；百分比属性的差值单位为百分点。';
    a=Object.assign({},a);b=Object.assign({},b);
    var selfRed=left && left.context && left.context.opponentPvpRed;
    var otherRed=right && right.context && right.context.opponentPvpRed;
    if(a[117]!==undefined && (selfRed!==undefined || b[118]!==undefined))a.finalPvp=a[117]-(selfRed===undefined?b[118]:selfRed);
    if(b[117]!==undefined && (otherRed!==undefined || a[118]!==undefined))b.finalPvp=b[117]-(otherRed===undefined?a[118]:otherRed);
    var metadata=((left && left.attrMeta) || (right && right.attrMeta) || []),keys=Object.keys(a);
    Object.keys(b).forEach(function(key){if(keys.indexOf(key)<0)keys.push(key);});
    keys.sort(function(x,y){return x==='finalPvp'?1:y==='finalPvp'?-1:Number(x)-Number(y);});
    var table=el('table','bonus-compare'),head=el('tr');
    ['属性','我方','差值（我方 − 敌方）','敌方'].forEach(function(label){head.appendChild(el('th',null,label));});table.appendChild(head);
    keys.forEach(function(key){
      var meta=metadata.find(function(row){return String(row.key)===key;}) || {label:key,percent:false};
      var va=bonusValue(a,key),vb=bonusValue(b,key),delta=va===null || vb===null?null:va-vb;
      var row=el('tr');row.appendChild(el('td',null,meta.label || meta.note || key));
      row.appendChild(el('td',delta>0?'bonus-winner':delta<0?'bonus-lower':'',fmtAttr(meta,va)));
      row.appendChild(el('td','bonus-diff',formulaDifference(va,vb,meta.percent,true)));
      row.appendChild(el('td',delta<0?'bonus-winner':delta>0?'bonus-lower':'',fmtAttr(meta,vb)));
      table.appendChild(row);
    });
    box.appendChild(table);
  }
  function renderFormulaComparison(){
    var panel=document.getElementById('formula-comparison'),box=document.getElementById('bonus-summary');
    if(formulaState.sec===null){panel.hidden=true;return;}
    panel.hidden=false;while(box.firstChild)box.removeChild(box.firstChild);
    document.getElementById('formula-selected-sec').textContent=formulaState.sec+'s · '+document.getElementById('formula-type').selectedOptions[0].textContent+' · 乘区对比';
    var aRows=formulaRows(DATA,formulaState.sec),bRows=formulaRows(DATA.other,formulaState.sec),table=el('table','bonus-compare');
    [['我方',DATA],['敌方',DATA.other]].forEach(function(pair){
      var independent=formulaRows(pair[1],formulaState.sec,true).filter(function(row){return !formulaUsesStandard(row);});
      if(!independent.length)return;
      var count=independent.reduce(function(n,row){return n+(Number(row.hits)||1);},0),damage=independent.reduce(function(n,row){return n+(Number(row.damage)||0);},0);
      var note=el('details','bonus-panel');note.appendChild(el('summary',null,pair[0]+'：'+count+' 次独立/特殊结算，扣血 '+fmt(damage)+'；未混入常规乘区均值'));
      var names=[];independent.forEach(function(row){if(names.indexOf(row.name)<0)names.push(row.name);});
      note.appendChild(el('p','note',names.join('、')+'。这些记录未执行常规攻击与增伤乘区计算，伤害统计仍保留。'));box.appendChild(note);
    });

    if(!aRows.length && !bRows.length){box.appendChild(el('p','empty','本秒双方都没有该攻击类型的 BOSS 实际命中，暂无乘区可对比。'));return;}
    formulaTableHead(table);
    formulaZones().forEach(function(zone){
      var a=formulaStat(aRows,zone.key),b=formulaStat(bRows,zone.key),details=el('div','formula-parts');
      details.id='formula-parts-'+zone.key;details.hidden=true;
      var format=zone.numeric ? fmt : bonusMultiplier;format.numeric=!!zone.numeric;
      var partsA=formulaParts(aRows,zone,DATA),partsB=formulaParts(bRows,zone,DATA.other || {}),ids=[];
      partsA.concat(partsB).forEach(function(p){if(ids.indexOf(p.id)<0)ids.push(p.id);});
      var nested=el('table','bonus-compare formula-detail-table');formulaTableHead(nested);
      ids.forEach(function(id){
        var pa=partsA.find(function(p){return p.id===id;}),pb=partsB.find(function(p){return p.id===id;});
        var elementAttribute=zone.key==='element' && /^(self|target):\d+$/.test(id);
        var av=pa ? pa.peakValue : elementAttribute ? null : a.hits ? 0 : null,bv=pb ? pb.peakValue : elementAttribute ? null : b.hits ? 0 : null;
        if(av===0 && bv===0)return;
        var info=pa || pb,print=elementAttribute ? function(v){return Number((v*100).toFixed(4))+'%';} : info.multiplier ? bonusMultiplier : info.percent ? function(v){return bonusPct(v);} : function(v){return fmt(v);};print.percent=info.percent;print.numeric=!info.percent && !info.multiplier;
        var comparisonRow=formulaCompareRow(info.label,av,bv,print,pa ? pa.sources : [],pb ? pb.sources : []);
        if(id.indexOf('target:')===0){if(pa)comparisonRow.children[0].children[0].textContent=pa.label;if(pb)comparisonRow.children[2].children[0].textContent=pb.label;}
        if(elementAttribute){
          if(av!==null && bv!==null){var delta=(av-bv)*100;comparisonRow.children[1].textContent=(delta>0 ? '+' : '')+Number(delta.toFixed(4))+'个百分点';}
          [[0,pa],[2,pb]].forEach(function(pair){if(!pair[1])comparisonRow.children[pair[0]].children[1].textContent='本秒无适用记录';});
        }
        attachFormulaNumber(comparisonRow.children[0],formulaPartNumberInfo(pa,aRows),print);
        attachFormulaNumber(comparisonRow.children[2],formulaPartNumberInfo(pb,bRows),print);
        nested.appendChild(comparisonRow);
      });
      if(zone.key==='element')details.appendChild(el('p','note','默认显示本秒适用记录中的属性最高值；仅在数值或适用范围变化时，悬停数字查看实际贡献、结算时间及技能列表。颜色和差值比较最高值。不同元素的原始属性不能直接相加；总倍率 = 100%基础倍率 + 各项对本类均值的加权贡献。双方命中/快照的元素构成不同时，总体均值也会不同。'));
      if(zone.key==='type'){
        function equation(label,rows){
          if(!rows.length)return label+'：本秒无常规命中';
          var highest=rows.reduce(function(best,row){return formulaFactorValue(row,'type')>formulaFactorValue(best,'type') ? row : best;},rows[0]);rows=[highest];
          var terms=['100%（基础倍率）'];[['targetType','目标类型'],['hp','血量条件'],['skillType','技能类型'],['attackBonus','普攻']].forEach(function(pair){
            var stat=formulaStat(rows,pair[0]);if(stat.value && (pair[0]!=='attackBonus' || formulaState.type==='attack'))terms.push(pair[1]+' '+bonusPct(stat.value));
          });
          return label+'（最高倍率对应结算）：'+terms.join(' + ')+' = '+bonusMultiplier(formulaStat(rows,'type').value);
        }
        details.appendChild(el('p','formula-equation',equation('我方',aRows)+'；'+equation('敌方',bRows)));
      }
      if(ids.length)details.appendChild(nested);else details.appendChild(el('p','empty','该区没有可展开的已采集属性。实际倍率保留原值。'));
      var hint=function(stat){return stat.hits ? ['本秒 '+stat.hits+' 份有效记录均值；范围 '+format(stat.min)+'～'+format(stat.max)] : ['本秒没有该类型的实际命中，不用其他秒填补。'];};
      var top=formulaCompareRow(zone.label,a.max,b.max,format,hint(a),hint(b),function(){
        var expanded=details.hidden;details.hidden=!expanded;drill.hidden=!expanded;
        [0,2].forEach(function(index){var button=top.children[index].children[0];button.setAttribute('aria-expanded',String(expanded));button.title=expanded ? '点击收起属性与来源' : '点击展开属性与来源';});
      });
      attachFormulaNumber(top.children[0],formulaZoneNumberInfo(aRows,zone.key),format);
      attachFormulaNumber(top.children[2],formulaZoneNumberInfo(bRows,zone.key),format);
      [0,2].forEach(function(index){top.children[index].children[0].setAttribute('aria-controls',details.id);});
      if(zone.key==='settlement'){
        top.children[0].appendChild(el('p','note','实际扣血 ÷ 扣血前计算伤害；观测值，不重复乘入增伤。'));
        top.children[2].appendChild(el('p','note','含护盾、免伤、招架、伤害上限、生命保底等可能影响；具体原因以采集状态为准。'));
      }
      if(zone.key==='pvp'){
        top.children[0].appendChild(el('p','note',formulaPvpText(aRows)));
        top.children[2].appendChild(el('p','note',formulaPvpText(bRows)));
        top.children[0].title+='\n'+formulaPvpText(aRows);top.children[2].title+='\n'+formulaPvpText(bRows);
      }
      top.className='formula-zone-row'+(zone.key===formulaState.zone ? ' formula-selected-zone' : '');table.appendChild(top);
      var drill=el('tr','formula-drill-row'),td=el('td');drill.hidden=true;td.colSpan=3;td.appendChild(details);drill.appendChild(td);table.appendChild(drill);
    });
    box.appendChild(table);
  }
  function formulaAttributeChanges(side,sec){
    var current=formulaRows(side,sec),previous=formulaRows(side,sec-1);
    if(!current.length)return [];
    function ordered(rows){return rows.slice().sort(function(a,b){return (a.firstT===undefined?a.sec:a.firstT)-(b.firstT===undefined?b.sec:b.firstT);});}
    function state(row){
      var provenance=(side.factorSources || [])[row.sourceRef],values={},known={};
      if(!provenance)return null;
      ['self','target'].forEach(function(owner){Object.keys(provenance[owner] || {}).forEach(function(key){
        known[owner+':'+key]=true;
        (provenance[owner][key] || []).forEach(function(source){
          if(!Number.isFinite(source.value))return;
          var label=buffSourceLabel(source.label || '未标明来源'),id=owner+':'+key+':'+label;
          var item=values[id] || (values[id]={value:0,key:key,owner:owner,label:label});item.value+=source.value;
        });
      });});return {values:values,known:known};
    }
    var before=previous.length ? state(ordered(previous).slice(-1)[0]) : null,lines=[];
    ordered(current).forEach(function(row){var after=state(row);if(!after){before=null;return;}
      if(before){var ids=Object.keys(before.values);Object.keys(after.values).forEach(function(id){if(ids.indexOf(id)<0)ids.push(id);});
        ids.forEach(function(id){var a=before.values[id],b=after.values[id],item=b || a,attr=item.owner+':'+item.key;
          // Missing attribute provenance is unknown, not evidence of a removed Buff.
          if(!before.known[attr] || !after.known[attr])return;
          var delta=(b ? b.value : 0)-(a ? a.value : 0);if(Math.abs(delta)<1e-9)return;
          var meta=attrMetaOf(DATA.pvp || {},item.key),time=Number(Number.isFinite(row.firstT)?row.firstT:row.sec).toFixed(2);
          var line=(!a ? '本秒新增' : !b ? '本秒失去' : delta>0 ? '本秒新增' : '本秒失去')+' · '+time+'s · '+(item.owner==='target'?'BOSS身上':'自身')+' · '+meta.label+' '+fmtAttr(meta,!a ? b.value : !b ? a.value : delta)+' · 来源：'+item.label;
          if(lines.indexOf(line)<0)lines.push(line);
        });
      }before=after;
    });
    if(!previous.length)lines.unshift('缺少上一秒同类记录，仅列本秒已观测到的变化；首条记录不视为新增。');
    return lines;
  }
  function renderFormulaTrend(){
    var aRows=formulaRows(DATA),bRows=formulaRows(DATA.other),seconds=[];
    var rows=aRows.concat(bRows);
    if(rows.length){var last=rows.reduce(function(n,row){return Math.max(n,row.sec);},0);for(var sec=0;sec<=last;sec++)seconds.push(sec);}
    var zone=FORMULA_ZONES.find(function(z){return z.key===formulaState.zone;}) || FORMULA_ZONES[2];
    var series=[['我方',DATA,SELF_SLOT],['敌方',DATA.other,OTHER_SLOT]].map(function(pair){
      var changeCache=new Map(),notes=[],values=seconds.map(function(sec){var stat=formulaStat(formulaRows(pair[1],sec),zone.key);
        notes.push(stat.hits ? stat.hits+(formulaRows(pair[1],sec).some(function(row){return row.sampleKind==='second';}) ? '份每秒快照 · 范围 ' : '次命中 · 范围 ')+(zone.numeric ? fmt : bonusMultiplier)(stat.min)+'～'+(zone.numeric ? fmt : bonusMultiplier)(stat.max) : '本秒无该类型命中；虚线仅连接前后观测');return stat.max;});
      return {label:pair[0]+' · '+zone.label,slot:pair[2],values:values,notes:notes,changes:function(index){var sec=seconds[index];if(!changeCache.has(sec))changeCache.set(sec,formulaAttributeChanges(pair[1],sec));return changeCache.get(sec);}};
    });
    drawLine(document.getElementById('svg-attr'),document.getElementById('tip-attr'),series,{height:300,gaps:true,connectGaps:true,xLabels:seconds,
      markerIndex:seconds.indexOf(formulaState.sec),yFormat:zone.numeric ? fmt : bonusMultiplier,onSelect:function(index){
        if(seconds[index]===undefined)return;formulaState.sec=seconds[index];renderFormulaComparison();renderFormulaTrend();
        if(document.getElementById('factor-details').open)renderFactorHistory({sec:formulaState.sec});
        var panel=document.getElementById('formula-comparison');if(panel.scrollIntoView)panel.scrollIntoView({behavior:'smooth',block:'nearest'});
      }});
    var firstHits=[['我方',aRows],['敌方',bRows]].map(function(pair){
      var valid=pair[1].filter(function(row){return Number.isFinite(formulaFactorValue(row,zone.key));});
      return pair[0]+(valid.length ? '起始记录 '+Math.min.apply(null,valid.map(function(row){return row.sec;}))+'s' : '暂无该类型命中');
    }).join('，');
    document.getElementById('formula-chart-note').textContent=seconds.length ? zone.label+' · '+firstHits+'；首次命中前暂无实测倍率。曲线显示本秒最高值，悬停数值查看加权贡献；独立/特殊结算另列，虚线连接无命中间隔（非逐秒实测）。BOSS扣血结算为独立观测项。点击某秒查看真实记录、属性与来源。' : '该类型没有可用的乘区记录；即使伤害统计中有命中，也可能未采集到对应乘区。已有报告无法补回缺失的快照，请在更新采集器后重新进行战斗或重放。';
    if(aRows.concat(bRows).some(function(row){return row.sampleKind==='second';}))document.getElementById('formula-chart-note').textContent=zone.label+' · 每秒读取当前属性，曲线和表格显示本秒最高值；变化时悬停数字查看快照均值及逐条依据；未暴击/未触发随机效果。技能系数不在快照中推测，实际命中保留在底部。总乘积含攻击值，不含基础技能系数、扣血观测比与取整。缺少角色或BOSS时留空，不补造数据。';
  }
  function renderFormulaFilters(){
    var box=document.getElementById('formula-zone-picks');while(box.firstChild)box.removeChild(box.firstChild);
    var zones=formulaZones();if(!zones.some(function(z){return z.key===formulaState.zone;}))formulaState.zone=(zones[0] || {}).key || 'damage';
    zones.forEach(function(zone){var button=el('button','btn'+(zone.key===formulaState.zone?' formula-active':''),zone.label);button.type='button';
      button.onclick=function(){formulaState.zone=zone.key;renderFormulaFilters();renderFormulaTrend();renderFormulaComparison();};box.appendChild(button);});
  }
  function renderFormulaSkills(){
    var select=document.getElementById('formula-skill');while(select.firstChild)select.removeChild(select.firstChild);
    var saved=formulaState.skill;formulaState.skill='all';var rows=formulaRows(DATA,undefined,false,'damage').concat(formulaRows(DATA.other,undefined,false,'damage'),formulaRows(DATA,undefined,true).filter(formulaUsesStandard),formulaRows(DATA.other,undefined,true).filter(formulaUsesStandard));formulaState.skill=saved;
    var all=el('option',null,(DATA.factorSnapshots || []).length ? '本类全部技能（显示本秒最高值）' : '本类全部技能（显示本秒最高值）');all.value='all';select.appendChild(all);var ids=[];
    rows.forEach(function(row){if(ids.indexOf(row.skillId)>=0)return;ids.push(row.skillId);var option=el('option',null,(row.bookName ? row.bookName+' · ':'')+row.name);option.value=String(row.skillId);select.appendChild(option);});
    if(saved!=='all' && !ids.some(function(id){return String(id)===saved;}))formulaState.skill='all';select.value=formulaState.skill;
  }
  function renderAttrs(){
    if(!DATA.pvp && !DATA.factorRows && !(DATA.other && DATA.other.factorRows))return;
    document.getElementById('attr-card').hidden=false;
    document.getElementById('formula-type').value=formulaState.type;
    function refresh(){renderFormulaSkills();renderFormulaFilters();renderFormulaTrend();renderFormulaComparison();}
    document.getElementById('formula-type').onchange=function(e){formulaState.type=e.target.value;formulaState.skill='all';refresh();};
    document.getElementById('formula-skill').onchange=function(e){formulaState.skill=e.target.value;renderFormulaFilters();renderFormulaTrend();renderFormulaComparison();};
    var foot=document.getElementById('factor-details'),historyButton=document.getElementById('open-damage-history');
    var historyCount=[DATA,DATA.other].reduce(function(n,side){return n+((side && side.factorRows) || []).reduce(function(total,row){return total+(Number(row.hits)||1);},0);},0);
    function historyTitle(){document.getElementById('damage-history-summary').textContent=(foot.open ? '收起' : '展开')+'全部逐秒伤害计算明细（'+historyCount+' 次BOSS结算）';historyButton.setAttribute('aria-expanded',String(!!foot.open));}
    foot.ontoggle=function(){historyTitle();if(foot.open)renderFactorHistory({sec:formulaState.sec===null ? 0 : formulaState.sec});};
    historyButton.onclick=function(){document.getElementById('factor-all-seconds').checked=true;foot.open=true;historyTitle();renderFactorHistory({sec:formulaState.sec===null ? 0 : formulaState.sec});if(foot.scrollIntoView)foot.scrollIntoView({behavior:'smooth',block:'start'});};
    historyTitle();
    document.getElementById('factor-all-seconds').onchange=function(){if(foot.open)renderFactorHistory({sec:formulaState.sec===null ? 0 : formulaState.sec});};
    refresh();
  }

  function renderFlags() {
    var card=document.getElementById('flag-card'), box=document.getElementById('flag-summary');
    var series=[];
    [["我方",RAW_DATA,SELF_SLOT],["敌方",RAW_DATA.other,OTHER_SLOT]].forEach(function(pair){
      var skills=flagSkills(pair[1]);
      if(!skills.length) return;
      card.hidden=false;
      box.appendChild(el('h3',null,pair[0]+'战旗伤害：'+fmt(skills.reduce(function(n,s){return n+s.dmg;},0))));
      skills.forEach(function(s){box.appendChild(el('p','note',s.name+'：'+fmt(s.dmg)+'，'+s.hits+'次命中'));});
      var values=[];
      skills.forEach(function(s){(s.perSecond || []).forEach(function(v,i){values[i]=(values[i] || 0)+v;});});
      series.push({label:pair[0]+'战旗每秒伤害',slot:pair[2],values:values});
    });
    card.addEventListener('toggle',function(){
      if(card.open) drawLine(document.getElementById('svg-flag'),document.getElementById('tip-flag'),series,{height:220});
    });
  }

  // ── 玩家数据 ──
  function renderBookComparison(card,player,opponent){
    var entries=player.awakenings || [],other=(opponent && opponent.awakenings) || [],groups=[];
    function bookKey(a){return a.bookId!==undefined && a.bookId!==null ? String(a.bookId) : a.bookName;}
    function branchKey(a){return a.branchId!==undefined && a.branchId!==null ? String(a.branchId) : a.pathName+'|'+a.branchName;}
    entries.forEach(function(a){
      var key=bookKey(a),group=groups.find(function(g){return g.key===key;});
      if(!group){group={key:key,name:a.bookName,rows:[]};groups.push(group);}group.rows.push(a);
    });
    if(!groups.length)return;
    card.appendChild(el('h4',null,'天书对比'));
    function levelNode(a){
      var match=other.find(function(b){return bookKey(b)===bookKey(a) && branchKey(b)===branchKey(a);});
      var known=a.level!==null && a.level!==undefined && Number.isFinite(Number(a.level));
      var comparable=match && match.level!==null && match.level!==undefined && Number.isFinite(Number(match.level)) && known;
      var cls='book-level';
      // 颜色只放在天书名称上。
      var item=el('span',cls,a.branchName+' '+(known ? 'Lv'+a.level : '等级未知'));
      if(comparable)item.title='对方同项：Lv'+match.level;
      return item;
    }
    groups.forEach(function(group){
      var details=el('details','book-comparison'),summary=el('summary');
      summary.title='点击展开分支等级对比';
      var opposing=other.filter(function(a){return bookKey(a)===group.key;}),mainRows=group.rows.filter(function(a){return a.pathName==='主阶';});
      var opposingMain=opposing.filter(function(a){return a.pathName==='主阶';}),order=[];
      mainRows.concat(opposingMain).forEach(function(a){if(order.indexOf(branchKey(a))<0)order.push(branchKey(a));});
      order.sort(function(a,b){return Number(b)-Number(a);});
      var comparison=0;
      if(mainRows.length && opposingMain.length)order.some(function(key){
        var own=mainRows.find(function(a){return branchKey(a)===key;}),enemy=opposingMain.find(function(a){return branchKey(a)===key;});
        if((own && (own.level===null || own.level===undefined)) || (enemy && (enemy.level===null || enemy.level===undefined)))return true;
        var a=own ? Number(own.level) : 0,b=enemy ? Number(enemy.level) : 0;
        if(!Number.isFinite(a) || !Number.isFinite(b))return true;
        comparison=a-b;return comparison!==0;
      });
      var bookName=el('strong',comparison>0 ? 'book-higher' : comparison<0 ? 'book-lower' : null,group.name);
      bookName.title='按主阶进度比较，高阶优先，同阶比较等级';summary.appendChild(bookName);
      var main=group.rows.filter(function(a){return a.pathName==='主阶';}),levels=el('span','book-main-levels');
      if(!main.length)levels.appendChild(el('span','muted','暂无主阶等级'));
      main.forEach(function(a){levels.appendChild(levelNode(a));});summary.appendChild(levels);details.appendChild(summary);
      var branches=group.rows.filter(function(a){return a.pathName!=='主阶';}),list=el('ul');
      branches.forEach(function(a){var li=el('li');li.appendChild(levelNode(a));li.appendChild(el('span','muted','（'+a.pathName+'）'));list.appendChild(li);});
      if(branches.length)details.appendChild(list);else details.appendChild(el('p','muted','暂无分支记录'));
      card.appendChild(details);
    });
  }

  function renderPlayers() {
    var side = sd();
    var players = side && side.players;
    var leifaRows = [["我方",DATA],["敌方",DATA.other]].map(function(pair){
      var data=pair[1];
      var cat=data && (data.categories || []).find(function(c){return c.key==='leifa';});
      return pair[0]+'：'+(cat ? fmt(cat.dmg)+'，'+cat.hits+'次命中' : '暂无雷法尊者伤害记录');
    });
    if([DATA,DATA.other].some(function(data){return data && (data.categories || []).some(function(c){return c.key==='leifa';});})) {
      document.getElementById('leifa-card').hidden=false;
      document.getElementById('leifa-summary').textContent=leifaRows.join('；');
    }
    if (!players || (!players.self && !players.other)) return;
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
      renderBookComparison(card,p,title==='我方' ? players.other : players.self);
      section("鬼仆", p.pets, function (pet) {
        return (pet.name || ("鬼仆" + pet.cfgId)) + (pet.skillLevel ? " 技能Lv" + pet.skillLevel : "");
      });
      section("三尸", p.desires, function (d) { return d.name; });
      section("傀儡装", p.fashions, function(f){return (f.name || ("ID"+f.id)) + (f.level ? " Lv"+f.level : "") + "（已穿戴）";});
      if(side.replay && side.replay.isReplay) card.appendChild(el("div", "note", side.battleType===20 ? "血月战场回放" : "PVP回放"));
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
      "每格 1s，共 " + shown.length + " 条曲线" + (side.truncated ? (side.recordingOnly ? "；原始事件已截断，曲线仅覆盖已保存事件" : "；原始事件已截断，曲线仍完整") : "");

    drawLine(document.getElementById("svg-main"), document.getElementById("tip-main"), shown, { height: 320, showPercent:state.view==='dps', percentTotals:((side.curves || []).find(function(c){return c.key==='__total';}) || {})[state.scope==='boss' ? 'bossPerSecond' : 'perSecond'] });

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
      " · " + (side.eventCount || 0) + " 条伤害事件 · 主统计不含战旗";

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

    renderFlags();
    renderPvp();
    renderAttrs();
    renderPlayers();
    renderInitialAttributes();
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
