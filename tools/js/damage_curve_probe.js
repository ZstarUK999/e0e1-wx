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
  { key: "leifa", label: "雷法尊者", types: [] },
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
var E0E1_PATCHES = [];
var E0E1_BM_PATCHED = false; // BattleManager.createBattle 是否已挂钩
var E0E1_LAST_ERROR = null;  // 最近一次异常，damageCurveDebug() 会报
var E0E1_PVP = { cfg: null, samples: [], attrSeconds: [], lastSecond: -1, battleType: null, skipped: false,
                 instanceKey: null };
var E0E1_TIMER = null;
var E0E1_CFG = null;
var E0E1_DEFINE = null;
var E0E1_CHARACTER = null;
var E0E1_BATTLE_CONST = null;
var E0E1_TYPE_COMPONENTS = null;
var E0E1_LIFE = null;
var E0E1_FORMULA_MODULES = null;
var E0E1_DAMAGE_STACK = [];
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
  E0E1_DUAL = await e0e1Import("chunks:///_virtual/arena-dual-score-pvp-battle-manager.ts");
  E0E1_LOCAL_DUAL = await e0e1Import("chunks:///_virtual/dual-score-pvp-battle-manager.ts");
  E0E1_DEFINE = await e0e1Import("chunks:///_virtual/define-index.ts");
  E0E1_CHARACTER = await e0e1Import("chunks:///_virtual/character-helper.ts");
  E0E1_BATTLE_CONST = await e0e1Import("chunks:///_virtual/battle-const.ts");
  E0E1_TYPE_COMPONENTS = await e0e1Import("chunks:///_virtual/type-components.ts");
  E0E1_LIFE = await e0e1Import("chunks:///_virtual/comp-life.ts");
  var formulaModules=await Promise.all(['damage-context.ts','skill-context.ts','DecimalNumber.ts','comp-hero.ts'].map(function(name){return e0e1Import('chunks:///_virtual/'+name);}));
  E0E1_FORMULA_MODULES={damage:formulaModules[0],skill:formulaModules[1],decimal:formulaModules[2],hero:formulaModules[3]};
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
  var candidates = [row.name, row.Name, row.cfgName, row.title, row.itemId && row.itemId.name];
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
    var previous = index[String(row.skillId)];
    index[String(row.skillId)] = {
      branchId: branch ? branch.id : (row.evolutionId || null),
      branchName: branch ? (branch.name || branch.nodeName || null) : null,
      branchLevel: previous && previous.branchId === (branch ? branch.id : row.evolutionId) ? null : (row.skillLevel !== undefined ? row.skillLevel : null),
      path: branch ? branch.evolutionPath : null,
      bookId: branch ? branch.skillBookBelong : null
    };
  }
  // 召唤入口的分支归属沿sumSkill常量传播到真正造成伤害的技能；不执行配置表达式。
  var skills = E0E1_CFG && E0E1_CFG.SkillCfg;
  for (var pass=0;pass<4;pass++) {
    var changed=false;
    (skills && skills.list || []).forEach(function(parent){
      var meta=index[String(parent.id)];
      if(!meta) return;
      (parent._properties || []).forEach(function(prop){
        if(prop.name!=='sumSkill' || !/^\d+$/.test(String(prop.expression || ''))) return;
        var child=Number(prop.expression);
        if(child>0 && !index[String(child)] && skills.getById(child)) {
          index[String(child)]=Object.assign({},meta);changed=true;
        }
      });
    });
    if(!changed)break;
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
var E0E1_FASHION_SKILLS = {};
var E0E1_DUAL = null;
var E0E1_LOCAL_DUAL = null;
var E0E1_REPLAY_CONTEXTS = [];
var E0E1_REPLAY_SERIAL = 0;
var E0E1_ORIGIN_SOURCES = [
  { table: "MagicArtifactBaseCfg", fields: ["skill"], label: "法器" },
  { table: "MagicArtifactStoneCfg", fields: ["skill"], label: "法器宝石" },
  { table: "MagicArtifactTemperSkillCfg", fields: ["skill"], label: "法器淬炼" },
  { table: "EquipmentSuitSkillCfg", fields: ["skillId"], label: "脸谱套装" },
  { table: "FashionCfg", fields: ["skill", "attackSkill"], label: "傀儡装" },
  { table: "BaseSkinCfg", fields: ["skill"], label: "基地法相" },
  { table: "DesireCfg", fields: ["skill"], label: "三尸" },
  { table: "SeasonWarRestraintCfg", fields: ["pveSkill", "pvpSkill"], label: "战旗" }
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
        (function visit(value) {
          if (Array.isArray(value)) { value.forEach(visit); return; }
          if (typeof value !== 'number' || !isFinite(value) || value <= 0) return;
          var name=row.name || (row.itemId && row.itemId.name) || (row.c_item_itemId && e0e1CfgName('ItemCfg',row.c_item_itemId));
          var label=source.label+(name ? ' · '+name : '');
          var previous=index[String(value)];
          index[String(value)]=previous ? (previous.split(' / ').indexOf(label)<0 ? previous+' / '+label : previous) : label;
          if (source.table === 'FashionCfg') E0E1_FASHION_SKILLS[String(value)] = {id:row.id,name:row.name};
        })(raw);
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
function e0e1SamplePvp(forceFinal) {
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
  [E0E1_SIDES.self,E0E1_SIDES.other].forEach(function(state){if(state)e0e1SampleFormulaState(state);});
  if (sec === E0E1_PVP.lastSecond) {
    // 时钟信号早于本帧伤害结算；同步跳过返回后补齐最后一帧，不制造重复秒。
    if(forceFinal && E0E1_PVP.samples.length){
      var finalSample=E0E1_PVP.samples[E0E1_PVP.samples.length-1];
      var finalSelf=e0e1ScoreOf(world),finalOther=E0E1_SIDES.other && E0E1_SIDES.other.world;
      finalSample.t=t;
      if(finalSelf!==null)finalSample.selfScore=finalSelf;
      var otherFinal=finalOther ? e0e1ScoreOf(finalOther) : null;
      if(otherFinal!==null)finalSample.otherScore=otherFinal;
      finalSample.selfBoss=e0e1BossDamageOf(world);
      if(finalOther)finalSample.otherBoss=e0e1BossDamageOf(finalOther);
    }
    return;
  }

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
    other: other && other.world ? e0e1ReadHeroAttrs(other.world) : {},
    selfSources: e0e1ReadAttrSources(world),
    otherSources: other && other.world ? e0e1ReadAttrSources(other.world) : {},
    selfContext: e0e1ReadAttrContext(world),
    otherContext: other && other.world ? e0e1ReadAttrContext(other.world) : {}
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
// p = 是否百分比。compAttributes.get 已将原始万分数转换为比率；报告乘 100 显示百分数。
//   （2.3 → 230%），数值类（攻击/生命）不换算。
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
// 与 damage-context.ts / formula.ts 对齐；百分比值为 compAttributes.get 的比率。
var E0E1_EXTRA_ATTRS = [
 [13,'移速加成'],[410,'招架次数',false],[1006,'伤害免疫',false],[2,'基础攻击',false],[3,'攻击加成'],[19,'PVP固定攻击',false],[20,'PVP攻击加成'],
 [103,'暴击抵抗'],[108,'对精英增伤'],[109,'对首领增伤'],[110,'对空增伤'],[111,'对地增伤'],
 [112,'灼烧增伤'],[113,'挑战增伤（目标生命>80%）'],[114,'审判增伤（目标生命<20%）'],
 [119,'天书减伤'],[120,'符咒减伤'],[125,'主线增伤'],[126,'主线减伤'],[127,'首领/精英通用增伤'],
 [128,'首领/精英通用减伤'],[129,'PVP最终增伤'],[130,'法术爆伤抵抗'],[132,'法术暴击抵抗'],[134,'法器减伤'],
 [233,'紫天书增伤'],[234,'紫天书减伤'],[235,'橙天书增伤'],[236,'橙天书减伤'],[237,'红天书增伤'],[238,'红天书减伤'],
 [601,'鬼仆暴击率'],[602,'鬼仆爆伤'],[705,'灼烧符咒系数加成'],[706,'爆发符咒系数加成'],
 [1002,'护盾转增伤比例'],[1003,'被控减伤'],[1004,'齐射弹射转伤'],
 [200101,'赛季攻击',false],[200103,'赛季最终增伤'],[200104,'赛季最终减伤'],
 [200105,'致命一击率'],[200106,'致命一击率抵抗'],[200107,'致命一击伤害'],[200108,'致命一击伤害抵抗'],
 [200109,'群攻致命一击率'],[200110,'群攻致命一击率抵抗'],[200111,'群攻致命一击伤害'],[200112,'群攻致命一击伤害抵抗']
];
['火','水','风','土'].forEach(function(name,i){
 [[201,'伤害'],[205,'减伤'],[209,'天书伤害'],[213,'天书减伤'],[217,'法术爆伤'],[221,'法术爆伤抵抗'],[225,'符咒伤害'],[229,'符咒减伤']].forEach(function(row){
   E0E1_EXTRA_ATTRS.push([row[0]+i,name+'系'+row[1]]);
 });
});
E0E1_EXTRA_ATTRS.forEach(function(row){
 if(!E0E1_ATTR_KEYS.some(function(a){return a.key===row[0];})) E0E1_ATTR_KEYS.push({key:row[0],label:row[1],p:row[2]!==false});
});

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

function e0e1AttrNumber(value) {
  if(value===undefined || value===null) return null;
  var n=typeof value.toNumber==='function' ? value.toNumber() : Number(value);
  return isFinite(n) ? n : null;
}

// 配置反向引用仅解释可能的授予链；不执行表达式，不把关联上下文认作授予者。
var E0E1_BUFF_GRAPH=null,E0E1_BUFF_ORIGINS={};
function e0e1BuildBuffGraph(){
  var parents={};
  function edge(from,table,id){
    if(!Number.isInteger(Number(id)) || Number(id)<=0 || !e0e1CfgRow(table,id))return;
    var key=table+':'+id,list=parents[key] || (parents[key]=[]);if(list.indexOf(from)<0)list.push(from);
  }
  var links={SkillCfg:{_passive:'PassiveSkillCfg',_active:'ActiveSkillCfg'},ActiveSkillCfg:{_emitters:'EmitterCfg'},EmitterCfg:{bulletIds:'BulletCfg'}};
  ['SkillCfg','PassiveSkillCfg','ActiveSkillCfg','EmitterCfg','BulletCfg','BuffCfg'].forEach(function(table){
    var cfg=E0E1_CFG && E0E1_CFG[table];
    (cfg && cfg.list || []).forEach(function(row){
      var from=table+':'+row.id;
      Object.keys(links[table] || {}).forEach(function(field){(row[field] || []).forEach(function(id){edge(from,links[table][field],id);});});
      Object.keys(row).filter(function(key){return /^_.*[Ee]ffects$/.test(key);}).forEach(function(field){
        (Array.isArray(row[field]) ? row[field] : []).forEach(function(expression){
          var pattern=/\b(SELF_BUFF_FORCE|SELF_BUFF|OWNER_BUFF|PLAYER_BUFF|BUFF|ACTIVE|ADD_SKILL)\(\s*(\d+)\s*(?=[,)])/g,match;
          while((match=pattern.exec(String(expression))))edge(from,match[1]==='ACTIVE' ? 'ActiveSkillCfg' : match[1]==='ADD_SKILL' ? 'SkillCfg' : 'BuffCfg',Number(match[2]));
          var probabilistic=/\b(?:PROB_BUFF|PROB_OWNER_BUFF|ATTR_PROB_BUFF)\(\s*[^,()]+,\s*(\d+)\s*(?=[,)])/g;
          while((match=probabilistic.exec(String(expression))))edge(from,'BuffCfg',Number(match[1]));
          var condition=/\bBUFF_CONDITION\(\s*[^,()]+,\s*(\d+)\s*,\s*(\d+)\s*\)/g;
          while((match=condition.exec(String(expression)))){edge(from,'BuffCfg',Number(match[1]));edge(from,'BuffCfg',Number(match[2]));}

        });
      });
    });
  });
  return parents;
}
function e0e1BuffOrigins(id){
  if(!E0E1_BUFF_GRAPH)E0E1_BUFF_GRAPH=e0e1BuildBuffGraph();
  if(E0E1_BUFF_ORIGINS[id])return E0E1_BUFF_ORIGINS[id];
  var queue=['BuffCfg:'+id],seen={},sources=[];
  for(var index=0;index<queue.length;index++){
    var node=queue[index];if(seen[node])continue;seen[node]=true;
    if(node.indexOf('SkillCfg:')===0){
      var skillId=Number(node.split(':')[1]),name=e0e1CfgName('SkillCfg',skillId);
      if(name){var origin=e0e1OriginOf(skillId);sources.push({skillId:skillId,name:name,origin:origin});}
    }
    (E0E1_BUFF_GRAPH[node] || []).forEach(function(parent){if(!seen[parent])queue.push(parent);});
  }
  return E0E1_BUFF_ORIGINS[id]=sources;
}
function e0e1BuffLabel(buff){
  var id=buff.cfg && buff.cfg.id,roots=e0e1BuffOrigins(id);
  var names=roots.map(function(root){return (root.origin ? root.origin+' / ' : '')+root.name;});
  var label='Buff：'+((buff.cfg && buff.cfg.name)||id)+'（'+buff.piles+'层）';
  if(names.length)label+='；配置'+(names.length===1 ? '来源：' : '候选来源：')+names.slice(0,6).join('、')+(names.length>6 ? '等'+names.length+'项（共享Buff）' : '');
  else label+='；授予来源未解析';
  var skill=buff.skillContext && buff.skillContext.shareData && buff.skillContext.shareData.skillCfg;
  if(skill)label+='；关联技能：'+(skill.name || skill.id);
  return label;
}

// 只读当前实际生效的 changeAttributes，不重新执行技能表达式，不改游戏属性。
function e0e1ReadAttrSources(world, entity) {
  var out={};
  try {
    var hero=entity || (world.getFightHero && world.getFightHero()), comp=hero && hero.compAttributes;
    var values=comp && comp.attributes && comp.attributes.attributes;
    if(!values || !values.get) return out;
    var known={};
    function addChanges(changes,label) {
      if(!changes) return;
      function add(value,key) {
        var n=e0e1AttrNumber(value); if(n===null || n===0) return;
        (known[key] || (known[key]=[])).push({label:label,raw:n});
      }
      if(changes.forEach) changes.forEach(add);
      else Object.keys(changes).forEach(function(key){add(changes[key],key);});
    }
    var recipes=hero.compSkillAssistant && hero.compSkillAssistant.allSkills;
    if(recipes && recipes.forEach) recipes.forEach(function(recipe){
      var id=recipe.skillId || (recipe.cfg && recipe.cfg.id);
      addChanges(recipe.changeAttributes,'技能：'+(e0e1CfgName('SkillCfg',id)||id));
    });
    ((hero.compBuffAssistant && hero.compBuffAssistant.buffs) || []).forEach(function(buff){
      if(buff.isFinish) return;
      var id=buff.cfg && buff.cfg.id;
      var skill=buff.skillContext && buff.skillContext.shareData && buff.skillContext.shareData.skillCfg;
      var label=e0e1BuffLabel(buff);
      addChanges(buff.changeAttributes,label);
      (buff.endCond || []).forEach(function(cond){addChanges(cond.applied,label+' · 状态属性');});
    });
    E0E1_ATTR_KEYS.forEach(function(meta){
      var attr=values.get(meta.key);if(!attr) return;
      var base=e0e1AttrNumber(attr.baseValue),scale=e0e1AttrNumber(attr.addScaleValue),absolute=e0e1AttrNumber(attr.addAbsoluteValue);
      var total=e0e1AttrNumber(comp.get(meta.key)), divisor=meta.p ? 10000 : 1;
      if(base===null || scale===null || absolute===null || total===null) return;
      var rows=[];
      if(base) rows.push({label:'基础面板',value:base/divisor});
      if(base*scale) rows.push({label:'面板比例修正',value:base*scale/divisor});
      var attributed=0;
      (known[meta.key] || []).forEach(function(row){attributed+=row.raw;rows.push({label:row.label,value:row.raw/divisor});});
      if(absolute-attributed) rows.push({label:'其他即时变化（未归属）',value:(absolute-attributed)/divisor});
      var difference=total-(base*(1+scale)+absolute)/divisor;
      if(Math.abs(difference)>1e-8) rows.push({label:'属性上下限/模式修正',value:difference});
      out[meta.key]=rows;
    });
  } catch(error) {}
  return out;
}

function e0e1ReadAttrContext(world) {
  var out={};
  try {
    var hero=world.getFightHero && world.getFightHero();
    var mi=world.options && world.options.mineInfo, metrics=mi && mi.pvpMetrics;
    if(metrics) out.opponentPvpRed=Number((mi.isSelf ? metrics.otherPvpDmgRed : metrics.selfPvpDmgRed)||0)/10000;
    var hp=e0e1AttrNumber(hero && hero.compLife && hero.compLife.max);
    var shield=e0e1AttrNumber(hero && hero.compArmor && hero.compArmor.current);
    if(hp>0) out.shieldRatio=Math.max(0,shield || 0)/hp;
    var bd=world.options && world.options.battleData;
    if(bd && bd.type===20) {
      // EBattleTeamOpType.seasonEnergy 使用原生枚举，避免猜测 options 数字键。
      var team=bd.leftTeam, energyKey=E0E1_DEFINE && E0E1_DEFINE.EBattleTeamOpType && E0E1_DEFINE.EBattleTeamOpType.seasonEnergy;
      var energy=team && team.options && team.options.get && energyKey!==undefined ? team.options.get(energyKey) : null;
      if(energy!==undefined && energy!==null) {
        var cfg=e0e1CfgRow('SeasonStaminaCfg',energy) || e0e1CfgRow('SeasonStaminaCfg',100);
        if(cfg) out.stamina={energy:energy,skillDamage:cfg.skillDamage/10000,finalDamage:cfg.finalDamage/10000};
      }
    }
  } catch(error) {}
  return out;
}

// 队伍成员字段在不同版本里不一定齐全，全部防御式读取：有就拿，没有就跳过
function e0e1ReadFighterInfo(member) {
  if (!member) return null;
  var info = { books: [], awakenings: [], desires: [], pets: [], equipment: [], fashions: [] };
  if (member.fashion && typeof member.fashion.forEach === "function") member.fashion.forEach(function(id,slot){
    info.fashions.push({id:Number(id),slot:slot,name:e0e1CfgName("FashionCfg",id)||("傀儡装"+id),
      level:member.allFashion && member.allFashion.get ? member.allFashion.get(Number(id)) : null});
  });
  ["roleId", "id", "name", "sName", "level", "heroId", "fightPower", "maxFightPower"].forEach(function (field) {
    if (member[field] !== undefined && member[field] !== null) info[field] = member[field];
  });

  try {
    // Fighter.equipSkills 是技能ID→等级；GDRoleSnap.equipSkill 才是槽位→天书ID。
    var seenBooks={};
    if(member.equipSkills && member.equipSkills.forEach){
      member.equipSkills.forEach(function(level,skillId){
        var skill=e0e1CfgRow('SkillCfg',skillId),id=skill && (skill.bookId || skill.sourceBookId);
        if(!skill || [4,13,17].indexOf(skill.skillFunctionType)<0 || !id || seenBooks[id] || !e0e1CfgRow('SkillBookCfg',id))return;
        seenBooks[id]=true;info.books.push({bookId:Number(id),name:e0e1CfgName('SkillBookCfg',id),level:null});
      });
    }else if(member.equipSkill && member.equipSkill.forEach){
      member.equipSkill.forEach(function(bookId,slot){
        if(!e0e1CfgRow('SkillBookCfg',bookId))return;
        var levels=member.skillLevel,level=levels && levels.get ? levels.get(bookId) : null;
        info.books.push({slot:slot,bookId:Number(bookId),name:e0e1CfgName('SkillBookCfg',bookId),level:level===undefined ? null : level});
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
    function readTeam(team) {
      if(!team) return null;
      var members=team.team,member=null;
      if(Array.isArray(members)) member=members[0];
      else if(members && typeof members.values==='function') member=members.values().next().value;
      else if(members && typeof members==='object') member=members[Object.keys(members)[0]];
      var person=e0e1ReadFighterInfo(member);
      if(!person && (team.name || team.roleId)) person={books:[],awakenings:[],desires:[],pets:[],equipment:[],fashions:[]};
      if(person) {
        if(team.name) person.name=team.name;
        if(team.roleId) person.roleId=team.roleId;
        if(team.power!==undefined) person.fightPower=team.power;
      }
      return person;
    }
    out.self=readTeam(data.leftTeam);
    out.other=readTeam(data.rightTeam);
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
    replay: world && world.__e0e1DamageReplay || null,
    bucket: 1,
    factorSnapshots: [], lastFactorSampleSecond: -1, factorRows: [], factorIndex: {}, factorSources: [], factorSourceIndex: {}, factorsTruncated: false,
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

function e0e1Classify(skillId, state) {
  var row = e0e1CfgRow("SkillCfg", skillId);
  var sft = row && row.skillFunctionType !== undefined ? row.skillFunctionType : -1;
  var cat = E0E1_TYPE_TO_CAT[sft] || "other";
  var bookId = row && (row.bookId || row.sourceBookId) ? (row.bookId || row.sourceBookId) : null;
  if (cat === "book" && !bookId) {
    var guess = 100 * Math.floor(Number(skillId) / 100);
    if (e0e1CfgRow("SkillBookCfg", guess)) bookId = guess;
  }
  if (!E0E1_ORIGIN) E0E1_ORIGIN = e0e1BuildOriginIndex();
  var fashion = E0E1_FASHION_SKILLS[String(skillId)];
  if (fashion && fashion.name === "雷法尊者") { cat = "leifa"; bookId = null; }
  var evo = e0e1EvoOf(skillId);
  if (evo && evo.bookId) bookId = evo.bookId;
  var origin=e0e1OriginOf(skillId);
  if(origin && origin.split(' / ').some(function(label){return label.indexOf('战旗 · ')===0;})){cat='flag';bookId=null;}
  var actualLevel = evo ? evo.branchLevel : null;
  if (evo && state && state.activeBranches) state.activeBranches.forEach(function(active){
    if(active.branchId===evo.branchId) actualLevel=active.level;
  });
  return {
    sft: sft,
    cat: cat,
    skillName: e0e1CfgName("SkillCfg", skillId) || ("技能" + skillId),
    bookId: bookId,
    bookName: bookId ? (e0e1CfgName("SkillBookCfg", bookId) || ("天书" + bookId)) : null,
    element: cat === "card" ? (E0E1_ELEMENTS[row ? row.elementalType : 0] || "") : "",
    branchId: evo ? evo.branchId : null,
    branchName: evo ? (evo.branchName || ("分支" + evo.branchId)) : null,
    branchLevel: actualLevel,
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
    if (dmg < 0) return;
    var t = 0;
    try {
      t = state.world.battleTime.battleTime || 0;
    } catch (error) {}
    var info = e0e1Classify(skillId, state);
    try { e0e1RecordFactors(state,source,skillId,dmg,target,info,t); } catch(error) { E0E1_LAST_ERROR=String(error); }
    if(dmg===0) return;
    state.lastTime = Math.max(state.lastTime, t);
    state.eventCount += 1;
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

    if (info.cat === "book" && info.bookId) {
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

// 捕获真正扣血链路中的 DamageContext；只在 $skillDamageCollect 确认实际命中时记账。
// 不挂 calcDamage：它也会被伤害预估调用，不能把预估当成实际攻击。
function e0e1PatchFactorCapture() {
  var owner=E0E1_CHARACTER && E0E1_CHARACTER.characterHelper;
  if(!owner || typeof owner.subLife!=='function' || owner.subLife.__e0e1Factors) return;
  var original=owner.subLife;
  var wrapper=function(context) {
    var frame={context:context,snapshot:null};
    try {
      var state=E0E1_SIDES.self && E0E1_SIDES.self.world===context.battleWorld ? E0E1_SIDES.self :
        E0E1_SIDES.other && E0E1_SIDES.other.world===context.battleWorld ? E0E1_SIDES.other : null;
      if(state && context.target && context.target.compBoss && state.factorRows.length<12000) frame.snapshot=e0e1FactorInputs(context);
    } catch(error) { E0E1_LAST_ERROR=String(error); }
    E0E1_DAMAGE_STACK.push(frame);
    try {
      var result=original.apply(this,arguments);
      // 免伤可能在广播采集信号前返回0；补记该结算，不加入伤害事件/总伤害。
      if(frame.snapshot && !frame.recorded && e0e1AttrNumber(result)===0 && frame.snapshot.settlement.inputDamage>0){
        try {e0e1RecordFactors(state,context.source,context.skillId,0,context.target,e0e1Classify(context.skillId,state),state.world.battleTime.battleTime || 0);}
        catch(error){E0E1_LAST_ERROR=String(error);}
      }
      return result;
    } finally { E0E1_DAMAGE_STACK.pop(); }
  };
  wrapper.__e0e1Factors=true;owner.subLife=wrapper;
  E0E1_PATCHES.push({owner:owner,key:'subLife',original:original,wrapper:wrapper});
}

function e0e1AttrZone(key) {
  key=Number(key);
  if([410,1006].indexOf(key)>=0) return 'BOSS扣血结算机制（非增伤乘区）';
  if([1,2,3,19,20].indexOf(key)>=0) return '攻击区';
  if([104,105,125,126,1002,1003,1004].indexOf(key)>=0) return '普通增伤区';
  if(key>=201 && key<=216) return '元素增伤区';
  if([108,109,110,111,127,128].indexOf(key)>=0) return '类型增伤区 / 首领、精英、空地';
  if([113,114].indexOf(key)>=0) return '类型增伤区 / 高低血量';
  if([115,116,119,120,131,133,134].indexOf(key)>=0 || key>=225 && key<=238) return '类型增伤区 / 天书、符咒及技能';
  if([708,709].indexOf(key)>=0) return '类型增伤区 / 普攻';
  if([117,118].indexOf(key)>=0) return 'PVP增伤区（对局指标优先）';
  if([123,124,129].indexOf(key)>=0) return '最终增伤区';
  if([101,102,103,106,107,130,132,601,602].indexOf(key)>=0 || key>=217 && key<=224) return '暴击区（触发时）';
  if([705,706].indexOf(key)>=0) return '技能系数区';
  if([200103,200104].indexOf(key)>=0) return '赛季最终增伤区';
  if(key>=200105 && key<=200112) return '致命一击区（触发时）';
  return '其他属性 / 特殊机制（未确认乘区）';
}
function e0e1ReadBossBuffs(target) {
  if(!target || !target.compBoss) return [];
  var reductions=[103,105,118,119,120,124,126,128,130,132,134,200104,200106,200108,200110,200112,709,1003];
  for(var k=205;k<=208;k++) reductions.push(k);
  for(var j=213;j<=216;j++) reductions.push(j);
  for(var l=221;l<=224;l++) reductions.push(l);
  for(var n=229;n<=232;n++) reductions.push(n);
  reductions.push(234,236,238);
  return ((target.compBuffAssistant && target.compBuffAssistant.buffs) || []).filter(function(b){return !b.isFinish;}).map(function(buff){
    var cfg=buff.cfg || {},share=buff.skillContext && buff.skillContext.shareData,skill=share && share.skillCfg;
    var changes=[];
    function add(value,key) {
      var raw=e0e1AttrNumber(value);if(raw===null || raw===0) return;
      var meta=E0E1_ATTR_KEYS.find(function(m){return m.key===Number(key);});
      changes.push({key:Number(key),name:meta ? meta.label : '属性'+key,value:meta && meta.p ? raw/10000 : raw,
        percent:meta ? meta.p : null,zone:e0e1AttrZone(key),usage:[410,1006].indexOf(Number(key))>=0 ? 'BOSS受击时在扣血阶段处理，不重复乘入增伤' : Number(key)===128 ? '当前客户端类型区读取但未实际抵扣，按实测倍率展示' : reductions.indexOf(Number(key))>=0 ? 'BOSS受击时抵扣（满足适用条件时）' : 'BOSS自身属性/输出；不直接视为受击增伤'});
    }
    if(buff.changeAttributes && buff.changeAttributes.forEach) buff.changeAttributes.forEach(add);
    (buff.endCond || []).forEach(function(cond){if(cond.applied && cond.applied.forEach) cond.applied.forEach(add);});
    return {id:cfg.id,name:cfg.name || cfg.note || 'Buff '+cfg.id,skillId:skill && skill.id,skillName:skill && skill.name,
      sourceName:share && share.source && share.source.name,configuredSources:e0e1BuffOrigins(cfg.id).slice(0,6),configuredSourceCount:e0e1BuffOrigins(cfg.id).length,effectDescriptions:['_beginEffects','_loopEffects','_endEffects','_deadEndEffects'].reduce(function(out,key,index){return out.concat((cfg[key] || []).map(function(expression){return ['获得时','周期触发','结束时','死亡结束时'][index]+'：'+expression;}));},[]),piles:buff.piles,
      remainingSeconds:buff.timeMax>0 ? Math.max(0,Math.ceil(buff.timeMax-buff.time)) : null,tag:cfg.tag || null,changes:changes};
  });
}

// 将本次实际采用的属性拆成相加项；不确定的部分以残差保留，绝不把不适用的面板项强加进去。
function e0e1FactorParts(ctx,inputs,factors,context) {
  var parts={},share=ctx.skillContext && ctx.skillContext.shareData,cfg=e0e1CfgRow('SkillCfg',ctx.skillId);
  if(['attack','coefficient','damage','element','targetType','hp','skillType','attackBonus'].every(function(key){return factors[key]===0;}))return parts;
  function add(zone,side,key) {
    var value=inputs[side] && inputs[side][key];if(value===undefined || value===null) return;
    (parts[zone] || (parts[zone]=[])).push({side:side,key:key,value:side==='target' ? -value : value});
  }
  add('damage','self',104);add('damage','target',105);
  if(ctx.battleWorld.options.battleData.type===1){add('damage','self',125);add('damage','target',126);}
  function pair(method,zone){
    if(!share || typeof share[method]!=='function') return;
    var keys=share[method]();if(keys && keys.length>=2){add(zone,'self',keys[0]);add(zone,'target',keys[1]);}
  }
  pair('getElementAttrType','element');pair('getElementAttrTypeSpecialSkill','element');
  if(ctx.target.compMonster) {
    add('targetType','self',109);add('targetType','self',127);
    var flyType=E0E1_TYPE_COMPONENTS && E0E1_TYPE_COMPONENTS.CompFly;
    if(flyType && ctx.target.getComponent) add('targetType','self',ctx.target.getComponent(flyType) ? 110 : 111);
  }
  // 原客户端在此读取128但未减入 multiplier，不能自行将它抵扣。
  var ratio=context && context.targetHpRatio;
  if(ratio>.8) add('hp','self',113);else if(ratio<.2) add('hp','self',114);
  var book=cfg && e0e1CfgRow('SkillBookCfg',cfg.bookId),sft=cfg && cfg.skillFunctionType,element=cfg && cfg.elementalType;
  var elementAttrOffset={1:1,2:2,3:4,4:3}[element];
  if(book && book.type===1){
    add('skillType','self',116);add('skillType','target',120);
    if(element>=1 && element<=4){add('skillType','self',224+elementAttrOffset);add('skillType','target',228+elementAttrOffset);}
  } else if(!book && sft!==12 || [4,13,17].indexOf(sft)>=0){
    add('skillType','self',115);if([4,13,17].indexOf(sft)>=0) add('skillType','target',119);
  }
  if([5,9,10,11].indexOf(sft)>=0) add('skillType','self',131);
  if([15,16].indexOf(sft)>=0){add('skillType','self',133);add('skillType','target',134);}
  pair('getQualityAttrTypeSpecialSkill','skillType');
  if(cfg && cfg.type===1){add('attackBonus','self',708);add('attackBonus','target',709);}
  var isPvp=!!E0E1_PVP_TYPE[ctx.battleWorld.options.battleData.type];
  if(isPvp) add('pvp','self',117);
  // PVP抵扣值可能来自对局指标，不能用目标面板覆盖实际公式。
  var metrics=ctx.battleWorld.options.mineInfo && ctx.battleWorld.options.mineInfo.pvpMetrics;
  if(isPvp && metrics && context && context.opponentPvpRed!==undefined) {
    (parts.pvp || (parts.pvp=[])).push({side:'opponent',key:118,label:'对面PVP减伤',value:-context.opponentPvpRed});
  } else if(isPvp) add('pvp','target',118);
  add('final','self',123);if(isPvp) add('final','self',129);add('final','target',124);
  if(ctx.isCrit) add('crit','self',102);
  if(ctx.isSkillCrit) {
    if(book && book.type===4) add('skillCrit','self',602);
    else {add('skillCrit','self',107);add('skillCrit','target',130);
      if(element>=1 && element<=4){add('skillCrit','self',216+elementAttrOffset);add('skillCrit','target',220+elementAttrOffset);}
    }
  }
  if(factors.season!==undefined){add('season','self',200103);add('season','target',200104);}
  Object.keys(parts).forEach(function(zone){
    var isAdditive=['targetType','hp','skillType','attackBonus'].indexOf(zone)>=0;
    var expected=isAdditive ? factors[zone] : factors[zone]-1;
    var sum=parts[zone].reduce(function(n,p){return n+p.value;},0),rest=expected-sum;
    if(Math.abs(rest)>1e-8) parts[zone].push({label:zone==='pvp' && metrics ? '对局减伤指标/倍率下限修正' : '条件效果、倍率下限或未拆分部分',value:rest});
  });
  return parts;
}

function e0e1ReadSettlement(ctx){
  var target=ctx.target,life=target && target.compLife,attrs=target && target.compAttributes;
  function component(name){var type=E0E1_LIFE && E0E1_LIFE[name];return type && target.getComponent ? target.getComponent(type) : null;}
  var cap=component('CompMaxDamageSecond'),hold=component('CompHpHold');
  return {inputDamage:e0e1AttrNumber(ctx.damage),hpBefore:e0e1AttrNumber(life && life.current),hpMax:e0e1AttrNumber(life && life.max),
    shieldBefore:e0e1AttrNumber(target && target.compArmor && target.compArmor.current),
    parry:attrs && attrs.get ? e0e1AttrNumber(attrs.get(410)) : null,immunity:attrs && attrs.get ? e0e1AttrNumber(attrs.get(1006)) : null,
    hpHold:hold ? e0e1AttrNumber(hold.minPercent) : null,capMax:cap ? e0e1AttrNumber(cap.maxDamageSecond) : null,
    capUsed:cap ? e0e1AttrNumber(cap.curSecondDamage) : null,blockShield:!!component('CompBlockBlockShield'),
    ignoreArmor:!!ctx.ignoreArmor,reallyDamage:!!ctx.reallyDamage};
}

function e0e1FactorInputs(ctx) {
  var inputs={self:{},target:{}};
  E0E1_ATTR_KEYS.forEach(function(meta){
    if(ctx.sourceAttr && ctx.sourceAttr.get) inputs.self[meta.key]=e0e1AttrNumber(ctx.sourceAttr.get(meta.key));
    if(ctx.targetAttr && ctx.targetAttr.get) inputs.target[meta.key]=e0e1AttrNumber(ctx.targetAttr.get(meta.key));
  });
  var hero=ctx.battleWorld.getFightHero && ctx.battleWorld.getFightHero();
  var entity=hero && hero.compAttributes && hero.compAttributes.attributes===ctx.sourceAttr ? hero : ctx.source;
  var matches=entity && entity.compAttributes && entity.compAttributes.attributes===ctx.sourceAttr;
  var context=e0e1ReadAttrContext(ctx.battleWorld),life=ctx.target && ctx.target.compLife;
  if(life && e0e1AttrNumber(life.max)>0) context.targetHpRatio=e0e1AttrNumber(life.current)/e0e1AttrNumber(life.max);
  return {inputs:inputs,settlement:e0e1ReadSettlement(ctx),provenance:{self:matches ? e0e1ReadAttrSources(ctx.battleWorld,entity) : {},target:e0e1ReadAttrSources(ctx.battleWorld,ctx.target),targetBuffs:e0e1ReadBossBuffs(ctx.target)},
    context:context};
}

// 按秒只读计算：仅调用 calcDmgRate，它只写入新建的本地乘区对象。
// 不调用 createSkillContext/calcDamage/暴击判定，不消耗战斗随机数或执行技能效果。
function e0e1SampleFormulaState(state){
  var mods=E0E1_FORMULA_MODULES,world=state.world;
  if(!mods || !mods.damage || !mods.skill || !mods.decimal || !world)return;
  var time=Number(world.battleTime && world.battleTime.battleTime)||0,sec=Math.floor(time);
  if(state.lastFactorSampleSecond===sec || state.factorSnapshots.length>=12000)return;
  var hero=world.getFightHero && world.getFightHero(),battleContext=world.sceneEntity && world.sceneEntity.battleContext;
  var enemies=battleContext && battleContext.awakenedEnemies || [];
  var target=enemies.find(function(entity){return entity && entity.isValid!==false && entity.compBoss && entity.compAttributes;});
  if(!hero || !target || !hero.compAttributes)return;
  state.lastFactorSampleSecond=sec;
  var actors=[hero];
  ['getFightPet','getFightMagicWeapon'].forEach(function(method){var actor=world[method] && world[method]();if(actor && actors.indexOf(actor)<0)actors.push(actor);});
  var decimal=mods.decimal.DecimalNumber,zero=decimal && decimal.ZERO;
  if(!zero)return;
  actors.forEach(function(actor){
    var recipes=actor.compSkillAssistant && actor.compSkillAssistant.allSkills;
    if(!recipes || !recipes.forEach)return;
    recipes.forEach(function(recipe){
      var cfg=recipe.cfg || e0e1CfgRow('SkillCfg',recipe.skillId);
      if(!cfg || [1,2,3].indexOf(cfg.type)<0 || state.factorSnapshots.length>=12000)return;
      var info=e0e1Classify(cfg.id,state);if(['monster','flag','other','desire','store'].indexOf(info.cat)>=0)return;
      try{
        var share=Object.create(mods.skill.SkillContextShareData.prototype);
        share.world=world;share.source=actor;share.skillCfg=cfg;share.skillRecipe=recipe;
        var ctx=Object.create(mods.damage.DamageContext.prototype);
        ctx.skillContext={shareData:share,effectParams:{}};ctx.source=actor;ctx.target=target;ctx.battleWorld=world;
        ctx.sourceAttr=actor.compAttributes && actor.compAttributes.attributes;ctx.targetAttr=target.compAttributes.attributes;
        ['CompPet','CompBase','CompMagicWeapon','CompSummon'].forEach(function(name){
          var type=mods.hero && mods.hero[name],component=type && actor.getComponent && actor.getComponent(type);
          if(component && component.owner && (name!=='CompSummon' || component.config && component.config.attrInherit===1))ctx.sourceAttr=component.owner.compAttributes.attributes;
        });
        if(!ctx.sourceAttr || !ctx.targetAttr)return;
        ctx.multiplier={};['baseCoeff','dmgAddRate','elementAddRate','hpDmgAddRate','skillTypeAddRate','dmgTypeRate','attackDmgRate','finalDmgRate','pvpDmgRate'].forEach(function(key){ctx.multiplier[key]=zero;});
        ctx.atk=ctx.sourceAttr.get(1);ctx.isCrit=false;ctx.isSkillCrit=false;ctx.isSpCrit=false;ctx.isMobsBoss=true;
        ctx.calcDmgRate();
        var mul=ctx.multiplier,num=e0e1AttrNumber;
        var factors={attack:num(ctx.atk),coefficient:null,damage:num(mul.dmgAddRate),element:num(mul.elementAddRate),
          targetType:num(mul.dmgTypeRate),hp:num(mul.hpDmgAddRate),skillType:num(mul.skillTypeAddRate),attackBonus:num(mul.attackDmgRate),
          pvp:Math.max(.5,1+(num(mul.pvpDmgRate)||0)),final:Math.max(.25,1+(num(mul.finalDmgRate)||0)),crit:1,skillCrit:1};
        factors.type=1+factors.targetType+factors.hp+factors.skillType+factors.attackBonus;
        var snapshot=e0e1FactorInputs(ctx),context=snapshot.context;
        if(state.battleType===20 || state.battleType===27){
          factors.season=1+(snapshot.inputs.self[200103] || 0)-(snapshot.inputs.target[200104] || 0);factors.spCrit=1;
          if(state.battleType===20 && context.stamina){factors.staminaSkill=context.stamina.skillDamage;factors.staminaFinal=context.stamina.finalDamage;}
        }
        var provenance=snapshot.provenance,key=JSON.stringify(provenance),ref=state.factorSourceIndex[key];
        if(ref===undefined){if(state.factorSources.length>=4000)return;ref=state.factorSources.length;state.factorSourceIndex[key]=ref;state.factorSources.push(provenance);}
        state.factorSnapshots.push({sec:sec,firstT:time,lastT:time,skillId:Number(cfg.id),name:info.skillName,bookName:info.bookName,
          group:cfg.type===1 ? 'attack' : info.cat==='book' ? 'book' : 'skill',category:info.cat,boss:true,hits:1,
          sampleKind:'second',formulaMode:'standard',factors:factors,inputs:snapshot.inputs,sourceRef:ref,context:context,
          parts:e0e1FactorParts(ctx,snapshot.inputs,factors,context)});
        state.lastTime=Math.max(state.lastTime,time);
      }catch(error){E0E1_LAST_ERROR='每秒乘区快照：'+String(error);}
    });
  });
}

function e0e1RecordFactors(state,source,skillId,damage,target,info,t) {
  if(state.factorRows.length>=12000){state.factorsTruncated=true;return;}
  var frame=E0E1_DAMAGE_STACK[E0E1_DAMAGE_STACK.length-1],ctx=frame && frame.context;
  if(!target || !target.compBoss || !ctx || ctx.battleWorld!==state.world || ctx.target!==target || Number(ctx.skillId)!==Number(skillId) || info.cat==='flag') return;
  var mul=ctx.multiplier;if(!mul) return;
  frame.recorded=true;
  state.lastTime=Math.max(state.lastTime,t);
  var cfg=e0e1CfgRow('SkillCfg',skillId), group=cfg && cfg.type===1 ? 'attack' : info.cat==='book' ? 'book' : 'skill';
  function num(value){return e0e1AttrNumber(value);}
  var factors={attack:num(ctx.atk),coefficient:num(mul.baseCoeff),damage:num(mul.dmgAddRate),element:num(mul.elementAddRate),
    targetType:num(mul.dmgTypeRate),hp:num(mul.hpDmgAddRate),skillType:num(mul.skillTypeAddRate),attackBonus:num(mul.attackDmgRate),
    pvp:Math.max(.5,1+(num(mul.pvpDmgRate)||0)),final:Math.max(.25,1+(num(mul.finalDmgRate)||0)),
    crit:ctx.isCrit ? Math.max(1,1+(num(ctx.critPwr)||0)) : 1,
    skillCrit:ctx.isSkillCrit ? Math.max(1,1+(num(ctx.skillCritPwr)||0)) : 1};
  factors.type=1+(factors.targetType||0)+(factors.hp||0)+(factors.skillType||0)+(factors.attackBonus||0);
  var snapshot=frame.snapshot || e0e1FactorInputs(ctx),inputs=snapshot.inputs,context=snapshot.context;
  var settlement=snapshot.settlement || {};
  settlement.actualDamage=damage;
  settlement.shieldAfter=e0e1AttrNumber(target && target.compArmor && target.compArmor.current);
  if(settlement.inputDamage>0) factors.settlement=damage/settlement.inputDamage;
  var season=state.battleType===20 || state.battleType===27;
  if(season) {
    var sa=inputs.self[200103],sr=inputs.target[200104];
    factors.season=sa===null || sr===null ? null : 1+sa-sr;
    var attr=function(key){return inputs.self[key] || 0;}, red=function(key){return inputs.target[key] || 0;};
    var hitCount=ctx.skillContext && ctx.skillContext.effectParams && ctx.skillContext.effectParams.hitCount || 0;
    var consts=E0E1_BATTLE_CONST && E0E1_BATTLE_CONST.BattleConst;
    var aoe=consts && hitCount>consts.SPCRIT_AOE_HIT_COUNT;
    factors.spCrit=ctx.isSpCrit ? 1+attr(200107)-red(200108)+(aoe ? attr(200111)-red(200112) : 0) : 1;
    factors.spCritAoe=!!aoe;
    if(state.battleType===20 && context.stamina) {
      factors.staminaSkill=context.stamina.skillDamage;factors.staminaFinal=context.stamina.finalDamage;
    }
  }
  var parts=e0e1FactorParts(ctx,inputs,factors,context);
  var provenance=snapshot.provenance,sourceKey=JSON.stringify(provenance);
  var sourceRef=state.factorSourceIndex[sourceKey];
  if(sourceRef===undefined) {
    if(state.factorSources.length>=4000) {state.factorsTruncated=true;return;}
    sourceRef=state.factorSources.length;state.factorSourceIndex[sourceKey]=sourceRef;state.factorSources.push(provenance);
  }
  var sec=Math.floor(t),key=JSON.stringify([sec,Number(skillId),ctx.source && ctx.source.uuid,target && target.uuid,!!ctx.reallyDamage,!!ctx.isSeckill,factors,inputs,sourceRef,context,parts,settlement]);
  var identity=JSON.stringify([Number(skillId),ctx.source && ctx.source.uuid,target && target.uuid]);
  var last=state.factorIndex[identity],row=last && last.signature===key ? last.row : null;
  if(!row) {
    if(state.factorRows.length>=12000){state.factorsTruncated=true;return;}
    row={sec:sec,firstT:t,lastT:t,skillId:Number(skillId),name:info.skillName,bookName:info.bookName,group:group,category:info.cat,
      sourceId:ctx.source && ctx.source.uuid,sourceName:ctx.source && ctx.source.name,targetName:target && target.name,targetId:target && target.uuid,
      boss:!!(target && target.compBoss),element:info.element,sourceRef:sourceRef,formulaMode:['attack','coefficient','damage','element','targetType','hp','skillType','attackBonus'].every(function(key){return factors[key]===0;}) ? 'independent' : 'standard',
      trueDamage:!!ctx.reallyDamage,seckill:!!ctx.isSeckill,factors:factors,parts:parts,settlement:settlement,inputs:inputs,context:context,hits:0,damage:0};
    state.factorIndex[identity]={signature:key,row:row};state.factorRows.push(row);
  }
  row.lastT=t;row.hits++;row.damage+=damage;
}

// ── 挂接 / 摘除 ──

// 单个 World 的挂接（可重复调用，已挂的会跳过）。
// 拆成独立函数是因为要在 createBattle 的钩子里同步调用：
// 好友切磋跳过时第一件事就是 detachBattleWorlds 把 World 移出 getBattles()，
// 只靠 500ms 轮询的话，用户一进战斗就点跳过我们就一次都轮不到。
function e0e1TryAttachWorld(world) {
  if (!world || world.isQuitted || !world.battleSignal) return false;
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
  if (state.replay || side === "self") e0e1ResetPvpIfNewBattle(state);
  E0E1_SIDES[side] = state;
  return true;
}

// 分数采样是全局累积的（不走 E0E1_SIDES），不按场次归零的话
// 第二场会接着第一场的秒数往下记，时间轴被拼成两场之和。
function e0e1ResetPvpIfNewBattle(state) {
  var key = state.replay ? "replay-session:" + state.replay.sessionId : String(state.instanceId) + "|" + String(state.battleType) + "|" + String(state.seed);
  if (!E0E1_PVP.instanceKey) {
    E0E1_PVP.instanceKey = key;
    E0E1_PVP.battleType = state.battleType;
    return false;
  }
  if (E0E1_PVP.instanceKey === key) return false;
  E0E1_SIDES = {self:null,other:null};
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
  e0e1PatchFactorCapture();
  if (E0E1_BM_PATCHED || !E0E1_BM) return false;
  var BM = E0E1_BM.BattleManager;
  var ins = BM && BM.ins;
  if (!ins) return false;
  var patched = false;
  var LocalController=E0E1_LOCAL_DUAL && E0E1_LOCAL_DUAL.DualScorePvpBattleManager;
  var localProto=LocalController && LocalController.prototype;
  if(localProto && typeof localProto.skipBattleLocalFastForward==='function' && !localProto.skipBattleLocalFastForward.__e0e1SkipCaptured){
    var skipOriginal=localProto.skipBattleLocalFastForward;
    localProto.skipBattleLocalFastForward=function(){
      var selfWorld=this.selfBattleWorld,otherWorld=this.otherBattleWorld;
      var isFriendly=!!(selfWorld && otherWorld && selfWorld.options && selfWorld.options.battleData && selfWorld.options.battleData.type===26);
      if(isFriendly){
        try {e0e1WatchWorld(selfWorld);e0e1WatchWorld(otherWorld);e0e1SamplePvp();E0E1_PVP.skipped=true;}catch(error){E0E1_LAST_ERROR='跳过采集准备：'+String(error);}
      }
      try {return skipOriginal.apply(this,arguments);}
      finally {if(isFriendly){try {e0e1SamplePvp(true);}catch(error){E0E1_LAST_ERROR='跳过最终采样：'+String(error);}}}
    };
    localProto.skipBattleLocalFastForward.__e0e1SkipCaptured=true;
    E0E1_PATCHES.push({owner:localProto,key:'skipBattleLocalFastForward',original:skipOriginal,wrapper:localProto.skipBattleLocalFastForward});
  }
  var Controller = E0E1_DUAL && E0E1_DUAL.ArenaDualScorePvpBattleManager;
  var proto = Controller && Controller.prototype;
  if (proto && typeof proto.start === 'function' && !proto.start.__e0e1ReplayTagged) {
    var startOriginal = proto.start;
    proto.start = function(options) {
      E0E1_REPLAY_CONTEXTS = E0E1_REPLAY_CONTEXTS.filter(function(c){return c.controller !== this;},this);
      E0E1_REPLAY_CONTEXTS.push({controller:this,meta:{sessionId:++E0E1_REPLAY_SERIAL,
        isReplay:!!options.isReplay,openType:options.openType||null}});
      if (E0E1_REPLAY_CONTEXTS.length > 8) E0E1_REPLAY_CONTEXTS.shift();
      return startOriginal.apply(this,arguments);
    };
    proto.start.__e0e1ReplayTagged = true;
    E0E1_PATCHES.push({owner:proto,key:'start',original:startOriginal,wrapper:proto.start});
  }

  // (1) World 一创建就挂。注意 battleSignal 的信号可能是延迟建好的，这里挂不上没关系，
  //     下面的 detachBattleWorlds 兜底，轮询也会补挂。
  if (typeof ins.createBattle === "function" && !ins.__e0e1CreatePatched) {
    var createOriginal = ins.createBattle;
    ins.createBattle = function (type, options) {
      var world = createOriginal.call(ins, type, options);
      try {
        for(var rc=E0E1_REPLAY_CONTEXTS.length-1;rc>=0;rc--){
          var context=E0E1_REPLAY_CONTEXTS[rc], c=context.controller;
          if(options && options.mineInfo && (options.mineInfo===c.selfScoreInfo || options.mineInfo===c.otherScoreInfo)) {
            world.__e0e1DamageReplay = context.meta; break;
          }
        }
        e0e1WatchWorld(world);
      } catch (error) {}
      return world;
    };
    E0E1_PATCHES.push({owner:ins,key:'createBattle',original:createOriginal,wrapper:ins.createBattle,flag:'__e0e1CreatePatched'});
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
    E0E1_PATCHES.push({owner:ins,key:'detachBattleWorlds',original:detachOriginal,wrapper:ins.detachBattleWorlds,flag:'__e0e1DetachPatched'});
    ins.__e0e1DetachPatched = true;
    patched = true;
  }

  if (patched) E0E1_BM_PATCHED = true;
  return patched;
}

function e0e1AttachAll() {
  E0E1_REPLAY_CONTEXTS=E0E1_REPLAY_CONTEXTS.filter(function(context){
    var controller=context.controller,worlds=[controller.selfBattleWorld,controller.otherBattleWorld].filter(Boolean);
    return !worlds.length || worlds.some(function(world){return !world.isQuitted;});
  });
  if (!E0E1_BM_PATCHED) e0e1PatchBattleManager();
  // 候选 = createBattle 钩到的 + getBattles() 里现存的
  E0E1_WATCHED = E0E1_WATCHED.filter(function(world){return world && !world.isQuitted;});
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
    // 保留报告的纯数据，释放已退出 World 对场景、实体和纹理的强引用。
    if(dead.state && dead.world && dead.world.isQuitted)dead.state.world=null;
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
    replay: state.replay,
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
    events: state.events,
    factorSnapshots:state.factorSnapshots, factorRows: state.factorRows, factorSources: state.factorSources, factorsTruncated: state.factorsTruncated
  };
}

// 给双方各补一条「最终PVP增伤」= 本方PVP增伤 − 对方PVP减伤
function e0e1WithFinalPvp(rows) {
  var out = [];
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i] || {};
    var self = row.self || {}, other = row.other || {};
    var item = { sec: row.sec, self: {}, other: {}, selfSources:row.selfSources,otherSources:row.otherSources,selfContext:row.selfContext,otherContext:row.otherContext };
    for (var a in self) item.self[a] = self[a];
    for (var b in other) item.other[b] = other[b];
    var selfRed=row.selfContext && row.selfContext.opponentPvpRed;
    var otherRed=row.otherContext && row.otherContext.opponentPvpRed;
    if(selfRed===undefined) selfRed=other[118];
    if(otherRed===undefined) otherRed=self[118];
    if(self[117]!==undefined && selfRed!==undefined) item.self[E0E1_FINAL_PVP_KEY]=self[117]-selfRed;
    if(other[117]!==undefined && otherRed!==undefined) item.other[E0E1_FINAL_PVP_KEY]=other[117]-otherRed;
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
      factorRows: st.factorRows.length, factorSnapshots: st.factorSnapshots.length, factorSources: st.factorSources.length,
      rawEvents: st.events.length, activeBranches: st.activeBranches.length
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
  E0E1_PATCHES.slice().reverse().forEach(function(patch){
    if(patch.owner[patch.key]===patch.wrapper) {
      patch.owner[patch.key]=patch.original;
      if(patch.flag) patch.owner[patch.flag]=false;
    }
  });
  E0E1_PATCHES=[];E0E1_BM_PATCHED=false;E0E1_REPLAY_CONTEXTS=[];
  if (E0E1_TIMER) {
    var game = e0e1ResolveGameWindow();
    if (game && game.clearInterval) game.clearInterval(E0E1_TIMER);
    else clearInterval(E0E1_TIMER);
    E0E1_TIMER = null;
  }
  e0e1DetachAll();
  return "已停止采集";
}

// 可选诊断仅在手动启用 e0e1Perf 时计时，不保存参数或战斗对象。
var e0e1SampleFormulaOriginal=e0e1SampleFormulaState,e0e1RecordFactorsOriginal=e0e1RecordFactors;
e0e1SampleFormulaState=function(){var p=globalThis.e0e1Perf;return p?p.measure('damage.snapshot.sync',e0e1SampleFormulaOriginal,this,arguments):e0e1SampleFormulaOriginal.apply(this,arguments);};
e0e1RecordFactors=function(){var p=globalThis.e0e1Perf;return p?p.measure('damage.factors.sync',e0e1RecordFactorsOriginal,this,arguments):e0e1RecordFactorsOriginal.apply(this,arguments);};

// ── 轮询挂接 ──

function e0e1Tick() {
  try {
    var p=globalThis.e0e1Perf;
    if(p){p.measure('damage.attach.sync',e0e1AttachAll,null,[]);p.measure('damage.sample.sync',e0e1SamplePvp,null,[]);}
    else {e0e1AttachAll();e0e1SamplePvp();}
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
