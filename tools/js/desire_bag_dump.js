// ==UserScript==
// @name 三尸·背包与合成配置导出
// @description 只读导出 ROLE.desire.bag 按（种类×品质）的可合成数量，以及 ComposeCfg 的真实成功率与失败返还。不点击、不发请求、不消耗任何三尸。
// @match *
// @run-at document-start
// @e0e1-mode once
// ==/UserScript==

// 数据来源（已逆向确认）：
//   ROLE.desire.bag : Map<uuid, GDDesireItem{ id(=uuid), cfgId, locked, num, planInfo }>
//   品质 = ItemCfg.getById(cfgId).quality      —— 1白 2蓝 3紫 4橙 5红 6黑金 7幻彩 8轮回
//   种类 = DesireCfg.getById(cfgId).type       —— DesireType: TANHEART=1 CHENHEART=2 CHIHEART=3
//                                                  TANORDINARY=4 CHENORDINARY=5 CHIORDINARY=6
//   合成硬约束 canDoCompose(a,b)：type 相同 && quality 相同（心与凡不能互合）
//   可合成的品质档 = ComposeCfg 里存在 quality-1 == q 的配置
//   合成成功率 = ComposeCfg 里 num==2 且 quality==目标品质 的 ratio（万分比）与 returned（失败返还）
//
// 排除规则与游戏自身一致（getDesireItemsForBag / isComposeRed）：
//   locked 的不参与；planInfo.size > 0（镶嵌在某个方案里）的不参与。

var E0E1_DESIRE_TYPE_LABEL = {
  1: "贪·心", 2: "嗔·心", 3: "痴·心", 4: "贪·凡", 5: "嗔·凡", 6: "痴·凡"
};

function e0e1ResolveGameWindow() {
  try {
    if (globalThis.UIManager) return globalThis;
  } catch (error) {}

  try {
    var named = globalThis.document && globalThis.document.querySelector('iframe[name="gameContext"]');
    if (named && named.contentWindow && named.contentWindow.UIManager) {
      return named.contentWindow;
    }
  } catch (error) {}

  try {
    var frames = globalThis.frames;
    for (var i = 0; i < frames.length; i++) {
      try {
        if (frames[i] && frames[i].UIManager) return frames[i];
      } catch (error) {}
    }
  } catch (error) {}
  return null;
}

function e0e1Expose(name, fn) {
  try {
    globalThis[name] = fn;
  } catch (error) {}
  try {
    var game = e0e1ResolveGameWindow();
    if (game && game !== globalThis) game[name] = fn;
  } catch (error) {}
}

function e0e1LabelOf(codes, value) {
  // 数字枚举的反向名字：TS 编译后是双向映射，1 -> "TANHEART"。
  return codes ? codes[value] : null;
}

