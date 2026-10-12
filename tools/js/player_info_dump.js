// ==UserScript==
// @name 玩家信息导出
// @description 打开玩家信息界面（Setting / setting_ui）时，按界面显示方式解析该玩家 GDRoleSnap 快照（天书/三尸/脸谱/鬼仆阵法/法器），输出可读文本；含被对方隐藏的部分。注入后可手动调用 dumpPlayerInfo()。
// @match *
// @run-at document-start
// @e0e1-mode once
// ==/UserScript//

// 说明：本脚本以语句形式直接执行（e0e1 的注入包装是 async 函数，可直接使用 await）。
// 数据来源：UISetting.onOpen → RoleService.getRolePreviewInfo → resp.preview（GDRoleSnap，game.js:39868）
// 名称解析：System.import("chunks:///_virtual/configs.ts") 取配置表，用 getById 把 ID 翻成名字。
// 工具默认注入到 top 上下文，游戏在 name="gameContext" 的 iframe 里，需要跨进去拿全局。

// EPreviewHideType（game.js:37382）
var E0E1_HIDE_NAMES = { 0: "天书", 1: "三尸", 2: "脸谱", 3: "鬼仆阵法", 4: "法器" };

// 各分区字段 → 用于翻译 ID 的配置表（均导出自 configs.ts，game.js:30096 起）
var E0E1_SECTIONS = [
  {
    name: "天书",
    fields: [
      { field: "skillLevel", cfg: "SkillBookCfg", kind: "level" },
      { field: "skillCombineLevel", cfg: "RareskillCombCfg", kind: "level" },
      { field: "equipSkill", cfg: "EvolutionSkillCfg", kind: "level" },
      { field: "extEquipSkill", cfg: "EvolutionSkillCfg", kind: "level" },
      { field: "epicLevel", cfg: "SkillBookCfg", kind: "level" },
      { field: "epicAwakening", cfg: "SkillBookCfg", kind: "level" }
    ]
  },
  {
    name: "三尸",
    fields: [
      { field: "desirePlan", cfg: "DesireCfg", kind: "obj" },
      { field: "allDesirePlan", cfg: "DesireCfg", kind: "obj" }
    ]
  },
  {
    name: "脸谱",
    fields: [
      { field: "equipment", cfg: "EquipmentCfg", kind: "equip" },
      { field: "equipmentSuit", cfg: "EquipmentSuitCfg", kind: "level" },
      { field: "equipmentPlanSkill", cfg: "SkillBookCfg", kind: "level" }
    ]
  },
  {
    name: "鬼仆阵法",
    fields: [
      { field: "pet", cfg: "PetCfg", kind: "pet" },
      { field: "formationPetInfo", cfg: "PetCfg", kind: "raw" },
      { field: "formationPetSkill", cfg: "PetSkillCfg", kind: "level" }
    ]
  },
  {
    name: "法器",
    fields: [
      { field: "magic", cfg: "MagicArtifactBaseCfg", kind: "raw" }
    ]
  },
  {
    name: "其他",
    fields: [
      { field: "attribute", cfg: "AttrCfg", kind: "raw" },
      { field: "achieve", cfg: "AchieveCfg", kind: "raw" },
      { field: "fashion", cfg: "FashionCfg", kind: "raw" },
      { field: "unlockModuleIds", cfg: null, kind: "module" }
    ]
  }
];

// ModuleType（game.js:30269 起），只列玩家信息里常见的几个
var E0E1_MODULE_NAMES = {
  1: "关卡", 2: "属性成长", 3: "技能", 4: "招募", 7: "图鉴", 9: "鬼仆", 10: "阴司",
  16: "心愿", 18: "百鬼夜行", 23: "脸谱", 25: "摸金行动", 26: "好友", 27: "组队",
  30: "跨服", 31: "赛季竞技", 33: "走阴", 34: "斗法", 36: "法器", 38: "赛季"
};

