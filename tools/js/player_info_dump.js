// ==UserScript==
// @name 玩家信息导出
// @description 打开玩家信息界面（Setting）时，按界面显示方式解析 GDRoleSnap 快照（天书/三尸/脸谱/鬼仆阵法/法器），用配置表把 ID 翻成中文名并展开词条效果。含被对方隐藏的部分。注入后可手动调用 dumpPlayerInfo()。
// @match *
// @run-at document-start
// @e0e1-mode once
// ==/UserScript//

// 说明：本脚本以语句形式直接执行（e0e1 的注入包装是 async 函数，可直接使用 await）。
// 数据来源：UISetting.onOpen → RoleService.getRolePreviewInfo → resp.preview（GDRoleSnap，game.js:39868）
// 名称解析：System.import("chunks:///_virtual/configs.ts") 拿配置表，getById 翻译。
// 结构映射由 tools/cdp_deep_probe.py 实测内存结构确认。
// 工具默认注入到 top 上下文，游戏在 name="gameContext" 的 iframe 里，需跨进去取全局。

// EPreviewHideType（game.js:37382）
var E0E1_HIDE_NAMES = { 0: "天书", 1: "三尸", 2: "脸谱", 3: "鬼仆阵法", 4: "法器" };

// ModuleType（game.js:30273），官方没有中文注释表，这里按枚举名翻译
var E0E1_MODULE_NAMES = {
  1: "关卡", 2: "属性成长", 3: "技能", 4: "招募", 5: "天书特技", 6: "外观", 7: "图鉴",
  8: "基础属性", 9: "鬼仆", 10: "阴司", 11: "技能超限", 12: "挑战", 14: "丹药",
  15: "鬼仆随机", 16: "心愿", 17: "人气招募", 18: "百鬼夜行", 19: "奖励渠道", 20: "影院",
  21: "鬼仆阵法", 22: "稀有技组合", 23: "脸谱", 24: "天书觉醒", 25: "摸金行动",
  26: "好友", 27: "组队", 28: "成就", 29: "更多", 30: "跨服", 31: "赛季竞技",
  32: "基础水晶", 33: "走阴", 34: "斗法", 35: "斗法切磋", 36: "法器", 37: "好友对战",
  38: "赛季", 39: "赛季副本",
  101: "邮件", 102: "商店", 103: "聊天", 104: "七日", 105: "任务", 106: "随机商店",
  107: "特权", 108: "背包", 109: "战令", 110: "首充", 111: "排行", 112: "挂机",
  113: "世界BOSS", 114: "挑战副本", 115: "鬼仆副本", 116: "开服七日", 117: "周末",
  118: "阴墟", 119: "阴司货运", 120: "推送礼包", 121: "皮肤礼包"
};

var E0E1_BASE_FIELDS = [
  ["id", "角色ID"], ["name", "昵称"], ["sid", "服ID"], ["sName", "服务器"],
  ["level", "等级"], ["fightPower", "战力"], ["maxFightPower", "最高战力"],
  ["heroId", "主角ID"], ["legionId", "阴司ID"], ["legionName", "阴司"],
  ["chargeTotal", "累计充值"], ["stageWave", "关卡波次"], ["loginOutAt", "最后登出"]
];

// 未确认归属的 ID 用这张有序候选表兜底，取第一个能翻出中文名的
var E0E1_FALLBACK_TABLES = [
  "PetSkillCfg", "PetRandomSkillCfg", "PetSamsaraCfg", "SkillBookCfg",
  "MagicArtifactEntryCfg", "MagicArtifactStoneCfg", "MagicArtifactTemperCfg",
  "MagicArtifactCollectionCfg", "MagicArtifactBaseCfg", "EquipmentEntryCfg", "ItemCfg"
];

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

function e0e1IsMap(value) {
  return !!value && Object.prototype.toString.call(value) === "[object Map]";
}

function e0e1ForEachMap(value, limit, fn) {
  if (!e0e1IsMap(value)) return;
  var i = 0;
  value.forEach(function (item, key) {
    if (i++ >= limit) return;
    fn(item, key);
  });
}

