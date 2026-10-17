// ==UserScript==
// @name 战斗伤害曲线采集（支持 PVP 双世界）
// @description 逐条记录伤害事件并分类（普攻/符咒/天书逐本/觉醒分支/技能）。PVP 对局下同时采集我方与敌方两个 World，并按客户端公式采样双方分数与伤害天平。
// @match *
// @run-at document-start
// @e0e1-mode runtime_toggle
// ==/UserScript//

// 用法：
//   python tools/cdp_inject.py --port 62000 --toggle tools/js/damage_curve_probe.js
// 然后在 DevTools Console（切到 gameContext）里：
//   damageCurveText()          文本：PVP 先看分数，再看双方伤害拆解
//   damageCurveJson()          { mode, pvp, self, other }
//   damageCurveCsv()           CSV（含 side 列，双方都在）
//   damageCurveStatus()        当前挂了几个 World / 采了多少事件
//   damageCurveReset() / damageCurveStop()
//
// ── PVP 机制（静态逆向结论，行号指 subpackages/game/game.js）──
//   双分数 PVP 会建两个 World：selfBattleWorld / otherBattleWorld（2010、46504）
//   两个 World 都在 BattleManager.ins.getBattles() 里
//   options.mineInfo 就是各自主人的分数对象 { isSelf, score }（1981-1988、46476-46483）
//     → 有 mineInfo 即双分数 PVP；isSelf 直接区分敌我；score 是真实分数
//   每秒结算一次（2015、46533）：
//     a = 本秒我方 BossDamage 增量, l = 本秒敌方增量
//     p = a/(a+l) − 0.5,  f = l/(a+l) − 0.5
//     g = PVPInitVariable^floor(t) × PVPBaseBonus      ← 时间权重，指数放大
//     selfScore += g*p,  otherScore += g*f              （2040、46556-46565）
//   胜负：任一方分数 > 2×PVPInitScore（2044、46562）或 PVPLimitTime 到时比分高者胜
//   覆盖 battleType：mine(8) / battlefieldDuel(16) / arena(19) / season(20) / goodFriend(26)
//
// ── 跳过战斗 ──
//   好友切磋(26) 的跳过是本地快进：一次同步调用里把整场跑完（46623），
//   伤害事件照发、分数照常结算 → 数据完整，本脚本已按战斗时钟采样所以曲线也不丢。
//   其它 PVP 的跳过走服务端结算、本地不补算 → 只能拿到跳过之前的部分。
//   采集时会记 skipped / skipSafe，报告里如实标注。
//   comp-life.ts:15822 emit $skillDamageCollect(source, skillId, damage, target, isCrit)
//   注意 damage 是 CompLife.sub 返回的实际扣血量（27002），过护盾/格挡/生命保底，会被 overkill 截断

// SkillFunctionType（game.js:30336）
var E0E1_SFT = {
  NONE: 0, ATTACKSKILL: 1, MONSTER: 2, SKILL: 3, RARESKILL: 4, PETSKILL: 5,
  DESIRESKILL: 6, FASHIONSKILL: 7, STORESKILL: 8, PETFUZHOUSKILL: 9,
  PETSKILL_PASSIVE: 10, PETSKILL_AUTO: 11, BASE_SKILL: 12, RARESKILL_SUMMON: 13,
  BASE_SKIN_SKILL: 14, EQUIPMENT_SKILL: 15, EQUIPMENT_STONE_SKILL: 16,
  RARESKILL_CAST: 17, RESTRAINT_SKILL: 18
};

var E0E1_CATEGORIES = [
  { key: "attack", label: "普攻", types: [E0E1_SFT.ATTACKSKILL] },
  { key: "card", label: "符咒", types: [E0E1_SFT.SKILL] },
  { key: "book", label: "天书", types: [E0E1_SFT.RARESKILL, E0E1_SFT.RARESKILL_SUMMON, E0E1_SFT.RARESKILL_CAST] },
  { key: "pet", label: "鬼仆", types: [E0E1_SFT.PETSKILL, E0E1_SFT.PETFUZHOUSKILL, E0E1_SFT.PETSKILL_PASSIVE, E0E1_SFT.PETSKILL_AUTO] },
  { key: "desire", label: "三尸", types: [E0E1_SFT.DESIRESKILL] },
  { key: "epic", label: "法器", types: [E0E1_SFT.EQUIPMENT_SKILL, E0E1_SFT.EQUIPMENT_STONE_SKILL] },
  { key: "flag", label: "战旗", types: [E0E1_SFT.RESTRAINT_SKILL] },
  { key: "fashion", label: "傀儡装", types: [E0E1_SFT.FASHIONSKILL] },
  { key: "store", label: "鬼店", types: [E0E1_SFT.STORESKILL] },
  { key: "base", label: "法相", types: [E0E1_SFT.BASE_SKILL, E0E1_SFT.BASE_SKIN_SKILL] },
  { key: "monster", label: "怪物", types: [E0E1_SFT.MONSTER] },
  { key: "other", label: "其它", types: [] }
];

// ElementalType（game.js:30234）
var E0E1_ELEMENTS = { 0: "", 1: "火", 2: "水", 3: "土", 4: "风" };
// EvolutionPath（game.js:30243）
var E0E1_PATH_NAMES = { 1: "主觉醒", 2: "主阶", 3: "分阶", 4: "副觉醒" };
// 天书类技能在同一本天书里的角色
var E0E1_BOOK_KINDS = { 4: "主技能", 13: "召唤物", 17: "施法" };
// battleType → PVPType（game.js:10437 + 30197）
var E0E1_PVP_TYPE = { 8: 1, 16: 2, 19: 3, 20: 5, 26: 6 };
var E0E1_BATTLE_STATS_BOSS = "BossDamage";
// battleType 中文名（EBattleType，game.js:37128）
var E0E1_BATTLE_TYPE_NAMES = {
  8: "阴墟", 13: "酆都战场", 16: "酆都战场决斗", 19: "竞技场／斗法", 20: "血月战场",
  24: "帧同步对决", 25: "帧同步对决(peer)", 26: "好友切磋"
};
// 只有好友切磋的「跳过」是本地快进（模拟跑完整场），其它 PVP 走服务端结算会丢数据
var E0E1_SKIP_SAFE_TYPES = { 26: true };

var E0E1_TYPE_TO_CAT = {};
for (var e0e1Ci = 0; e0e1Ci < E0E1_CATEGORIES.length; e0e1Ci++) {
  var e0e1Cat = E0E1_CATEGORIES[e0e1Ci];
  for (var e0e1Ti = 0; e0e1Ti < e0e1Cat.types.length; e0e1Ti++) {
    E0E1_TYPE_TO_CAT[e0e1Cat.types[e0e1Ti]] = e0e1Cat.key;
  }
}

var E0E1_RAW_LIMIT = 30000;   // 每一侧的原始事件上限
var E0E1_TOP_PER_SECOND = 8;  // 每秒保留多少个伤害来源（hover 展示取前 5）
var E0E1_SIDES = { self: null, other: null };
var E0E1_HOOKS = [];          // [{ world, handler, tickHandler, state, side }]
var E0E1_WATCHED = [];       // createBattle 钩到的 World，防止被 detach 后轮询不到
var E0E1_BM_PATCHED = false; // BattleManager.createBattle 是否已挂钩
var E0E1_LAST_ERROR = null;  // 最近一次异常，damageCurveDebug() 会报
var E0E1_PVP = { cfg: null, samples: [], attrSeconds: [], lastSecond: -1, battleType: null, skipped: false,
                 instanceKey: null };
var E0E1_TIMER = null;
var E0E1_CFG = null;
var E0E1_CFG_TRIED = false;
var E0E1_BM = null;
var E0E1_BM_TRIED = false;
var E0E1_EVO = null;

// ── 跨上下文 ──