var E0E1_BASE_FIELDS = [
  ["id", "角色ID"], ["name", "昵称"], ["sid", "服ID"], ["sName", "服务器"],
  ["level", "等级"], ["fightPower", "战力"], ["maxFightPower", "最高战力"],
  ["heroId", "主角ID"], ["legionId", "阴司ID"], ["legionName", "阴司"],
  ["chargeTotal", "累计充值"], ["stageWave", "关卡波次"], ["loginOutAt", "最后登出"]
];

// ── 跨上下文：工具注入到 top，游戏在 name="gameContext" 的 iframe 里 ──

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

// ── 配置表：把 ID 翻成人能看的名字 ──

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
      var loaded = loader.import("chunks:///_virtual/configs.ts");
      e0e1CfgModule = await Promise.race([loaded, timeout]) || null;
    }
  } catch (error) {
    e0e1CfgModule = null;
  }
  return e0e1CfgModule;
}

function e0e1CfgRow(cfgName, id) {
  if (!cfgName || id === undefined || id === null) return null;
  try {
    var table = e0e1CfgModule && e0e1CfgModule[cfgName];
    if (!table || typeof table.getById !== "function") return null;
    return table.getById(Number(id)) || null;
  } catch (error) {
    return null;
  }
}

function e0e1CfgName(cfgName, id) {
  var row = e0e1CfgRow(cfgName, id);
  if (!row) return null;
  return row.name || row.Name || row.cfgName || null;
}

// ── 渲染小工具 ──

function e0e1KindOf(value) {
  return Object.prototype.toString.call(value);
}

function e0e1IsMap(value) {
  return !!value && e0e1KindOf(value) === "[object Map]";
}

function e0e1Name(cfgName, id) {
  var name = e0e1CfgName(cfgName, id);
  return name || ("ID" + id + (e0e1CfgModule ? "" : ""));
}

function e0e1Attrs(obj, keys) {
  var parts = [];
  keys.forEach(function (key) {
    var value = obj && obj[key];
    if (value === undefined || value === null || value === 0 || value === "") return;
    var label = { level: "等级", lv: "等级", quality: "品质", star: "星", step: "阶", num: "数量", count: "数量" }[key] || key;
    parts.push(label + value);
  });
  return parts;
}

// 把 Map/对象按 kind 翻成可读行
function e0e1RenderField(entry, snapshot) {
  var cfg = entry.cfg;
  var value = snapshot[entry.field];
  if (value === undefined || value === null) return [];
  if (e0e1IsMap(value) && value.size === 0) return [];
  if (Array.isArray(value) && value.length === 0) return [];

  var lines = [];

  if (e0e1IsMap(value)) {
    value.forEach(function (item, key) {
      if (lines.length >= 40) return;
      if (entry.kind === "level") {
        lines.push("· " + e0e1Name(cfg, key) + " Lv." + item);
        return;
      }
      if (entry.kind === "equip") {
        // 脸谱：equipment 里存 cfgId/品质，等级在 equipmentLevel 里按位取
        var levelMap = snapshot.equipmentLevel;
        var level = e0e1IsMap(levelMap) ? levelMap.get(key) : undefined;
        var row = e0e1CfgRow(cfg, item && item.cfgId !== undefined ? item.cfgId : key);
        var parts = [e0e1Name(cfg, item && item.cfgId !== undefined ? item.cfgId : key)];
        if (level !== undefined && level !== null) parts.push("等级" + level);
        parts = parts.concat(e0e1Attrs(item, ["quality", "level", "lv", "star", "step"]));
        if (row && row.quality !== undefined && item && item.quality === undefined) parts.push("品质" + row.quality);
        lines.push("· " + parts.join(" "));
        return;
      }
      if (entry.kind === "obj") {
        if (item && typeof item === "object") {
          var head = e0e1Name(cfg, item.cfgId !== undefined ? item.cfgId : key);
          lines.push("· " + [head].concat(e0e1Attrs(item, ["level", "lv", "quality", "star", "step"])).join(" "));
        } else {
          lines.push("· " + e0e1Name(cfg, key) + " " + item);
        }
        return;
      }
      lines.push("· " + e0e1Name(cfg, key) + " " + JSON.stringify(item));
    });
    return lines;
  }

  if (Array.isArray(value) && entry.kind === "module") {
    lines.push("· 已解锁玩法: " + value.slice(0, 40).map(function (id) {
      return E0E1_MODULE_NAMES[id] || ("ID" + id);
    }).join("、"));
    return lines;
  }

  if (Array.isArray(value)) {
    value.slice(0, 20).forEach(function (item) {
      if (item && typeof item === "object" && item.cfgId !== undefined) {
        lines.push("· " + [e0e1Name(cfg, item.cfgId)].concat(e0e1Attrs(item, ["level", "lv", "quality", "star", "num"])).join(" "));
      } else {
        lines.push("· " + JSON.stringify(item));
      }
    });
    return lines;
  }

  if (typeof value === "object") {
    if (value.cfgId !== undefined) {
      lines.push("· " + [e0e1Name(cfg, value.cfgId)].concat(e0e1Attrs(value, ["level", "lv", "quality", "star"])).join(" "));
    } else {
      lines.push("· " + JSON.stringify(value).slice(0, 400));
    }
    return lines;
  }

  lines.push("· " + value);
  return lines;
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
  E0E1_SECTIONS.forEach(function (section) {
    var blocks = [];
    section.fields.forEach(function (entry) {
      var lines = e0e1RenderField(entry, snapshot);
      if (lines.length) blocks.push({ label: entry.field, lines: lines });
    });
    if (blocks.length) dump.sections.push({ name: section.name, blocks: blocks });
  });
  return dump;
}