// ── 配置表 ──

var e0e1CfgModule = null;
var e0e1CfgTried = false;

async function e0e1LoadCfg() {
  if (e0e1CfgModule || e0e1CfgTried) return e0e1CfgModule;
  e0e1CfgTried = true;
  try {
    var game = e0e1ResolveGameWindow();
    var loader = game && game.System;
    if (loader && typeof loader.import === "function") {
      var timeout = new Promise(function (resolve) { setTimeout(function () { resolve(null); }, 3000); });
      e0e1CfgModule = await Promise.race([loader.import("chunks:///_virtual/configs.ts"), timeout]) || null;
    }
  } catch (error) {
    e0e1CfgModule = null;
  }
  return e0e1CfgModule;
}

function e0e1Row(cfgName, id) {
  if (!cfgName || id === undefined || id === null) return null;
  try {
    var table = e0e1CfgModule && e0e1CfgModule[cfgName];
    if (!table || typeof table.getById !== "function") return null;
    return table.getById(Number(id)) || null;
  } catch (error) {
    return null;
  }
}

function e0e1IsCjk(text) {
  return !!text && /[\u4e00-\u9fa5]/.test(String(text));
}

// 只认包含中文的名字，避免把 "ID1001" 这类占位值当名字。
// AttrCfg 的 name 是数字，真正的中文名在 note（如 106 → "技能攻击时的暴击概率"）。
function e0e1NameOf(row) {
  if (!row) return null;
  var candidates = [row.name, row.Name, row.cfgName, row.title];
  if (row.itemId && typeof row.itemId === "object") candidates.push(row.itemId.name);
  candidates.push(row.note);
  for (var i = 0; i < candidates.length; i++) {
    if (e0e1IsCjk(candidates[i])) return String(candidates[i]);
  }
  return null;
}

function e0e1DescOf(row) {
  if (!row) return null;
  var candidates = [row.desc, row.des, row.description];
  if (row.itemId && typeof row.itemId === "object") candidates.push(row.itemId.desc);
  for (var i = 0; i < candidates.length; i++) {
    if (e0e1IsCjk(candidates[i])) return String(candidates[i]);
  }
  return null;
}

function e0e1ResolveName(cfgName, id) {
  var name = e0e1NameOf(e0e1Row(cfgName, id));
  if (name) return name;
  for (var i = 0; i < E0E1_FALLBACK_TABLES.length; i++) {
    var fallback = e0e1NameOf(e0e1Row(E0E1_FALLBACK_TABLES[i], id));
    if (fallback) return fallback;
  }
  return null;
}

function e0e1ResolveDesc(cfgName, id) {
  return e0e1DescOf(e0e1Row(cfgName, id));
}

// AttrCfg.style === 2 表示百分比，原始值是 ×100 后的整数（如 66057 → 660.57%）
function e0e1FormatAttr(attrId, value) {
  var row = e0e1Row("AttrCfg", attrId);
  var style = row && row.style !== undefined ? Number(row.style) : 0;
  if (style !== 2 || value === undefined || value === null) return String(value);
  var percent = Number(value) / 100;
  return String(Math.round(percent * 100) / 100) + "%";
}

// ── 各分区解析（结构经内存实测确认）──

// 天书：equipSkill = 槽位→天书ID，skillLevel = 天书ID→等级
function e0e1ParseEquippedSkills(snapshot) {
  var lines = [];
  e0e1ForEachMap(snapshot.equipSkill, 12, function (skillId, slot) {
    var name = e0e1ResolveName("SkillBookCfg", skillId);
    if (!name) return;
    lines.push("· 槽位" + slot + " " + name);
  });
  return lines;
}

function e0e1ParseSkillLevels(snapshot) {
  var lines = [];
  e0e1ForEachMap(snapshot.skillLevel, 40, function (level, skillId) {
    var name = e0e1ResolveName("SkillBookCfg", skillId);
    if (!name) return;
    lines.push("· " + name + " Lv." + level);
  });
  return lines;
}