function e0e1ResolveGameWindow() {
  try {
    if (globalThis.UIManager) return globalThis;
  } catch (error) {}
  try {
    var named = globalThis.document && globalThis.document.querySelector('iframe[name="gameContext"]');
    if (named && named.contentWindow && named.contentWindow.UIManager) return named.contentWindow;
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

function e0e1Expose(name, value) {
  globalThis[name] = value;
  try {
    var game = e0e1ResolveGameWindow();
    if (game && game !== globalThis) game[name] = value;
  } catch (error) {}
}

// ── 模块与配置 ──

async function e0e1Import(path) {
  var game = e0e1ResolveGameWindow();
  var loader = game && game.System;
  if (!loader || typeof loader.import !== "function") return null;
  var timeout = new Promise(function (resolve) { setTimeout(function () { resolve(null); }, 3000); });
  try {
    return await Promise.race([loader.import(path), timeout]) || null;
  } catch (error) {
    return null;
  }
}

async function e0e1LoadCfg() {
  if (E0E1_CFG || E0E1_CFG_TRIED) return E0E1_CFG;
  E0E1_CFG_TRIED = true;
  E0E1_CFG = await e0e1Import("chunks:///_virtual/configs.ts");
  return E0E1_CFG;
}

async function e0e1LoadBattleManager() {
  if (E0E1_BM || E0E1_BM_TRIED) return E0E1_BM;
  E0E1_BM_TRIED = true;
  E0E1_BM = await e0e1Import("chunks:///_virtual/battle-manager.ts");
  return E0E1_BM;
}

function e0e1CfgRow(tableName, id) {
  if (!tableName || id === undefined || id === null) return null;
  try {
    var table = E0E1_CFG && E0E1_CFG[tableName];
    if (!table || typeof table.getById !== "function") return null;
    return table.getById(Number(id)) || null;
  } catch (error) {
    return null;
  }
}

function e0e1CfgName(tableName, id) {
  var row = e0e1CfgRow(tableName, id);
  if (!row) return null;
  var candidates = [row.name, row.Name, row.cfgName, row.title];
  for (var i = 0; i < candidates.length; i++) {
    if (candidates[i] && /[一-龥]/.test(String(candidates[i]))) return String(candidates[i]);
  }
  return null;
}

// ── 觉醒分支反查 ──

function e0e1BuildEvoIndex() {
  var index = {};
  var evoSkill = E0E1_CFG && E0E1_CFG.EvolutionSkillCfg;
  var branchCfg = E0E1_CFG && E0E1_CFG.SkillBookEvolutionCfg;
  if (!evoSkill || !evoSkill.list) return index;
  for (var i = 0; i < evoSkill.list.length; i++) {
    var row = evoSkill.list[i];
    if (!row || !row.skillId) continue;
    var branch = branchCfg && branchCfg.getById ? branchCfg.getById(row.evolutionId) : null;
    index[String(row.skillId)] = {
      branchId: branch ? branch.id : (row.evolutionId || null),
      branchName: branch ? (branch.name || branch.nodeName || null) : null,
      branchLevel: row.skillLevel !== undefined ? row.skillLevel : null,
      path: branch ? branch.evolutionPath : null,
      bookId: branch ? branch.skillBookBelong : null
    };
  }
  return index;
}

function e0e1EvoOf(skillId) {
  if (!E0E1_EVO) E0E1_EVO = e0e1BuildEvoIndex();
  return E0E1_EVO[String(skillId)] || null;
}

// ── 技能来源反查 ──
// SkillFunctionType 的枚举名有历史遗留（15/16 叫 EQUIPMENT_*，但真正提供技能的是法器系配置表），
// 所以不猜名字，直接按配置表里的技能字段建索引：某个 skillId 出现在哪张表里就是哪个来源。
//
//   MagicArtifactBaseCfg.skill        法器
//   MagicArtifactStoneCfg.skill       法器宝石
//   MagicArtifactTemperSkillCfg.skill 法器淬炼
//   EquipmentSuitSkillCfg.skillId     脸谱套装
//   FashionCfg.skill / attackSkill    傀儡装
//   BaseSkinCfg.skill                 基地法相
var E0E1_ORIGIN = null;
var E0E1_ORIGIN_SOURCES = [
  { table: "MagicArtifactBaseCfg", fields: ["skill"], label: "法器" },
  { table: "MagicArtifactStoneCfg", fields: ["skill"], label: "法器宝石" },
  { table: "MagicArtifactTemperSkillCfg", fields: ["skill"], label: "法器淬炼" },
  { table: "EquipmentSuitSkillCfg", fields: ["skillId"], label: "脸谱套装" },
  { table: "FashionCfg", fields: ["skill", "attackSkill"], label: "傀儡装" },
  { table: "BaseSkinCfg", fields: ["skill"], label: "基地法相" }
];

function e0e1BuildOriginIndex() {
  var index = {};
  for (var s = 0; s < E0E1_ORIGIN_SOURCES.length; s++) {
    var source = E0E1_ORIGIN_SOURCES[s];
    var table = E0E1_CFG && E0E1_CFG[source.table];
    if (!table || !table.list) continue;
    for (var i = 0; i < table.list.length; i++) {
      var row = table.list[i];
      if (!row) continue;
      for (var f = 0; f < source.fields.length; f++) {
        var raw = row[source.fields[f]];
        if (Array.isArray(raw)) {
          for (var k = 0; k < raw.length; k++) if (raw[k]) index[String(raw[k])] = source.label;
        } else if (raw) {
          index[String(raw)] = source.label;
        }
      }
    }
  }
  return index;
}

function e0e1OriginOf(skillId) {
  if (!E0E1_ORIGIN) E0E1_ORIGIN = e0e1BuildOriginIndex();
  return E0E1_ORIGIN[String(skillId)] || null;
}

function e0e1BranchSkillIds(branchCfg, level) {
  var out = [];
  if (!branchCfg || !branchCfg.evolutionSkillId) return out;
  for (var i = 0; i < level && i < branchCfg.evolutionSkillId.length; i++) {
    var eid = branchCfg.evolutionSkillId[i];
    if (!eid) continue;
    var row = e0e1CfgRow("EvolutionSkillCfg", eid);
    if (row && row.skillId) out.push(row.skillId);
  }
  return out;
}

function e0e1ReadActiveBranches(world) {
  var out = [];
  try {
    var team = world && world.options && world.options.battleData &&
      world.options.battleData.leftTeam && world.options.battleData.leftTeam.team;
    if (!team || !team.length) return out;
    var awakening = null;
    for (var i = 0; i < team.length; i++) {
      if (team[i] && team[i].epicAwakening) awakening = team[i].epicAwakening;
    }
    if (!awakening || typeof awakening.forEach !== "function") return out;
    awakening.forEach(function (levels, bookId) {
      if (!levels || typeof levels.forEach !== "function") return;
      levels.forEach(function (level, branchId) {
        if (!(level > 0)) return;
        var bcfg = e0e1CfgRow("SkillBookEvolutionCfg", branchId);
        out.push({
          bookId: Number(bookId),
          bookName: e0e1CfgName("SkillBookCfg", bookId) || ("天书" + bookId),
          branchId: Number(branchId),
          branchName: (bcfg && (bcfg.name || bcfg.nodeName)) || ("分支" + branchId),
          level: level,
          path: bcfg ? bcfg.evolutionPath : null,
          pathName: E0E1_PATH_NAMES[bcfg ? bcfg.evolutionPath : 0] || "未知",
          skillIds: e0e1BranchSkillIds(bcfg, level)
        });
      });
    });
  } catch (error) {}
  return out;
}

// ── 找战斗 World 并区分敌我 ──

function e0e1WorldsFromManager() {
  var BM = E0E1_BM && E0E1_BM.BattleManager;
  var ins = BM && BM.ins;
  if (!ins || typeof ins.getBattles !== "function") return [];
  try {
    var list = ins.getBattles() || [];
    var out = [];
    for (var i = 0; i < list.length; i++) {
      if (list[i] && list[i].battleSignal) out.push(list[i]);
    }
    return out;
  } catch (error) {
    return [];
  }
}

function e0e1WorldsFromUi() {
  var game = e0e1ResolveGameWindow();
  var ins = game && game.UIManager && game.UIManager.ins;
  if (!ins || !ins.viewParams) return [];
  var out = [];
  for (var key in ins.viewParams) {
    var param = ins.viewParams[key];
    if (!param || !param.showing || !param.ui) continue;
    if (param.ui.battleWorld && param.ui.battleWorld.battleSignal) out.push(param.ui.battleWorld);
  }
  return out;
}

// 双分数 PVP 的 World 会带 options.mineInfo = { isSelf, score }
function e0e1MineInfoOf(world) {
  try {
    var mi = world && world.options && world.options.mineInfo;
    if (mi && typeof mi === "object" && typeof mi.score === "number") return mi;
  } catch (error) {}
  return null;
}

function e0e1SideOf(world) {
  var mi = e0e1MineInfoOf(world);
  if (mi) return mi.isSelf ? "self" : "other";
  return "self"; // 单世界（PVE）默认算我方
}

function e0e1FindWorlds() {
  var list = e0e1WorldsFromManager();
  var fromUi = list.length === 0;
  if (fromUi) {
    var uiList = e0e1WorldsFromUi();
    var out = [];
    for (var i = 0; i < uiList.length; i++) {
      out.push({ world: uiList[i], side: e0e1SideOf(uiList[i]), fromUi: true });
    }
    return out;
  }
  var result = [];
  for (var j = 0; j < list.length; j++) {
    result.push({ world: list[j], side: e0e1SideOf(list[j]), fromUi: false });
  }
  return result;
}

// ── PVP 配置与分数采样 ──

function e0e1ReadPvpCfg(battleType) {
  var pvpType = E0E1_PVP_TYPE[battleType];
  if (!pvpType) return null;
  var table = E0E1_CFG && E0E1_CFG.PVPcfg;
  if (!table || !table.list) return null;
  for (var i = 0; i < table.list.length; i++) {
    if (table.list[i] && table.list[i].PVPType === pvpType) return table.list[i];
  }
  return null;
}

function e0e1ScoreOf(world) {
  var mi = e0e1MineInfoOf(world);
  return mi ? mi.score : null;
}

function e0e1BossDamageOf(world) {
  try {
    return world.statistics.get(E0E1_BATTLE_STATS_BOSS, 0) || 0;
  } catch (error) {
    return 0;
  }
}

// 每整秒记一次双方分数与对敌方英雄累计伤害
function e0e1SamplePvp() {
  var self = E0E1_SIDES.self;
  if (!self || !self.world) return;
  var world = self.world;
  var t = 0;
  try {
    t = world.battleTime.battleTime || 0;
  } catch (error) {}
  // 跳过战斗时 battleTime.isSkipping 为真（11791）：标记一下，报告里如实说明
  try {
    if (world.battleTime && world.battleTime.isSkipping) E0E1_PVP.skipped = true;
  } catch (error) {}
  var sec = Math.floor(t);
  if (sec === E0E1_PVP.lastSecond) return;

  var other = E0E1_SIDES.other;
  var selfScore = e0e1ScoreOf(world);
  var otherScore = other && other.world ? e0e1ScoreOf(other.world) : null;
  if (selfScore === null && otherScore === null) return; // 不是双分数 PVP

  if (!E0E1_PVP.cfg) {
    E0E1_PVP.cfg = e0e1ReadPvpCfg(world.options && world.options.battleData ? world.options.battleData.type : null);
    E0E1_PVP.battleType = world.options && world.options.battleData ? world.options.battleData.type : null;
  }
  E0E1_PVP.lastSecond = sec;
  E0E1_PVP.samples.push({
    t: t,
    sec: sec,
    selfScore: selfScore === null ? 0 : selfScore,
    otherScore: otherScore === null ? 0 : otherScore,
    selfBoss: e0e1BossDamageOf(world),
    otherBoss: other && other.world ? e0e1BossDamageOf(other.world) : 0
  });
  // 双方属性按秒快照（英雄可能还没创建，读不到就是空对象）
  E0E1_PVP.attrSeconds.push({
    sec: sec,
    self: e0e1ReadHeroAttrs(world),
    other: other && other.world ? e0e1ReadHeroAttrs(other.world) : {}
  });
}

// 按客户端公式复算分数增量，用来和游戏实际分数对账（2027-2045）
function e0e1DerivedScores(samples, cfg) {
  var base = cfg && cfg.PVPBaseBonus !== undefined ? cfg.PVPBaseBonus : 0;
  var variable = cfg && cfg.PVPInitVariable !== undefined ? cfg.PVPInitVariable : 0;
  // 双方分数都从 PVPInitScore 起步（1983、46478：score 初值 = PVPInitScore）
  var init = cfg && cfg.PVPInitScore !== undefined ? cfg.PVPInitScore : 0;
  var selfScore = init, otherScore = init;
  var prevSelf = 0, prevOther = 0;
  var out = [];
  for (var i = 0; i < samples.length; i++) {
    var s = samples[i];
    var a = s.selfBoss - prevSelf;
    var l = s.otherBoss - prevOther;
    prevSelf = s.selfBoss;
    prevOther = s.otherBoss;
    var share = 0.5;
    var deltaSelf = 0, deltaOther = 0;
    var weight = Math.pow(variable, s.sec) * base;
    if (a + l > 0) {
      share = a / (a + l);
      deltaSelf = weight * (share - 0.5);
      deltaOther = weight * ((1 - share) - 0.5);
      selfScore += deltaSelf;
      otherScore += deltaOther;
    }
    out.push({
      t: s.t, sec: s.sec,
      selfDmg: a, otherDmg: l,
      share: a + l > 0 ? share : null,
      weight: weight,
      deltaSelf: deltaSelf, deltaOther: deltaOther,
      selfScore: selfScore, otherScore: otherScore
    });
  }
  return out;
}

// ── 玩家信息（对战双方 / 局内属性 / 养成配置）──

// 局内属性：BattleAttributeKey（30142）。
// p = 是否百分比。显式写死而不是读 AttrCfg.style：百分比属性的值是 ×100 后的整数
//   （23000 → 230%），数值类（攻击/生命）不换算。
// 中文名优先取 AttrCfg.note（AttrCfg.name 是数字不能用），拿不到就用下面的短标签。
var E0E1_ATTR_KEYS = [
  { key: 1, label: "攻击", p: false },
  { key: 4, label: "生命", p: false },
  { key: 8, label: "攻速", p: false },
  { key: 101, label: "暴击率", p: true },
  { key: 102, label: "暴击伤害", p: true },
  { key: 106, label: "法术暴击率", p: true },
  { key: 107, label: "法术爆伤", p: true },
  { key: 104, label: "伤害加成", p: true },
  { key: 105, label: "伤害减免", p: true },
  { key: 115, label: "天书增伤", p: true },
  { key: 116, label: "符咒增伤", p: true },
  { key: 117, label: "PVP增伤", p: true },
  { key: 118, label: "PVP减伤", p: true },
  { key: 123, label: "最终增伤", p: true },
  { key: 124, label: "最终减伤", p: true },
  { key: 131, label: "鬼仆增伤", p: true },
  { key: 133, label: "法器增伤", p: true },
  { key: 708, label: "普攻增伤", p: true },
  { key: 709, label: "普攻减伤", p: true }
];
// 派生属性：最终PVP增伤 = 我方PVP增伤(117) − 对方PVP减伤(118)
var E0E1_FINAL_PVP_KEY = "finalPvp";
var E0E1_FINAL_PVP_META = { key: E0E1_FINAL_PVP_KEY, label: "最终PVP增伤", note: "最终PVP增伤", percent: true };

var E0E1_ATTR_META = null;

// 官方中文名优先（AttrCfg.note），拿不到就用上面的短标签
function e0e1AttrMeta() {
  if (E0E1_ATTR_META) return E0E1_ATTR_META;
  var out = [];
  for (var i = 0; i < E0E1_ATTR_KEYS.length; i++) {
    var item = E0E1_ATTR_KEYS[i];
    var row = e0e1CfgRow("AttrCfg", item.key);
    var note = row && row.note ? String(row.note) : null;
    out.push({
      key: item.key,
      label: item.label,
      note: note || item.label,
      percent: !!item.p
    });
  }
  out.push(E0E1_FINAL_PVP_META);
  E0E1_ATTR_META = out;
  return out;
}

// 返回 { attrKey: number }，属性可能不存在就跳过
function e0e1ReadHeroAttrs(world) {
  var out = {};
  try {
    var hero = world.getFightHero && world.getFightHero();
    var attrs = hero && hero.compAttributes;
    if (!attrs) return out;
    for (var i = 0; i < E0E1_ATTR_KEYS.length; i++) {
      var item = E0E1_ATTR_KEYS[i];
      var value = attrs.get(item.key);
      if (value === undefined || value === null) continue;
      var num = typeof value.toNumber === "function" ? value.toNumber() : Number(value);
      if (!isFinite(num)) continue;
      out[item.key] = num;
    }
  } catch (error) {}
  return out;
}

// 队伍成员字段在不同版本里不一定齐全，全部防御式读取：有就拿，没有就跳过
function e0e1ReadFighterInfo(member) {
  if (!member) return null;
  var info = { books: [], awakenings: [], desires: [], pets: [], equipment: [] };
  ["roleId", "id", "name", "sName", "level", "heroId", "fightPower", "maxFightPower"].forEach(function (field) {
    if (member[field] !== undefined && member[field] !== null) info[field] = member[field];
  });

  try {
    var equip = member.equipSkill;
    var levels = member.skillLevel;
    if (equip && typeof equip.forEach === "function") {
      equip.forEach(function (bookId, slot) {
        info.books.push({
          slot: slot,
          bookId: Number(bookId),
          name: e0e1CfgName("SkillBookCfg", bookId) || ("天书" + bookId),
          level: (levels && levels.get) ? (levels.get(bookId) || null) : null
        });
      });
    }
  } catch (error) {}

  try {
    var aw = member.epicAwakening;
    if (aw && typeof aw.forEach === "function") {
      aw.forEach(function (levels, bookId) {
        if (!levels || typeof levels.forEach !== "function") return;
        levels.forEach(function (level, branchId) {
          if (!(level > 0)) return;
          var bcfg = e0e1CfgRow("SkillBookEvolutionCfg", branchId);
          info.awakenings.push({
            bookId: Number(bookId),
            bookName: e0e1CfgName("SkillBookCfg", bookId) || ("天书" + bookId),
            branchId: Number(branchId),
            branchName: (bcfg && (bcfg.name || bcfg.nodeName)) || ("分支" + branchId),
            level: level,
            pathName: E0E1_PATH_NAMES[bcfg ? bcfg.evolutionPath : 0] || "未知"
          });
        });
      });
    }
  } catch (error) {}

  try {
    var plan = member.desirePlan;
    if (!plan && member.allDesirePlan && member.allDesirePlan.get) {
      plan = member.allDesirePlan.get(member.planId || 0);
    }
    if (plan && typeof plan.forEach === "function") {
      plan.forEach(function (desireId, key) {
        var row = e0e1CfgRow("DesireCfg", desireId);
        var name = null;
        if (row) name = e0e1CfgName("DesireCfg", desireId) || (row.itemId && row.itemId.name) || null;
        info.desires.push({ key: key, desireId: Number(desireId), name: name || ("三尸" + desireId) });
      });
    }
  } catch (error) {}

  try {
    var pet = member.pet;
    var formation = member.formationPetInfo;
    var pets = [];
    if (formation && typeof formation.forEach === "function") {
      formation.forEach(function (value, key) { pets.push({ key: key, value: value }); });
    }
    if (!pets.length && pet) {
      var cfgId = pet.cfgId !== undefined ? pet.cfgId : (pet.id !== undefined ? pet.id : null);
      if (cfgId) pets.push({ key: 0, value: { cfgId: cfgId } });
    }
    pets.forEach(function (entry) {
      var raw = entry.value || {};
      var cfgId = raw.cfgId !== undefined ? raw.cfgId : (raw.id !== undefined ? raw.id : null);
      var skillLevel = raw.skillLevel !== undefined ? raw.skillLevel : null;
      info.pets.push({
        key: entry.key,
        cfgId: cfgId,
        name: cfgId ? (e0e1CfgName("PetCfg", cfgId) || ("鬼仆" + cfgId)) : null,
        skillLevel: skillLevel
      });
    });
  } catch (error) {}

  try {
    var equipment = member.equipment;
    if (equipment && typeof equipment.forEach === "function") {
      equipment.forEach(function (item, slot) {
        if (!item) return;
        info.equipment.push({
          slot: slot,
          configId: item.configId !== undefined ? item.configId : null,
          name: item.configId ? (e0e1CfgName("EquipmentCfg", item.configId) || null) : null,
          level: item.level !== undefined ? item.level : null
        });
      });
    }
  } catch (error) {}

  return info;
}

// 我方 World 的 leftTeam 是我方、rightTeam 是敌方（敌方 World 反过来了，1992）
function e0e1ReadPlayers(world) {
  var out = { self: null, other: null, heroAttrs: null };
  try {
    var data = world && world.options && world.options.battleData;
    if (!data) return out;
    if (data.leftTeam && data.leftTeam.team && data.leftTeam.team.length) {
      out.self = e0e1ReadFighterInfo(data.leftTeam.team[0]);
    }
    if (data.rightTeam && data.rightTeam.team && data.rightTeam.team.length) {
      out.other = e0e1ReadFighterInfo(data.rightTeam.team[0]);
    }
    out.heroAttrs = e0e1ReadHeroAttrs(world);
  } catch (error) {}
  return out;
}

// ── 单侧状态与聚合 ──

function e0e1NewState(world, side, fromUi) {
  return {
    world: world,
    fromUi: !!fromUi,
    side: side,
    instanceId: world && world.instanceId,
    battleType: (world && world.options && world.options.battleData && world.options.battleData.type),
    seed: (world && world.options && world.options.battleData && world.options.battleData.randomSeed),
    bucket: 1,
    events: [],
    truncated: false,
    eventCount: 0,
    lastTime: 0,
    buckets: {},
    total: {},
    skills: {},
    books: {},
    bookCurves: {}, bookBossCurves: {},
    branches: {},
    branchCurves: {}, branchBossCurves: {},
    skillCurves: {}, skillBossCurves: {},
    activeBranches: [],
    players: null
  };
}

function e0e1Bump(map, key, dmg, isCrit) {
  var slot = map[key];
  if (!slot) slot = map[key] = { dmg: 0, hits: 0, crits: 0 };
  slot.dmg += dmg;
  slot.hits += 1;
  if (isCrit) slot.crits += 1;
}

function e0e1Classify(skillId) {
  var row = e0e1CfgRow("SkillCfg", skillId);
  var sft = row && row.skillFunctionType !== undefined ? row.skillFunctionType : -1;
  var cat = E0E1_TYPE_TO_CAT[sft] || "other";
  var bookId = row && row.bookId ? row.bookId : null;
  if (cat === "book" && !bookId) {
    var guess = 100 * Math.floor(Number(skillId) / 100);
    if (e0e1CfgRow("SkillBookCfg", guess)) bookId = guess;
  }
  var evo = e0e1EvoOf(skillId);
  if (evo && evo.bookId) bookId = evo.bookId;
  return {
    sft: sft,
    cat: cat,
    skillName: e0e1CfgName("SkillCfg", skillId) || ("技能" + skillId),
    bookId: bookId,
    bookName: bookId ? (e0e1CfgName("SkillBookCfg", bookId) || ("天书" + bookId)) : null,
    element: cat === "card" ? (E0E1_ELEMENTS[row ? row.elementalType : 0] || "") : "",
    branchId: evo ? evo.branchId : null,
    branchName: evo ? (evo.branchName || ("分支" + evo.branchId)) : null,
    branchLevel: evo ? evo.branchLevel : null,
    branchPath: evo ? evo.path : null,
    branchPathName: evo ? (E0E1_PATH_NAMES[evo.path] || "未知") : null,
    // 技能来源（按配置表反查，不用枚举名猜）
    origin: e0e1OriginOf(skillId),
    kind: cat === "book" ? (E0E1_BOOK_KINDS[sft] || "其它") : ""
  };
}

function e0e1MakeHandler(state) {
  return function (source, skillId, damage, target, isCrit) {
    if (!state || !state.world) return;
    var dmg = Number(damage) || 0;
    if (dmg <= 0) return;
    var t = 0;
    try {
      t = state.world.battleTime.battleTime || 0;
    } catch (error) {}
    state.lastTime = Math.max(state.lastTime, t);
    state.eventCount += 1;

    var info = e0e1Classify(skillId);
    var isBoss = !!(target && target.compBoss);
    var isElite = !!(target && target.compElite);
    var self = !!(source && source.compCampFriend);

    if (state.events.length < E0E1_RAW_LIMIT) {
      state.events.push({
        t: t,
        skill: Number(skillId),
        skillName: info.skillName,
        cat: info.cat,
        kind: info.kind,
        book: info.bookId,
        bookName: info.bookName,
        branch: info.branchId,
        branchName: info.branchName,
        branchLevel: info.branchLevel,
        branchPath: info.branchPath,
        elem: info.element,
        origin: info.origin,
        dmg: dmg,
        crit: !!isCrit,
        boss: isBoss,
        elite: isElite,
        self: self
      });
    } else {
      state.truncated = true;
    }

    var bucket = Math.floor(t / state.bucket);
    var slot = state.buckets[bucket];
    if (!slot) slot = state.buckets[bucket] = { all: {}, boss: {} };
    e0e1Bump(slot.all, info.cat, dmg, isCrit);
    if (isBoss) e0e1Bump(slot.boss, info.cat, dmg, isCrit);
    e0e1Bump(slot.all, "__total", dmg, isCrit);

    e0e1Bump(state.total, info.cat, dmg, isCrit);
    e0e1Bump(state.total, "__total", dmg, isCrit);
    if (isBoss) e0e1Bump(state.total, "__boss", dmg, isCrit);

    var key = String(Number(skillId));
    var sk = state.skills[key];
    if (!sk) {
      sk = state.skills[key] = {
        dmg: 0, hits: 0, crits: 0, cat: info.cat, name: info.skillName,
        book: info.bookId, bookName: info.bookName, elem: info.element,
        branch: info.branchId, branchName: info.branchName,
        branchLevel: info.branchLevel, kind: info.kind, origin: info.origin
      };
    }
    sk.dmg += dmg;
    sk.hits += 1;
    if (isCrit) sk.crits += 1;

    var sc = state.skillCurves[key];
    if (!sc) sc = state.skillCurves[key] = {};
    sc[bucket] = (sc[bucket] || 0) + dmg;
    if (isBoss) {
      var sbc = state.skillBossCurves[key];
      if (!sbc) sbc = state.skillBossCurves[key] = {};
      sbc[bucket] = (sbc[bucket] || 0) + dmg;
    }

    if (info.bookId) {
      var bkey = String(info.bookId);
      if (!state.books[bkey]) state.books[bkey] = { dmg: 0, hits: 0, name: info.bookName };
      state.books[bkey].dmg += dmg;
      state.books[bkey].hits += 1;
      var bc = state.bookCurves[bkey];
      if (!bc) bc = state.bookCurves[bkey] = {};
      bc[bucket] = (bc[bucket] || 0) + dmg;
      if (isBoss) {
        var bbc = state.bookBossCurves[bkey];
        if (!bbc) bbc = state.bookBossCurves[bkey] = {};
        bbc[bucket] = (bbc[bucket] || 0) + dmg;
      }
    }

    if (info.branchId) {
      var rkey = String(info.branchId);
      if (!state.branches[rkey]) {
        state.branches[rkey] = {
          dmg: 0, hits: 0, name: info.branchName, book: info.bookId,
          bookName: info.bookName, level: info.branchLevel,
          path: info.branchPath, pathName: info.branchPathName
        };
      }
      state.branches[rkey].dmg += dmg;
      state.branches[rkey].hits += 1;
      if (info.branchLevel && (!state.branches[rkey].level || info.branchLevel > state.branches[rkey].level)) {
        state.branches[rkey].level = info.branchLevel;
      }
      var rc = state.branchCurves[rkey];
      if (!rc) rc = state.branchCurves[rkey] = {};
      rc[bucket] = (rc[bucket] || 0) + dmg;
      if (isBoss) {
        var rbc = state.branchBossCurves[rkey];
        if (!rbc) rbc = state.branchBossCurves[rkey] = {};
        rbc[bucket] = (rbc[bucket] || 0) + dmg;
      }
    }
  };
}

// ── 挂接 / 摘除 ──

// 单个 World 的挂接（可重复调用，已挂的会跳过）。
// 拆成独立函数是因为要在 createBattle 的钩子里同步调用：
// 好友切磋跳过时第一件事就是 detachBattleWorlds 把 World 移出 getBattles()，
// 只靠 500ms 轮询的话，用户一进战斗就点跳过我们就一次都轮不到。
function e0e1TryAttachWorld(world) {
  if (!world || !world.battleSignal) return false;
  for (var i = 0; i < E0E1_HOOKS.length; i++) {
    if (E0E1_HOOKS[i].world === world) return true;
  }
  var sig = world.battleSignal["$skillDamageCollect"];
  if (!sig || typeof sig.add !== "function") return false;   // 信号还没初始化，等下一次
  var side = e0e1SideOf(world);
  var state = e0e1NewState(world, side, false);
  state.activeBranches = e0e1ReadActiveBranches(world);
  var players = e0e1ReadPlayers(world);
  if (side === "other") {
    // 敌方 World 的 leftTeam/rightTeam 是反的（1992），换回来才好读
    var swap = players.self;
    players.self = players.other;
    players.other = swap;
  }
  state.players = players;
  var handler = e0e1MakeHandler(state);
  sig.add(handler, null);
  // 分数采样挂战斗内时钟，不能只靠实时定时器：
  // 好友切磋「跳过」会把整场在一次同步调用里跑完（46623），实时定时器插不进去，
  // 曲线会塌成一个点。timeBattleTickSignal 在 world.update() 内部触发，快进时每步都发。
  var tickHandler = null;
  var tickSig = world.battleSignal["timeBattleTickSignal"];
  if (tickSig && typeof tickSig.add === "function") {
    tickHandler = function () { e0e1SamplePvp(); };
    tickSig.add(tickHandler, null);
  }
  E0E1_HOOKS.push({ world: world, handler: handler, tickHandler: tickHandler,
                    state: state, side: side });
  E0E1_SIDES[side] = state;
  if (side === "self") e0e1ResetPvpIfNewBattle(state);
  return true;
}

// 分数采样是全局累积的（不走 E0E1_SIDES），不按场次归零的话
// 第二场会接着第一场的秒数往下记，时间轴被拼成两场之和。
function e0e1ResetPvpIfNewBattle(state) {
  var key = String(state.instanceId) + "|" + String(state.battleType) + "|" + String(state.seed);
  if (!E0E1_PVP.instanceKey) {
    E0E1_PVP.instanceKey = key;
    E0E1_PVP.battleType = state.battleType;
    return false;
  }
  if (E0E1_PVP.instanceKey === key) return false;
  E0E1_PVP.samples = [];
  E0E1_PVP.attrSeconds = [];
  E0E1_PVP.lastSecond = -1;
  E0E1_PVP.cfg = null;
  E0E1_PVP.battleType = state.battleType;
  E0E1_PVP.skipped = false;
  E0E1_PVP.instanceKey = key;
  return true;
}

function e0e1WatchWorld(world) {
  if (!world) return;
  if (E0E1_WATCHED.indexOf(world) < 0) {
    E0E1_WATCHED.push(world);
    if (E0E1_WATCHED.length > 8) E0E1_WATCHED.shift();
  }
  e0e1TryAttachWorld(world);
}

// 在 BattleManager.createBattle 上挂钩：World 一创建就挂上，
// 不等 500ms 轮询，也不怕它随后被 detach。
function e0e1PatchBattleManager() {
  if (E0E1_BM_PATCHED || !E0E1_BM) return false;
  var BM = E0E1_BM.BattleManager;
  var ins = BM && BM.ins;
  if (!ins) return false;
  var patched = false;

  // (1) World 一创建就挂。注意 battleSignal 的信号可能是延迟建好的，这里挂不上没关系，
  //     下面的 detachBattleWorlds 兜底，轮询也会补挂。
  if (typeof ins.createBattle === "function" && !ins.__e0e1CreatePatched) {
    var createOriginal = ins.createBattle;
    ins.createBattle = function (type, options) {
      var world = createOriginal.call(ins, type, options);
      try {
        e0e1WatchWorld(world);
      } catch (error) {}
      return world;
    };
    ins.__e0e1CreatePatched = true;
    patched = true;
  }

  // (2) 关键兜底：好友切磋跳过时 skipBattleLocalFastForward 会先调 detachBattleWorlds
  //     再跑同步快进循环（46622）。此时 World 已建好、信号就绪，正好赶在快进之前挂上。
  if (typeof ins.detachBattleWorlds === "function" && !ins.__e0e1DetachPatched) {
    var detachOriginal = ins.detachBattleWorlds;
    ins.detachBattleWorlds = function (worlds) {
      try {
        var list = worlds || [];
        for (var i = 0; i < list.length; i++) e0e1WatchWorld(list[i]);
      } catch (error) {}
      return detachOriginal.call(ins, worlds);
    };
    ins.__e0e1DetachPatched = true;
    patched = true;
  }

  if (patched) E0E1_BM_PATCHED = true;
  return patched;
}

function e0e1AttachAll() {
  if (!E0E1_BM_PATCHED) e0e1PatchBattleManager();
  // 候选 = createBattle 钩到的 + getBattles() 里现存的
  var candidates = [];
  for (var a = 0; a < E0E1_WATCHED.length; a++) {
    var watched = E0E1_WATCHED[a];
    if (watched && !watched.isQuitted) candidates.push(watched);
  }
  var found = e0e1FindWorlds();
  for (var b = 0; b < found.length; b++) {
    var world = found[b].world;
    if (candidates.indexOf(world) < 0) candidates.push(world);
  }
  var alive = [];
  for (var c = 0; c < candidates.length; c++) {
    if (e0e1TryAttachWorld(candidates[c])) alive.push(candidates[c]);
  }
  for (var k = E0E1_HOOKS.length - 1; k >= 0; k--) {
    if (alive.indexOf(E0E1_HOOKS[k].world) >= 0) continue;
    var dead = E0E1_HOOKS[k];
    try {
      var dsig = dead.world.battleSignal && dead.world.battleSignal["$skillDamageCollect"];
      if (dsig && typeof dsig.remove === "function") dsig.remove(dead.handler, null);
      if (dead.tickHandler) {
        var tsig = dead.world.battleSignal && dead.world.battleSignal["timeBattleTickSignal"];
        if (tsig && typeof tsig.remove === "function") tsig.remove(dead.tickHandler, null);
      }
    } catch (error) {}
    E0E1_HOOKS.splice(k, 1);
  }
}

function e0e1DetachAll() {
  for (var i = 0; i < E0E1_HOOKS.length; i++) {
    try {
      var sig = E0E1_HOOKS[i].world.battleSignal && E0E1_HOOKS[i].world.battleSignal["$skillDamageCollect"];
      if (sig && typeof sig.remove === "function") sig.remove(E0E1_HOOKS[i].handler, null);
      if (E0E1_HOOKS[i].tickHandler) {
        var tsig = E0E1_HOOKS[i].world.battleSignal && E0E1_HOOKS[i].world.battleSignal["timeBattleTickSignal"];
        if (tsig && typeof tsig.remove === "function") tsig.remove(E0E1_HOOKS[i].tickHandler, null);
      }
    } catch (error) {}
  }
  E0E1_HOOKS = [];
  E0E1_WATCHED = [];
  E0E1_SIDES = { self: null, other: null };
  E0E1_PVP = { cfg: null, samples: [], attrSeconds: [], lastSecond: -1, battleType: null, skipped: false, instanceKey: null };
}

// ── 输出 ──

function e0e1Num(n) {
  n = Number(n) || 0;
  if (n >= 1e8) return (n / 1e8).toFixed(2) + "亿";
  if (n >= 1e4) return (n / 1e4).toFixed(2) + "万";
  return String(Math.round(n));
}

var E0E1_SPARK = "▁▂▃▄▅▆▇█";

function e0e1Spark(values, width) {
  width = width || 60;
  if (!values.length) return "";
  if (values.length <= width) {
    var max = 0;
    for (var m = 0; m < values.length; m++) max = Math.max(max, values[m]);
    var out = "";
    for (var i = 0; i < values.length; i++) {
      out += max <= 0 ? E0E1_SPARK[0] : E0E1_SPARK[Math.min(7, Math.floor(values[i] / max * 7.999))];
    }
    return out;
  }
  var step = values.length / width;
  var sampled = [];
  for (var b = 0; b < width; b++) {
    var lo = Math.floor(b * step), hi = Math.floor((b + 1) * step);
    var sum = 0, cnt = 0;
    for (var q = lo; q < hi && q < values.length; q++) { sum += values[q]; cnt++; }
    sampled.push(cnt ? sum / cnt : 0);
  }
  return e0e1Spark(sampled, width);
}

function e0e1Cumulative(values) {
  var out = [], sum = 0;
  for (var i = 0; i < values.length; i++) { sum += values[i]; out.push(sum); }
  return out;
}

function e0e1Curve(map, key, count) {
  var m = map[key];
  var out = [];
  for (var i = 0; i < count; i++) out.push(m && m[i] ? m[i] : 0);
  return out;
}

function e0e1LabelOf(key) {
  for (var i = 0; i < E0E1_CATEGORIES.length; i++) {
    if (E0E1_CATEGORIES[i].key === key) return E0E1_CATEGORIES[i].label;
  }
  return key === "__total" ? "合计" : (key === "__boss" ? "对BOSS" : key);
}

function e0e1VisibleLen(text) {
  text = String(text);
  var len = 0;
  for (var i = 0; i < text.length; i++) len += text.charCodeAt(i) > 0x2e80 ? 2 : 1;
  return len;
}

function e0e1Pad(text, width, alignRight) {
  text = String(text);
  var pad = width - e0e1VisibleLen(text);
  if (pad <= 0) return text;
  var filler = new Array(pad + 1).join(" ");
  return alignRight ? filler + text : text + filler;
}

function e0e1TopAt(curveMap, state, bucket) {
  var rows = [];
  for (var skillId in curveMap) {
    var m = curveMap[skillId];
    var dmg = m && m[bucket] ? m[bucket] : 0;
    if (dmg <= 0) continue;
    var sk = state.skills[skillId];
    rows.push({
      skillId: Number(skillId),
      name: sk ? sk.name : ("技能" + skillId),
      origin: sk ? sk.origin : null,
      cat: sk ? sk.cat : null,
      book: sk ? sk.bookName : null,
      branch: sk ? sk.branchName : null,
      dmg: dmg
    });
  }
  rows.sort(function (a, b) { return b.dmg - a.dmg; });
  return rows.slice(0, E0E1_TOP_PER_SECOND);
}

function e0e1CollectSide(state) {
  if (!state) return null;
  var count = 0;
  for (var bk in state.buckets) count = Math.max(count, Number(bk) + 1);

  var cats = [];
  for (var key in state.total) {
    if (key === "__total" || key === "__boss") continue;
    cats.push({
      key: key, label: e0e1LabelOf(key),
      dmg: state.total[key].dmg, hits: state.total[key].hits, crits: state.total[key].crits
    });
  }
  cats.sort(function (a, b) { return b.dmg - a.dmg; });

  var totalDmg = state.total.__total ? state.total.__total.dmg : 0;
  var bossDmg = state.total.__boss ? state.total.__boss.dmg : 0;

  // 类别曲线：从 buckets 的 all / boss 子表读
  var curves = [];
  cats.forEach(function (c) {
    var ps = [], bps = [];
    for (var i = 0; i < count; i++) {
      var slot = state.buckets[i];
      ps.push(slot && slot.all && slot.all[c.key] ? slot.all[c.key].dmg : 0);
      bps.push(slot && slot.boss && slot.boss[c.key] ? slot.boss[c.key].dmg : 0);
    }
    curves.push({
      key: c.key, label: c.label, dmg: c.dmg,
      perSecond: ps, bossPerSecond: bps, cumulative: e0e1Cumulative(ps)
    });
  });
  var totalPs = [], totalBps = [];
  for (var i2 = 0; i2 < count; i2++) {
    var s2 = state.buckets[i2];
    totalPs.push(s2 && s2.all && s2.all.__total ? s2.all.__total.dmg : 0);
    totalBps.push(s2 && s2.boss && s2.boss.__total ? s2.boss.__total.dmg : 0);
  }
  curves.push({
    key: "__total", label: "合计", dmg: totalDmg,
    perSecond: totalPs, bossPerSecond: totalBps, cumulative: e0e1Cumulative(totalPs)
  });

  var skills = [];
  for (var sid in state.skills) {
    var sk = state.skills[sid];
    var sps = e0e1Curve(state.skillCurves, sid, count);
    skills.push({
      skillId: Number(sid), name: sk.name, cat: sk.cat, catLabel: e0e1LabelOf(sk.cat),
      bookId: sk.book, bookName: sk.bookName, elem: sk.elem,
      branchId: sk.branch, branchName: sk.branchName, branchLevel: sk.branchLevel,
      kind: sk.kind, origin: sk.origin,
      dmg: sk.dmg, hits: sk.hits, crits: sk.crits,
      perSecond: sps, bossPerSecond: e0e1Curve(state.skillBossCurves, sid, count),
      cumulative: e0e1Cumulative(sps)
    });
  }
  skills.sort(function (a, b) { return b.dmg - a.dmg; });

  var books = [];
  for (var bid in state.books) {
    var bk2 = state.books[bid];
    var bps2 = e0e1Curve(state.bookCurves, bid, count);
    books.push({
      bookId: Number(bid), name: bk2.name, dmg: bk2.dmg, hits: bk2.hits,
      perSecond: bps2, bossPerSecond: e0e1Curve(state.bookBossCurves, bid, count),
      cumulative: e0e1Cumulative(bps2)
    });
  }
  books.sort(function (a, b) { return b.dmg - a.dmg; });

  var branches = [];
  for (var rid in state.branches) {
    var br = state.branches[rid];
    var rps = e0e1Curve(state.branchCurves, rid, count);
    branches.push({
      branchId: Number(rid), name: br.name, bookId: br.book, bookName: br.bookName,
      level: br.level, path: br.path, pathName: br.pathName,
      dmg: br.dmg, hits: br.hits,
      perSecond: rps, bossPerSecond: e0e1Curve(state.branchBossCurves, rid, count),
      cumulative: e0e1Cumulative(rps)
    });
  }
  branches.sort(function (a, b) { return b.dmg - a.dmg; });

  for (var bi = 0; bi < books.length; bi++) {
    var bk3 = books[bi];
    bk3.branches = branches.filter(function (b2) { return b2.bookId === bk3.bookId; });
    var own = skills.filter(function (s3) { return s3.bookId === bk3.bookId; });
    bk3.skillsByBranch = own.filter(function (s4) { return s4.branchId; });
    bk3.skillsNoBranch = own.filter(function (s5) { return !s5.branchId; });
  }

  var active = [];
  for (var ai = 0; ai < state.activeBranches.length; ai++) {
    var ab = state.activeBranches[ai];
    var matched = null;
    for (var mj = 0; mj < branches.length; mj++) {
      if (branches[mj].branchId === ab.branchId) { matched = branches[mj]; break; }
    }
    active.push({
      bookId: ab.bookId, bookName: ab.bookName,
      branchId: ab.branchId, branchName: ab.branchName,
      level: ab.level, path: ab.path, pathName: ab.pathName,
      skillIds: ab.skillIds,
      dmg: matched ? matched.dmg : 0,
      hits: matched ? matched.hits : 0,
      perSecond: matched ? matched.perSecond : [],
      cumulative: matched ? matched.cumulative : [],
      dealtDamage: !!matched
    });
  }
  active.sort(function (a, b) { return b.dmg - a.dmg; });

  // 每秒伤害来源 Top N：让报告 hover 时能列出「这一秒的伤害都是谁打的」
  // PVP 分数只算对敌方英雄的伤害，所以两种口径都要，报告按场景选。
  var perSecondTop = [];
  var perSecondBossTop = [];
  for (var bs = 0; bs < count; bs++) {
    perSecondTop.push(e0e1TopAt(state.skillCurves, state, bs));
    perSecondBossTop.push(e0e1TopAt(state.skillBossCurves, state, bs));
  }

  return {
    side: state.side,
    players: state.players,
    perSecondTop: perSecondTop,
    perSecondBossTop: perSecondBossTop,
    instanceId: state.instanceId,
    battleType: state.battleType,
    battleTypeName: E0E1_BATTLE_TYPE_NAMES[state.battleType] || null,
    seed: state.seed,
    bucketSeconds: state.bucket,
    duration: state.lastTime,
    buckets: count,
    eventCount: state.eventCount,
    truncated: state.truncated,
    totalDamage: totalDmg,
    bossDamage: bossDmg,
    categories: cats,
    curves: curves,
    skills: skills,
    books: books,
    branches: branches,
    activeBranches: active,
    events: state.events
  };
}

// 给双方各补一条「最终PVP增伤」= 本方PVP增伤 − 对方PVP减伤
function e0e1WithFinalPvp(rows) {
  var out = [];
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i] || {};
    var self = row.self || {}, other = row.other || {};
    var item = { sec: row.sec, self: {}, other: {} };
    for (var a in self) item.self[a] = self[a];
    for (var b in other) item.other[b] = other[b];
    if (self[117] !== undefined && other[118] !== undefined) {
      item.self[E0E1_FINAL_PVP_KEY] = self[117] - other[118];
    }
    if (other[117] !== undefined && self[118] !== undefined) {
      item.other[E0E1_FINAL_PVP_KEY] = other[117] - self[118];
    }
    out.push(item);
  }
  return out;
}