async function e0e1CollectDesire() {
  var game = e0e1ResolveGameWindow();
  if (!game || !game.ROLE || !game.System) return { ok: false, message: "游戏未就绪（找不到 ROLE / System）" };
  var desire = game.ROLE.desire;
  var bag = desire && desire.bag;
  if (!bag || typeof bag.forEach !== "function") return { ok: false, message: "三尸背包不可用（ROLE.desire.bag 缺失）" };

  var configs = await game.System.import("chunks:///_virtual/configs.ts");
  var ItemCfg = configs.ItemCfg, DesireCfg = configs.DesireCfg, ComposeCfg = configs.ComposeCfg;
  if (!ItemCfg || !DesireCfg || !ComposeCfg) return { ok: false, message: "配置表未加载（ItemCfg / DesireCfg / ComposeCfg）" };

  var roleHelper = null;
  try {
    roleHelper = (await game.System.import("chunks:///_virtual/role-helper.ts")).roleHelper;
  } catch (error) {}

  var common = {};
  try {
    common = (await game.System.import("chunks:///_virtual/types-common.ts")) || {};
  } catch (error) {}
  var DesireType = common.DesireType || null;

  // 品质名以游戏自身的 getRareName 为准，拿不到就退回数字。
  var qualityNames = {};
  for (var q = 1; q <= 8; q++) {
    var text = "";
    if (roleHelper && typeof roleHelper.getRareName === "function") text = String(roleHelper.getRareName(q) || "");
    qualityNames[q] = text || ("品质" + q);
  }

  // 可合成的品质档：ComposeCfg.quality 是目标品质，材料品质 = quality - 1。
  var composeQuality = new Set();
  (ComposeCfg.list || []).forEach(function (row) {
    if (Number.isFinite(Number(row.quality))) composeQuality.add(Number(row.quality) - 1);
  });

  var rates = [];
  (ComposeCfg.list || []).forEach(function (row) {
    var num = Number(row.num), target = Number(row.quality);
    if (num !== 2 || !Number.isFinite(target)) return;
    rates.push({
      quality: target - 1,
      target: target,
      ratio: Number(row.ratio),
      percent: Number(row.ratio) / 100,
      returned: Number(row.returned)
    });
  });
  rates.sort(function (a, b) { return a.quality - b.quality; });

  var groups = new Map();
  var locked = 0, embedded = 0, unusable = 0;
  bag.forEach(function (item, uuid) {
    if (!item) return;
    if (item.locked) { locked++; return; }
    if (item.planInfo && typeof item.planInfo.size === "number" && item.planInfo.size > 0) { embedded++; return; }
    var cfgId = Number(item.cfgId);
    var itemCfg = ItemCfg.getById(cfgId), desireCfg = DesireCfg.getById(cfgId);
    if (!itemCfg || !desireCfg) return;
    var quality = Number(itemCfg.quality), type = Number(desireCfg.type);
    if (!Number.isFinite(quality) || !Number.isFinite(type)) return;
    if (!composeQuality.has(quality)) { unusable++; return; }
    var key = type + ":" + quality;
    var group = groups.get(key);
    if (!group) {
      group = { type: type, quality: quality, count: 0, uuids: [], stacks: [] };
      groups.set(key, group);
    }
    var num = Number(item.num) > 0 ? Number(item.num) : 1;
    group.count += num;
    group.uuids.push(uuid);
    group.stacks.push(num);
  });

  var rows = Array.from(groups.values());
  rows.sort(function (a, b) { return a.type - b.type || a.quality - b.quality; });
  rows.forEach(function (row) {
    row.typeCode = e0e1LabelOf(DesireType, row.type) || ("TYPE" + row.type);
    row.typeName = E0E1_DESIRE_TYPE_LABEL[row.type] || ("种类" + row.type);
    row.qualityName = qualityNames[row.quality] || ("品质" + row.quality);
    // 能配出几对：优先两个不同 uuid，不足时才复用同一堆叠。
    row.pairs = Math.floor(row.count / 2);
    row.distinctUuids = row.uuids.length;
    row.canComposeNow = row.count >= 2;
  });

  return {
    ok: true,
    message: "三尸背包已导出",
    bagId: desire ? Number(desire.bagId) : null,
    composeCnt: desire ? Number(desire.composeCnt) : null,
    qualityNames: qualityNames,
    rates: rates,
    groups: rows,
    excluded: { locked: locked, embedded: embedded, uncomposable: unusable }
  };
}

function e0e1DesireBagText(result) {
  if (!result || !result.ok) return String((result && result.message) || "导出失败");
  var lines = [];
  lines.push("三尸背包（可合成口径，已排除锁定 " + result.excluded.locked +
    " 件、已镶嵌 " + result.excluded.embedded + " 件、品质不可合 " + result.excluded.uncomposable + " 件）");
  lines.push("");
  lines.push("种类\t品质\t可合成数量\t不同uuid\t可配对数\ttypeCode");
  var currentType = null;
  result.groups.forEach(function (row) {
    if (row.type !== currentType) { currentType = row.type; lines.push("── " + row.typeName + " ──"); }
    lines.push(row.qualityName + "\t品质" + row.quality + "\t" + row.count +
      "\t" + row.distinctUuids + "\t" + row.pairs + "\t" + row.typeCode);
  });
  if (!result.groups.length) lines.push("（没有任何可用于合成的三尸）");
  lines.push("");
  lines.push("合成概率表（二合一，来自 ComposeCfg）");
  lines.push("材料品质\t目标品质\t成功率\t失败返还");
  result.rates.forEach(function (rate) {
    lines.push((result.qualityNames[rate.quality] || ("品质" + rate.quality)) +
      "\t" + (result.qualityNames[rate.target] || ("品质" + rate.target)) +
      "\t" + rate.percent + "%\t" + rate.returned);
  });
  if (!result.rates.length) lines.push("（ComposeCfg 里没有 num=2 的行，二合一可能不被支持）");
  lines.push("");
  lines.push("注：失败返还 < 2 时二合一会净亏材料，“永远不亏”不成立。");
  return lines.join("\n");
}

async function e0e1RunDesireDump() {
  var result = await e0e1CollectDesire();
  e0e1Expose("dumpDesireBag", e0e1RunDesireDump);
  e0e1Expose("dumpDesireBagText", async function () {
    return e0e1DesireBagText(await e0e1CollectDesire());
  });
  return { json: result, text: e0e1DesireBagText(result) };
}

var e0e1DesireResult = await e0e1RunDesireDump();
console.log("[e0e1][三尸背包] " + e0e1DesireResult.text);
if (typeof globalThis.__e0e1JsInjectionReport === "function") {
  globalThis.__e0e1JsInjectionReport(e0e1DesireResult.text);
}