function e0e1ParseEpicLevels(snapshot) {
  var lines = [];
  e0e1ForEachMap(snapshot.epicLevel, 20, function (level, id) {
    var name = e0e1ResolveName("SkillBookCfg", id);
    if (!name) return;
    lines.push("· " + name + " Lv." + level);
  });
  return lines;
}

// 顶级天书觉醒：外层天书ID → 内层 觉醒分支ID→等级（多分支）
function e0e1ParseEpicAwakening(snapshot) {
  var lines = [];
  e0e1ForEachMap(snapshot.epicAwakening, 20, function (branches, bookId) {
    var bookName = e0e1ResolveName("SkillBookCfg", bookId);
    if (!bookName || !e0e1IsMap(branches)) return;
    var parts = [];
    e0e1ForEachMap(branches, 20, function (level, branchId) {
      var branchName = e0e1ResolveName("SkillBookEvolutionCfg", branchId);
      if (branchName) parts.push(branchName + " Lv." + level);
    });
    if (!parts.length) return;
    lines.push("· " + bookName + "：" + parts.join("、"));
  });
  return lines;
}

function e0e1ParseSkillCombine(snapshot) {
  var lines = [];
  e0e1ForEachMap(snapshot.skillCombineLevel, 20, function (level, id) {
    var name = e0e1ResolveName("RareskillCombCfg", id) || e0e1ResolveName("SkillBookCfg", id);
    if (!name) return;
    lines.push("· " + name + " Lv." + level);
  });
  return lines;
}

// 三尸：key = 槽位<<16 | 序号，value = 三尸ID（DesireCfg 行的 itemId 里带名字和效果描述）
function e0e1ParseDesirePlan(planMap, label) {
  var lines = [];
  if (!e0e1IsMap(planMap)) return lines;
  var grouped = {};
  e0e1ForEachMap(planMap, 60, function (desireId, key) {
    var slot = Math.floor(Number(key) / 65536);
    var row = e0e1Row("DesireCfg", desireId);
    var name = e0e1NameOf(row);
    if (!name) return;
    var desc = e0e1ResolveDesc("DesireCfg", desireId);
    var quality = row && row.itemId ? row.itemId.quality : 0;
    var text = name + (quality ? "(品质" + quality + ")" : "") +
      (desc ? " —— " + desc.replace(/\s+/g, " ").slice(0, 60) : "");
    if (!grouped[slot]) grouped[slot] = [];
    grouped[slot].push(text);
  });
  Object.keys(grouped).sort().forEach(function (slot) {
    grouped[slot].forEach(function (text, index) {
      lines.push("· " + label + " 槽" + slot + "#" + (index + 1) + " " + text);
    });
  });

  // 只汇总无条件面板属性；描述里的层数、概率、条件增伤不能当成常驻值相加。
  var pvpUp=0,pvpDown=0,conditional=0;
  e0e1ForEachMap(planMap,80,function(desireId){
    var row=e0e1Row('DesireCfg',desireId),attrs=row && row.attr;
    function value(key){return Number(attrs && (attrs.get ? attrs.get(key) : attrs[key])) || 0;}
    pvpUp+=value(117)/100;pvpDown+=value(118)/100;
    if(row && row.skill && row.skill.length)conditional++;
  });
  if(pvpUp || pvpDown)lines.push('· '+label+' 常驻面板汇总：PVP增伤 '+pvpUp+'%、PVP减伤 '+pvpDown+'%');
  if(conditional)lines.push('· 另有 '+conditional+' 项技能效果，按触发条件与实际层数生效，不计入常驻面板汇总');
  return lines;
}

// allDesirePlan 是 Map<方案ID, Map<槽位键, 三尸ID>>，可能有多套方案
function e0e1ParseAllDesirePlans(snapshot) {
  var lines = [];
  if (!e0e1IsMap(snapshot.allDesirePlan)) return lines;
  snapshot.allDesirePlan.forEach(function (planMap, planId) {
    var planLines = e0e1ParseDesirePlan(planMap, "[方案" + planId + "]");
    planLines.forEach(function (line) { lines.push(line); });
    if (planLines.length) lines.push("");
  });
  return lines;
}