function e0e1Collect() {
  var self = e0e1CollectSide(E0E1_SIDES.self);
  var other = e0e1CollectSide(E0E1_SIDES.other);
  var pvp = null;
  if (E0E1_PVP.samples.length) {
    var cfg = E0E1_PVP.cfg || {};
    var derived = e0e1DerivedScores(E0E1_PVP.samples, cfg);
    var last = E0E1_PVP.samples[E0E1_PVP.samples.length - 1];
    var lastD = derived[derived.length - 1];
    var winLine = 2 * (cfg.PVPInitScore || 0);
    pvp = {
      battleType: E0E1_PVP.battleType,
      battleTypeName: E0E1_BATTLE_TYPE_NAMES[E0E1_PVP.battleType] || null,
      skipSafe: !!E0E1_SKIP_SAFE_TYPES[E0E1_PVP.battleType],
      cfg: {
        PVPInitScore: cfg.PVPInitScore,
        PVPInitVariable: cfg.PVPInitVariable,
        PVPBaseBonus: cfg.PVPBaseBonus,
        PVPLimitTime: cfg.PVPLimitTime,
        PVPWinRate: cfg.PVPWinRate
      },
      winLine: winLine,
      skipped: !!E0E1_PVP.skipped,
      samples: E0E1_PVP.samples,
      attrMeta: e0e1AttrMeta(),
      attrSeconds: e0e1WithFinalPvp(E0E1_PVP.attrSeconds),
      derived: derived,
      finalSelfScore: last ? last.selfScore : 0,
      finalOtherScore: last ? last.otherScore : 0,
      derivedSelfScore: lastD ? lastD.selfScore : 0,
      derivedOtherScore: lastD ? lastD.otherScore : 0
    };
  }
  return {
    mode: (E0E1_SIDES.self && E0E1_SIDES.other) ? "pvp" : "single",
    pvp: pvp,
    self: self,
    other: other
  };
}