function e0e1RenderText(dump) {
  var lines = [];
  lines.push("===== 玩家信息 " + dump.dumpedAt + " =====");
  lines.push(dump.base.map(function (pair) { return pair[0] + "=" + pair[1]; }).join("  "));
  lines.push("对方隐藏: " + (dump.hide.names.length ? dump.hide.names.join("、") + "（位掩码 " + dump.hide.raw + "）" : "无"));
  lines.push(dump.cfgReady ? "名称解析: 已加载配置表" : "名称解析: 未拿到配置表，仅显示 ID");
  lines.push("※ 下面各分区来自本地快照，不受对方隐藏设置影响");
  if (!dump.sections.length) {
    lines.push("[快照中没有可展示的数据]");
    return lines.join("\n");
  }
  dump.sections.forEach(function (section) {
    lines.push("");
    lines.push("── " + section.name + " ──");
    section.blocks.forEach(function (block) {
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

// ── 定位界面与快照 ──

function e0e1FindSettingUi() {
  var game = e0e1ResolveGameWindow();
  var manager = game && game.UIManager;
  var ins = manager && manager.ins;
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
  if (!game) {
    return e0e1Fail("未找到 gameContext，游戏可能还没加载");
  }
  var ui = e0e1FindSettingUi();
  if (!ui) {
    return e0e1Fail("当前没有打开玩家信息界面（Setting）");
  }
  // 他人信息是 getRolePreviewInfo 异步回来的，等一下
  var snapshot = ui.info;
  for (var attempt = 0; attempt < 16 && !snapshot && !ui.isSelf; attempt++) {
    await new Promise(function (resolve) { setTimeout(resolve, 250); });
    snapshot = ui.info;
  }
  if (!snapshot) snapshot = e0e1SelfSnapshot(game);
  if (!snapshot) {
    return e0e1Fail("没拿到快照数据（info 为空且不是本人界面）");
  }
  return e0e1Emit(await e0e1BuildDump(snapshot, ui.isSelf));
}

function e0e1Fail(message) {
  console.log("[e0e1][玩家信息] " + message);
  if (typeof globalThis.__e0e1JsInjectionReport === "function") {
    globalThis.__e0e1JsInjectionReport(message);
  }
  return null;
}

// ── 安装 / 卸载 ──

// 工具注入到 top 上下文，但 Console 可能停在 gameContext，两边都挂一份
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
  if (typeof globalThis.__e0e1JsInjectionReport === "function") {
    globalThis.__e0e1JsInjectionReport(e0e1PlayerResult.message);
  }
}