// 脸谱：槽位→{configId, entry:[{id,value,unlock}]}，等级在 equipmentLevel
function e0e1ParseEquipment(snapshot) {
  var lines = [];
  var levelMap = snapshot.equipmentLevel;
  e0e1ForEachMap(snapshot.equipment, 10, function (item, slot) {
    if (!item || item.configId === undefined) return;
    var row = e0e1Row("EquipmentCfg", item.configId);
    var name = e0e1NameOf(row);
    if (!name) return;
    var level = e0e1IsMap(levelMap) ? levelMap.get(slot) : undefined;
    var parts = ["· " + name];
    if (level !== undefined && level !== null) parts.push("等级" + level);
    if (row && row.quality) parts.push("品质" + row.quality);
    if (row && row.star) parts.push(row.star + "星");
    lines.push(parts.join(" "));
    if (Array.isArray(item.entry)) {
      var entries = [];
      item.entry.slice(0, 8).forEach(function (entry) {
        var entryRow = e0e1Row("EquipmentEntryCfg", entry.id);
        var entryName = e0e1NameOf(entryRow);
        if (!entryName) return;
        // entryRow.group 指向 AttrCfg，用来判断要不要按百分比显示
        var shown = e0e1FormatAttr(entryRow && entryRow.group, entry.value);
        entries.push(entryName + " " + shown + (entry.unlock ? "(已解锁)" : ""));
      });
      if (entries.length) lines.push("   词条：" + entries.join("、"));
    }
  });
  return lines;
}

function e0e1ParseEquipmentSuit(snapshot) {
  var lines = [];
  e0e1ForEachMap(snapshot.equipmentSuit, 10, function (count, id) {
    var name = e0e1ResolveName("EquipmentSuitCfg", id);
    if (!name) return;
    lines.push("· " + name + " " + count + "件");
  });
  return lines;
}

// 鬼仆：{cfgId, quality, level, entry:[词条ID], skillLevel:Map<技能ID,等级>}
function e0e1ParsePet(snapshot) {
  var lines = [];
  var pet = snapshot.pet;
  if (!pet || pet.cfgId === undefined) return lines;
  var name = e0e1ResolveName("PetCfg", pet.cfgId);
  if (!name) return lines;
  lines.push("· 出战 " + name + " 等级" + pet.level + (pet.quality ? " 品质" + pet.quality : ""));
  if (Array.isArray(pet.entry) && pet.entry.length) {
    var entries = [];
    pet.entry.slice(0, 8).forEach(function (id) {
      var entryName = e0e1ResolveName("PetEntryCfg", id);
      if (!entryName) return;
      var desc = e0e1ResolveDesc("PetEntryCfg", id);
      entries.push(entryName + (desc ? "(" + desc.replace(/鬼仆获得|成长能力|的/g, "").slice(0, 24) + ")" : ""));
    });
    if (entries.length) lines.push("   词条：" + entries.join("、"));
  }
  var skills = [];
  e0e1ForEachMap(pet.skillLevel, 10, function (level, id) {
    var skillName = e0e1ResolveName("SkillBookCfg", id);
    if (skillName) skills.push(skillName + " Lv." + level);
  });
  if (skills.length) lines.push("   技能：" + skills.join("、"));
  return lines;
}

// 阵法：formationPetInfo.formationPetInfo 槽位→鬼仆
function e0e1ParseFormation(snapshot) {
  var lines = [];
  var info = snapshot.formationPetInfo;
  if (!info) return lines;
  if (info.formationLevel !== undefined) lines.push("· 阵法等级 " + info.formationLevel);
  var inner = info.formationPetInfo;
  if (!e0e1IsMap(inner)) return lines;
  e0e1ForEachMap(inner, 6, function (pet, slot) {
    if (!pet || pet.cfgId === undefined) return;
    var name = e0e1ResolveName("PetCfg", pet.cfgId);
    if (!name) return;
    var parts = ["· 阵位" + slot + " " + name + " 等级" + pet.level];
    if (Array.isArray(pet.entry) && pet.entry.length) {
      var entries = [];
      pet.entry.slice(0, 6).forEach(function (id) {
        var entryName = e0e1ResolveName("PetEntryCfg", id);
        if (entryName) entries.push(entryName);
      });
      if (entries.length) parts.push("[" + entries.join("、") + "]");
    }
    lines.push(parts.join(" "));
  });
  return lines;
}