function damageCurveJson() {
  return e0e1Collect();
}

function damageCurveText(width) {
  var data = e0e1Collect();
  if (!data.self && !data.other) return "尚未挂上战斗 World（还没进战斗？）";
  width = width || 60;
  var lines = [];

  if (data.pvp) lines = lines.concat(e0e1PvpText(data.pvp, width));
  for (var s = 0; s < 2; s++) {
    var sideKey = s === 0 ? "self" : "other";
    var side = data[sideKey];
    if (!side) continue;
    lines = lines.concat(e0e1SideText(side, sideKey === "self" ? "我方" : "敌方", width));
  }
  var text = lines.join("\n");
  console.log(text);
  return text;
}

function e0e1PvpText(pvp, width) {
  var lines = [];
  lines.push("==== PVP 分数 · battleType=" + pvp.battleType + " ====");
  lines.push("我方分数:" + e0e1Num(pvp.finalSelfScore) + "   敌方分数:" + e0e1Num(pvp.finalOtherScore) +
    "   胜利线:" + e0e1Num(pvp.winLine));
  lines.push("PVPcfg  PVPInitScore=" + pvp.cfg.PVPInitScore + "  PVPInitVariable=" + pvp.cfg.PVPInitVariable +
    "  PVPBaseBonus=" + pvp.cfg.PVPBaseBonus + "  PVPLimitTime=" + pvp.cfg.PVPLimitTime);
  lines.push("复算校验  我方:" + e0e1Num(pvp.derivedSelfScore) + "  敌方:" + e0e1Num(pvp.derivedOtherScore) +
    "（按客户端公式从双方伤害复算，应与上面接近）");
  lines.push("");
  var d = pvp.derived;
  var selfScore = d.map(function (x) { return x.selfScore; });
  var otherScore = d.map(function (x) { return x.otherScore; });
  var share = d.map(function (x) { return x.share === null ? 0.5 : x.share; });
  var weight = d.map(function (x) { return x.weight; });
  lines.push("[分数曲线] 我方 " + e0e1Spark(selfScore, width));
  lines.push("          敌方 " + e0e1Spark(otherScore, width));
  lines.push("[伤害天平] 我方占比 " + e0e1Spark(share, width) +
    "  （末值 " + (d.length ? ((d[d.length - 1].share === null ? 0.5 : d[d.length - 1].share) * 100).toFixed(1) : "-") + "%）");
  lines.push("[时间权重] PVPInitVariable^t " + e0e1Spark(weight, width) +
    "  （末值 " + e0e1Num(d.length ? d[d.length - 1].weight : 0) + "，越往后每秒满额越高）");
  lines.push("");
  return lines;
}