// 法器：{onUseMagic, refineLevel, plan: Map<方案ID,{name, entry:Map<槽,{cfgId,value}>}>}
function e0e1ParseMagic(snapshot) {
  var lines = [];
  var magic = snapshot.magic;
  if (!magic) return lines;
  var current = e0e1ResolveName("MagicArtifactBaseCfg", magic.onUseMagic);
  var head = [];
  if (current) head.push("当前法器 " + current);
  if (magic.refineLevel !== undefined) head.push("精炼" + magic.refineLevel + "阶");
  if (magic.refineCount !== undefined) head.push("精炼次数" + magic.refineCount);
  if (head.length) lines.push("· " + head.join(" "));

  if (!e0e1IsMap(magic.plan)) return lines;
  e0e1ForEachMap(magic.plan, 8, function (item, planId) {
    if (!item) return;
    var parts = [];
    if (e0e1IsMap(item.entry)) {
      // 方案条目 cfgId 属于 MagicArtifactEntryCfg，des 是词条名，attrType 指向 AttrCfg
      var pvpUp = 0, pvpDown = 0;
      e0e1ForEachMap(item.entry, 8, function (entry, slot) {
        if (!entry || entry.cfgId === undefined) return;
        var entryRow = e0e1Row("MagicArtifactEntryCfg", entry.cfgId);
        var name = entryRow && e0e1IsCjk(entryRow.des) ? entryRow.des : null;
        var shown = e0e1FormatAttr(entryRow && entryRow.attrType, entry.value);
        parts.push((name || ("词条ID" + entry.cfgId)) + " " + shown);
        if (!name) return;
        if (/pvp增伤/i.test(name)) pvpUp += Number(entry.value) / 100;
        else if (/pvp减伤|pvp减免/i.test(name)) pvpDown += Number(entry.value) / 100;
      });
    }
    lines.push("· 方案「" + (item.name || planId) + "」" + (parts.length ? "：" + parts.join("、") : ""));
    if (pvpUp || pvpDown) {
      var summary = "   └ 汇总：PVP增伤 " + (Math.round(pvpUp * 100) / 100) + "%";
      if (pvpDown) summary += "、PVP减伤 " + (Math.round(pvpDown * 100) / 100) + "%";
      lines.push(summary);
    }
  });
  return lines;
}

function e0e1ParseAttributes(snapshot) {
  var lines = [];
  // attribute 实际有 50+ 条（含 PVP增伤/减免等），上限要够大
  e0e1ForEachMap(snapshot.attribute, 80, function (value, attrId) {
    var name = e0e1ResolveName("AttrCfg", attrId);
    if (!name) return;
    lines.push("· " + name + " " + e0e1FormatAttr(attrId, value));
  });
  return lines;
}

function e0e1ParseModules(snapshot) {
  var ids = snapshot.unlockModuleIds;
  if (!Array.isArray(ids) || !ids.length) return [];
  return ["· 已解锁玩法：" + ids.slice(0, 40).map(function (id) {
    return E0E1_MODULE_NAMES[id] || ("ID" + id);
  }).join("、")];
}

// 使用实际穿戴fashion，onShow只是展示外观，不据此判断战斗装备。
function e0e1ParseFashion(snapshot) {
  var equipped = e0e1IsMap(snapshot.fashion) ? snapshot.fashion : snapshot.fashion && snapshot.fashion.onUse;
  if (!e0e1IsMap(equipped)) return ['· 傀儡装穿戴资料未下发'];
  var lines = [];
  e0e1ForEachMap(equipped, 30, function (id, slot) {
    var cfg = e0e1Row('FashionCfg', id);
    var levels = snapshot.allFashion || (snapshot.fashion && snapshot.fashion.level);
    var level = e0e1IsMap(levels) ? levels.get(Number(id)) : null;
    var name = e0e1NameOf(cfg) || ('傀儡装ID' + id);
    lines.push('· ' + (name === '雷法尊者' ? '【雷法尊者】 ' : '') + name +
      '（已穿戴，部位' + slot + (level !== null && level !== undefined ? '，Lv' + level : '') + '）');
  });
  lines.sort(function(a,b){return Number(b.indexOf('【雷法尊者】') >= 0)-Number(a.indexOf('【雷法尊者】') >= 0);});
  return lines.length ? lines : ['· 未穿戴傀儡装'];
}

// ── 组装与输出 ──

function e0e1DecodeHide(mask) {
  var value = Number(mask) || 0;
  var names = [];
  for (var bit = 0; bit < 8; bit++) {
    if (value & (1 << bit)) names.push(E0E1_HIDE_NAMES[bit] || ("bit" + bit));
  }
  return { raw: value, names: names };
}

async function e0e1BuildDump(snapshot, isSelf) {
  await e0e1LoadCfg();
  var dump = {
    title: "玩家信息",
    dumpedAt: new Date().toISOString(),
    isSelf: !!isSelf,
    cfgReady: !!e0e1CfgModule,
    base: [],
    hide: e0e1DecodeHide(snapshot.previewHide),
    sections: []
  };
  E0E1_BASE_FIELDS.forEach(function (pair) {
    var value = snapshot[pair[0]];
    if (value === undefined || value === null || value === "" || value === 0) return;
    dump.base.push([pair[1], value]);
  });

  function add(name, blocks) {
    var filled = blocks.filter(function (block) { return block.lines.length; });
    if (filled.length) dump.sections.push({ name: name, blocks: filled });
  }

  add("傀儡装", [{ label: "当前穿戴", lines: e0e1ParseFashion(snapshot) }]);
  add("天书", [
    { label: "装备中", lines: e0e1ParseEquippedSkills(snapshot) },
    { label: "天书等级", lines: e0e1ParseSkillLevels(snapshot) },
    { label: "顶级天书", lines: e0e1ParseEpicLevels(snapshot) },
    { label: "顶级天书觉醒", lines: e0e1ParseEpicAwakening(snapshot) },
    { label: "天书组合", lines: e0e1ParseSkillCombine(snapshot) }
  ]);
  add("三尸", [
    { label: "当前装备", lines: e0e1ParseDesirePlan(snapshot.desirePlan, "[当前]") },
    { label: "全部方案", lines: e0e1ParseAllDesirePlans(snapshot) }
  ]);
  add("脸谱", [
    { label: "已穿戴", lines: e0e1ParseEquipment(snapshot) },
    { label: "套装", lines: e0e1ParseEquipmentSuit(snapshot) }
  ]);
  add("鬼仆阵法", [
    { label: "出战鬼仆", lines: e0e1ParsePet(snapshot) },
    { label: "阵法", lines: e0e1ParseFormation(snapshot) }
  ]);
  add("法器", [
    { label: "法器", lines: e0e1ParseMagic(snapshot) }
  ]);
  add("其他", [
    { label: "属性", lines: e0e1ParseAttributes(snapshot) },
    { label: "玩法", lines: e0e1ParseModules(snapshot) }
  ]);
  return dump;
}

function e0e1RenderText(dump) {
  var lines = [];
  lines.push("===== 玩家信息 " + dump.dumpedAt + " =====");
  lines.push(dump.base.map(function (pair) { return pair[0] + "=" + pair[1]; }).join("  "));
  lines.push("对方隐藏: " + (dump.hide.names.length ? dump.hide.names.join("、") + "（位掩码 " + dump.hide.raw + "）" : "无"));
  lines.push(dump.cfgReady ? "名称解析: 已加载配置表" : "名称解析: 未拿到配置表，仅显示能解析出的项");
  lines.push("※ 下面各分区来自本地快照，不受对方隐藏设置影响");
  if (!dump.sections.length) {
    lines.push("[快照中没有可展示的数据]");
    return lines.join("\n");
  }
  dump.sections.forEach(function (section) {
    lines.push("");
    lines.push("── " + section.name + " ──");
    section.blocks.forEach(function (block) {
      lines.push("  [" + block.label + "]");
      block.lines.forEach(function (line) {
        lines.push("  " + line);
      });
    });
  });
  return lines.join("\n");
}