function e0e1SideText(side, title, width) {
  var lines = [];
  lines.push("---- " + title + "（World#" + side.instanceId + " · 类型" + side.battleType +
    " · seed" + side.seed + "）----");
  if (!side.eventCount) {
    lines.push("  没有采集到伤害事件");
    lines.push("");
    return lines;
  }
  lines.push("时长:" + side.duration.toFixed(1) + "s  事件:" + side.eventCount +
    "  总伤害:" + e0e1Num(side.totalDamage) + "  对BOSS:" + e0e1Num(side.bossDamage));
  lines.push("  " + e0e1Pad("类别", 8) + e0e1Pad("伤害", 14, true) + e0e1Pad("占比", 8, true) + "曲线");
  for (var i = 0; i < side.curves.length; i++) {
    var cv = side.curves[i];
    if (!cv.dmg) continue;
    var pct = side.totalDamage ? (cv.dmg / side.totalDamage * 100).toFixed(1) + "%" : "-";
    lines.push("  " + e0e1Pad(cv.label, 8) + e0e1Pad(e0e1Num(cv.dmg), 14, true) +
      e0e1Pad(pct, 8, true) + e0e1Spark(cv.perSecond, Math.max(16, width - 30)));
  }
  if (side.books.length) {
    lines.push("  天书逐本:");
    for (var b = 0; b < side.books.length; b++) {
      var bk = side.books[b];
      lines.push("    " + e0e1Pad(bk.name || ("天书" + bk.bookId), 14) +
        e0e1Pad(e0e1Num(bk.dmg), 12, true) +
        e0e1Spark(bk.perSecond, Math.max(12, width - 26)));
      for (var q = 0; q < bk.branches.length; q++) {
        var bn = bk.branches[q];
        lines.push("      └ " + e0e1Pad(bn.name + " Lv" + bn.level + "(" + bn.pathName + ")", 22) +
          e0e1Pad(e0e1Num(bn.dmg), 12, true) +
          e0e1Spark(bn.perSecond, Math.max(10, width - 34)));
      }
    }
  }
  if (side.skills.length) {
    lines.push("  技能 Top（含来源）:");
    for (var t = 0; t < Math.min(8, side.skills.length); t++) {
      var sk = side.skills[t];
      lines.push("    " + e0e1Pad(sk.name, 16) + e0e1Pad(sk.origin || "-", 10) +
        e0e1Pad(e0e1Num(sk.dmg), 12, true));
    }
  }
  var zero = side.activeBranches.filter(function (a) { return !a.dealtDamage; });
  if (zero.length) {
    lines.push("  已激活但零伤害的分支（只贡献属性加成/被更高阶覆盖）:");
    for (var z = 0; z < zero.length; z++) {
      lines.push("    " + zero[z].bookName + " · " + zero[z].branchName + " Lv" + zero[z].level +
        " " + zero[z].pathName);
    }
  }
  lines.push("");
  return lines;
}