var e0e1LastReport = "";

function e0e1Emit(dump) {
  var text = e0e1RenderText(dump);
  e0e1LastReport = text.slice(0, 12000);
  console.log("[e0e1][玩家信息]\n" + text);
  console.log("[e0e1][玩家信息] 完整数据", dump);
  if (typeof globalThis.__e0e1JsInjectionReport === "function") {
    globalThis.__e0e1JsInjectionReport(text);
  }
  return dump;
}

// 只返回渲染好的文本，方便通过 CDP 直接取回（命令行注入时用）
async function e0e1DumpPlayerInfoText() {
  var game = e0e1ResolveGameWindow();
  if (!game) return "未找到 gameContext";
  var ui = e0e1FindSettingUi();
  if (!ui) return "当前没有打开玩家信息界面（Setting）";
  var snapshot = ui.info;
  for (var attempt = 0; attempt < 16 && !snapshot && !ui.isSelf; attempt++) {
    await new Promise(function (resolve) { setTimeout(resolve, 250); });
    snapshot = ui.info;
  }
  if (!snapshot) snapshot = e0e1SelfSnapshot(game);
  if (!snapshot) return "没拿到快照数据";
  return e0e1RenderText(await e0e1BuildDump(snapshot, ui.isSelf));
}

function e0e1Fail(message) {
  console.log("[e0e1][玩家信息] " + message);
  if (typeof globalThis.__e0e1JsInjectionReport === "function") {
    globalThis.__e0e1JsInjectionReport(message);
  }
  return null;
}

// ── 定位界面与快照 ──

function e0e1FindSettingUi() {
  var game = e0e1ResolveGameWindow();
  var ins = game && game.UIManager && game.UIManager.ins;
  if (!ins || !ins.viewParams) return null;
  for (var key in ins.viewParams) {
    var param = ins.viewParams[key];
    if (!param || !param.showing || !param.ui) continue;
    var uiId = param.cfgId || (param.cfg && param.cfg.id);
    if (uiId === "Setting") return param.ui;
  }
  return null;
}

function e0e1SelfSnapshot(game) {
  var snapshot = (game && game.ROLE) || null;
  if (snapshot && snapshot.previewHide === undefined) {
    var stats = snapshot.stats && snapshot.stats.statistics;
    snapshot.previewHide = stats && typeof stats.get === "function" ? stats.get(94) || 0 : 0;
  }
  return snapshot;
}

async function e0e1DumpPlayerInfo() {
  var game = e0e1ResolveGameWindow();
  if (!game) return e0e1Fail("未找到 gameContext，游戏可能还没加载");
  var ui = e0e1FindSettingUi();
  if (!ui) return e0e1Fail("当前没有打开玩家信息界面（Setting）");
  var snapshot = ui.info;
  for (var attempt = 0; attempt < 16 && !snapshot && !ui.isSelf; attempt++) {
    await new Promise(function (resolve) { setTimeout(resolve, 250); });
    snapshot = ui.info;
  }
  if (!snapshot) snapshot = e0e1SelfSnapshot(game);
  if (!snapshot) return e0e1Fail("没拿到快照数据（info 为空且不是本人界面）");
  return e0e1Emit(await e0e1BuildDump(snapshot, ui.isSelf));
}

// ── 安装 / 卸载 ──

function e0e1Expose(name, value) {
  globalThis[name] = value;
  try {
    var game = e0e1ResolveGameWindow();
    if (game && game !== globalThis) game[name] = value;
  } catch (error) {}
}

async function e0e1Install() {
  e0e1Expose("dumpPlayerInfo", function () {
    return e0e1DumpPlayerInfo();
  });
  e0e1Expose("dumpPlayerInfoText", function () {
    return e0e1DumpPlayerInfoText();
  });
  if (globalThis.__playerInfoAutoDump === undefined || globalThis.__playerInfoAutoDump === null) {
    globalThis.__playerInfoAutoDump = true;
  }

  var game = e0e1ResolveGameWindow();
  for (var attempt = 0; attempt < 16 && !game; attempt++) {
    await new Promise(function (resolve) { setTimeout(resolve, 250); });
    game = e0e1ResolveGameWindow();
  }
  if (!game) {
    globalThis.__playerInfoHooked = false;
    return { ok: false, message: "未找到 gameContext 里的 UIManager，请确认游戏已加载" };
  }
  e0e1Expose("dumpPlayerInfo", globalThis.dumpPlayerInfo);

  var proto = Object.getPrototypeOf(game.UIManager.ins);
  if (proto && typeof proto.open === "function" && !proto.__e0e1PlayerInfoHooked) {
    proto.__e0e1PlayerInfoOriginalOpen = proto.open;
    proto.open = function (cfg) {
      var viewParam = proto.__e0e1PlayerInfoOriginalOpen.apply(this, arguments);
      try {
        var uiId = (cfg && (cfg.id || cfg.cfgId)) || "";
        if (uiId === "Setting" && viewParam) {
          var wait = viewParam.waitAfterOpen;
          (wait && typeof wait.then === "function" ? wait : Promise.resolve()).then(function () {
            if (!globalThis.__playerInfoAutoDump) return null;
            return e0e1DumpPlayerInfo();
          }).catch(function (error) {});
        }
      } catch (error) {}
      return viewParam;
    };
    proto.__e0e1PlayerInfoHooked = true;
  }
  globalThis.__playerInfoHooked = true;

  if (e0e1FindSettingUi()) {
    await e0e1DumpPlayerInfo();
    return { ok: true, message: "已挂载钩子并导出当前玩家信息" };
  }
  return { ok: true, message: "已挂载 UIManager.open 钩子，打开玩家信息界面时自动导出；也可手动 dumpPlayerInfo()" };
}

function e0e1Uninstall() {
  globalThis.__playerInfoAutoDump = false;
  var game = e0e1ResolveGameWindow();
  if (game && game.UIManager && game.UIManager.ins) {
    var proto = Object.getPrototypeOf(game.UIManager.ins);
    if (proto && proto.__e0e1PlayerInfoHooked && typeof proto.__e0e1PlayerInfoOriginalOpen === "function") {
      proto.open = proto.__e0e1PlayerInfoOriginalOpen;
      delete proto.__e0e1PlayerInfoOriginalOpen;
      delete proto.__e0e1PlayerInfoHooked;
    }
  }
  globalThis.__playerInfoHooked = false;
  return { ok: true, message: "已取消玩家信息自动导出" };
}

// 双模式：长期脚本模式注册控制器，否则（once / 手动注入）直接执行一次
if (typeof globalThis.__e0e1RegisterRuntimeToggle === "function") {
  var e0e1PlayerEnabled = false;
  globalThis.__e0e1RegisterRuntimeToggle({
    async enable() {
      var result = await e0e1Install();
      e0e1PlayerEnabled = !!result.ok;
      return { ok: true, enabled: e0e1PlayerEnabled, message: result.message || "玩家信息导出已启用", log: e0e1LastReport };
    },
    async disable() {
      var result = e0e1Uninstall();
      e0e1PlayerEnabled = false;
      return { ok: true, enabled: false, message: result.message || "已取消", log: "" };
    },
    status() {
      return {
        ok: true,
        enabled: e0e1PlayerEnabled,
        message: e0e1PlayerEnabled ? "玩家信息导出已启用" : "玩家信息导出未启用",
        log: e0e1LastReport
      };
    }
  });
} else {
  var e0e1PlayerResult = await e0e1Install();
  console.log("[e0e1][玩家信息] " + e0e1PlayerResult.message);
  // 已经导出过就别再覆盖上报内容，否则只能看到状态消息
  if (!e0e1LastReport && typeof globalThis.__e0e1JsInjectionReport === "function") {
    globalThis.__e0e1JsInjectionReport(e0e1PlayerResult.message);
  }
}