function damageCurveCsv() {
  var data = e0e1Collect();
  var rows = ["side,t_sec,skill_id,skill_name,category,kind,origin,book_id,book_name,branch_id,branch_name,branch_level,element,damage,is_crit,is_boss,is_elite"];
  var sides = [["self", data.self], ["other", data.other]];
  for (var s = 0; s < sides.length; s++) {
    var side = sides[s][1];
    if (!side) continue;
    for (var i = 0; i < side.events.length; i++) {
      var e = side.events[i];
      rows.push([
        sides[s][0],
        e.t.toFixed(3),
        e.skill,
        '"' + String(e.skillName).replace(/"/g, '""') + '"',
        e.cat,
        e.kind || "",
        e.origin || "",
        e.book === null || e.book === undefined ? "" : e.book,
        e.bookName ? '"' + String(e.bookName).replace(/"/g, '""') + '"' : "",
        e.branch === null || e.branch === undefined ? "" : e.branch,
        e.branchName ? '"' + String(e.branchName).replace(/"/g, '""') + '"' : "",
        e.branchLevel === null || e.branchLevel === undefined ? "" : e.branchLevel,
        e.elem,
        e.dmg,
        e.crit ? 1 : 0,
        e.boss ? 1 : 0,
        e.elite ? 1 : 0
      ].join(","));
    }
  }
  var csv = rows.join("\n");
  console.log("[e0e1][伤害曲线] CSV " + (rows.length - 1) + " 行");
  return csv;
}

function damageCurveStatus() {
  var sides = {};
  ["self", "other"].forEach(function (key) {
    var st = E0E1_SIDES[key];
    sides[key] = st ? {
      instanceId: st.instanceId,
      battleType: st.battleType,
      eventCount: st.eventCount,
      duration: st.lastTime,
      totalDamage: st.total.__total ? st.total.__total.dmg : 0,
      activeBranches: st.activeBranches.length
    } : null;
  });
  return {
    hooked: E0E1_HOOKS.length,
    running: !!E0E1_TIMER,
    mode: (E0E1_SIDES.self && E0E1_SIDES.other) ? "pvp" : "single",
    sides: sides,
    pvpSamples: E0E1_PVP.samples.length,
    pvpCfg: E0E1_PVP.cfg,
    hasCfg: !!E0E1_CFG,
    hasBattleManager: !!E0E1_BM,
    evoIndexSize: E0E1_EVO ? Object.keys(E0E1_EVO).length : 0
  };
}

// 技能来源反查结果：按「类别 → 来源」汇总，用来确认某一档伤害到底出自哪个系统。
// 例如 15/16 那一档枚举名叫 EQUIPMENT_*，到底是脸谱套装还是法器宝石，看这个就知道。
function damageCurveOrigins() {
  var data = e0e1Collect();
  var lines = [];
  ["self", "other"].forEach(function (sideKey) {
    var side = data[sideKey];
    if (!side) return;
    lines.push("---- " + (sideKey === "self" ? "我方" : "敌方") + " 技能来源 ----");
    if (!side.skills.length) {
      lines.push("  没有技能事件");
      return;
    }
    var byCat = {};
    side.skills.forEach(function (s) {
      var bucket = byCat[s.catLabel] || (byCat[s.catLabel] = {});
      var key = s.origin || "未归类";
      var slot = bucket[key] || (bucket[key] = { dmg: 0, hits: 0, names: [] });
      slot.dmg += s.dmg;
      slot.hits += s.hits;
      if (slot.names.length < 3) slot.names.push(s.name + "(" + s.skillId + ")");
    });
    Object.keys(byCat).forEach(function (cat) {
      lines.push("  " + cat);
      Object.keys(byCat[cat]).forEach(function (origin) {
        var v = byCat[cat][origin];
        lines.push("    " + e0e1Pad(origin, 12) + e0e1Pad(e0e1Num(v.dmg), 12, true) +
          "  " + v.names.join("、"));
      });
    });
  });
  var text = lines.join("\n");
  console.log(text);
  return text;
}

// 采不到数据时先用这个定位：脚本在不在、World 挂没挂、分数采到几个
function damageCurveDebug() {
  var report = {
    scriptLoaded: true,
    timerRunning: !!E0E1_TIMER,
    cfgLoaded: !!E0E1_CFG,
    battleManagerLoaded: !!E0E1_BM,
    battleManagerPatched: E0E1_BM_PATCHED,
    watchedWorlds: E0E1_WATCHED.length,
    hookedWorlds: E0E1_HOOKS.length,
    hooks: E0E1_HOOKS.map(function (h) {
      return {
        instanceId: h.world && h.world.instanceId,
        side: h.side,
        quitted: !!(h.world && h.world.isQuitted),
        events: h.state.eventCount,
        battleType: h.state.battleType
      };
    }),
    sides: {
      self: E0E1_SIDES.self ? E0E1_SIDES.self.eventCount : null,
      other: E0E1_SIDES.other ? E0E1_SIDES.other.eventCount : null
    },
    pvpSamples: E0E1_PVP.samples.length,
    pvpSampleSeconds: E0E1_PVP.samples.length
      ? [E0E1_PVP.samples[0].sec, E0E1_PVP.samples[E0E1_PVP.samples.length - 1].sec]
      : null,
    pvpInstanceKey: E0E1_PVP.instanceKey,
    pvpSkipped: E0E1_PVP.skipped,
    pvpCfg: E0E1_PVP.cfg,
    attrSeconds: E0E1_PVP.attrSeconds.length,
    attrRawSample: E0E1_PVP.attrSeconds.length
      ? E0E1_PVP.attrSeconds[E0E1_PVP.attrSeconds.length - 1]
      : null,
    evoIndexSize: E0E1_EVO ? Object.keys(E0E1_EVO).length : 0,
    lastError: E0E1_LAST_ERROR
  };
  // 顺带看一眼当前还能不能拿到 World（用来判断是否被 detach 了）
  try {
    var battles = e0e1FindWorlds();
    report.worldsInGetBattles = battles.length;
  } catch (error) {
    report.worldsInGetBattles = "error: " + error;
  }
  console.log(report);
  return report;
}

function damageCurveReset() {
  e0e1DetachAll();
  e0e1AttachAll();
  return "已清空" + (E0E1_HOOKS.length ? "，重新挂上 " + E0E1_HOOKS.length + " 个 World" : "（当前无战斗 World）");
}

function damageCurveStop() {
  if (E0E1_TIMER) {
    var game = e0e1ResolveGameWindow();
    if (game && game.clearInterval) game.clearInterval(E0E1_TIMER);
    else clearInterval(E0E1_TIMER);
    E0E1_TIMER = null;
  }
  e0e1DetachAll();
  return "已停止采集";
}

// ── 轮询挂接 ──

function e0e1Tick() {
  try {
    e0e1AttachAll();
    e0e1SamplePvp();
  } catch (error) {
    E0E1_LAST_ERROR = String(error && (error.stack || error.message) || error);
    console.log("[e0e1][伤害曲线] tick error: " + error);
  }
}

async function e0e1Install() {
  var api = {
    damageCurveText: damageCurveText,
    damageCurveJson: damageCurveJson,
    damageCurveCsv: damageCurveCsv,
    damageCurveStatus: damageCurveStatus,
    damageCurveDebug: damageCurveDebug,
    damageCurveOrigins: damageCurveOrigins,
    damageCurveReset: damageCurveReset,
    damageCurveStop: damageCurveStop
  };
  for (var name in api) e0e1Expose(name, api[name]);

  var game = e0e1ResolveGameWindow();
  for (var attempt = 0; attempt < 40 && !game; attempt++) {
    await new Promise(function (resolve) { setTimeout(resolve, 250); });
    game = e0e1ResolveGameWindow();
  }
  if (!game) return { ok: false, message: "未找到 gameContext，请确认游戏已加载" };
  for (var name2 in api) e0e1Expose(name2, api[name2]);

  await e0e1LoadCfg();
  await e0e1LoadBattleManager();
  E0E1_EVO = e0e1BuildEvoIndex();

  var timer = game.setInterval || globalThis.setInterval;
  E0E1_TIMER = timer.call(game, e0e1Tick, 200);
  e0e1Tick();

  return {
    ok: true,
    message: "伤害曲线采集已启动（PVP 会同时采我方与敌方两个 World）。进入好友切磋／斗法／血月对战自动开始，" +
      "打完运行 damageCurveText() 看分数与伤害拆解。",
    log: ""
  };
}

function e0e1Uninstall() {
  damageCurveStop();
  return { ok: true, message: "已停止伤害曲线采集" };
}

if (typeof globalThis.__e0e1RegisterRuntimeToggle === "function") {
  var e0e1CurveEnabled = false;
  globalThis.__e0e1RegisterRuntimeToggle({
    async enable() {
      var result = await e0e1Install();
      e0e1CurveEnabled = !!result.ok;
      return { ok: true, enabled: e0e1CurveEnabled, message: result.message, log: "" };
    },
    async disable() {
      var result = e0e1Uninstall();
      e0e1CurveEnabled = false;
      return { ok: true, enabled: false, message: result.message, log: "" };
    },
    status() {
      var st = damageCurveStatus();
      var detail = st.hooked
        ? (st.mode === "pvp" ? "PVP 双方已挂接" : "已挂接") + " · 事件 " +
          ((st.sides.self ? st.sides.self.eventCount : 0) + (st.sides.other ? st.sides.other.eventCount : 0)) +
          (st.pvpSamples ? " · 分数采样 " + st.pvpSamples : "")
        : "等待进入战斗";
      return {
        ok: true,
        enabled: e0e1CurveEnabled,
        message: e0e1CurveEnabled ? ("采集中 · " + detail) : "未启用",
        log: ""
      };
    }
  });
} else {
  var e0e1CurveResult = await e0e1Install();
  console.log("[e0e1][伤害曲线] " + e0e1CurveResult.message);
  if (typeof globalThis.__e0e1JsInjectionReport === "function") {
    globalThis.__e0e1JsInjectionReport(e0e1CurveResult.message);
  }
}
