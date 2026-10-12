// ==UserScript==
// @name 阴司成员导出
// @description 进入阴司界面时自动拉取并打印本阴司全部成员（含离线）；注入后可在控制台手动调用 dumpLegionMembers()。
// @match *
// @run-at document-start
// @e0e1-mode once
// ==/UserScript==

// 说明：本脚本以语句形式直接执行（e0e1 的注入包装是 async 函数，可直接使用 await）。
// 数据来源：LegionModule.legionInfo（LegionInfo，继承自 LegionPreview）
//   legionInfo.members: Map<roleId, LegionMemberInfo>
// 模块实例获取：阴司界面的 module getter 是 GET_MODULE(ModuleLocalType.LEGION)，
//   所以从 UIManager.ins.viewParams 里找到已打开的 Legion* 界面，取 ui.module 即可，无需碰模块注册表。

var E0E1_JOB = { 0: "none", 1: "leader", 2: "subLeader", 3: "elite", 9: "member" };
var E0E1_JOB_CN = { 0: "无", 1: "阎君", 2: "判官", 3: "拘魂使", 9: "成员" };

// 触发自动导出的界面；其余 Legion* 界面只用来顺手缓存模块实例。
var E0E1_DUMP_UI = { LegionUI: 1, LegionMainUI: 1 };
var E0E1_LEGION_UI = /^Legion/;

function e0e1JobName(job) {
  var cn = E0E1_JOB_CN[job];
  return (cn || E0E1_JOB[job] || ("job" + job)) + "(" + job + ")";
}

// 中文等全角字符按 2 个字符宽算，否则表格会错位。
function e0e1DisplayWidth(text) {
  var width = 0;
  for (var i = 0; i < text.length; i++) {
    var code = text.charCodeAt(i);
    width += (code > 0x1100 && (
      (code < 0x1160) || (code >= 0x2e80 && code < 0xa4d0) || (code >= 0xac00 && code < 0xd7a4) ||
      (code >= 0xf900 && code < 0xfb00) || (code >= 0xfe30 && code < 0xfe70) ||
      (code >= 0xff00 && code < 0xff61) || (code >= 0xffe0 && code < 0xffe7)
    )) ? 2 : 1;
  }
  return width;
}

function e0e1PadEnd(value, width) {
  var text = String(value == null ? "" : value);
  var pad = width - e0e1DisplayWidth(text);
  return pad > 0 ? text + new Array(pad + 1).join(" ") : text;
}

// 工具默认注入到 top 上下文（servicewechat.com），游戏跑在 name="gameContext" 的 iframe 里。
// 这里跨进 iframe 拿游戏的 window，避免依赖会变的 contextId。
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

function e0e1GetUiIns() {
  try {
    var game = e0e1ResolveGameWindow();
    var manager = game && game.UIManager;
    return (manager && manager.ins) || null;
  } catch (error) {
    return null;
  }
}

function e0e1UiId(viewParam) {
  if (!viewParam) return "";
  return String(viewParam.cfgId || (viewParam.cfg && viewParam.cfg.id) || "");
}

// 从已打开的阴司界面上取 LegionModule 单例。
function e0e1FindLegionModule(uiIns) {
  if (!uiIns || !uiIns.viewParams) return null;
  var params = uiIns.viewParams;
  for (var key in params) {
    var param = params[key];
    if (!param || !param.showing || !param.ui) continue;
    if (!E0E1_LEGION_UI.test(e0e1UiId(param))) continue;
    try {
      if (param.ui.module) return param.ui.module;
    } catch (error) {}
  }
  return null;
}

function e0e1ReadMember(member, roleId) {
  return {
    roleId: roleId != null ? roleId : member.id,
    name: member.name,
    level: member.level,
    server: member.sName || member.sId,
    fightPower: member.fightPower,
    maxFightPower: member.maxFightPower,
    job: member.job,
    jobName: E0E1_JOB[member.job] || String(member.job),
    contrib: member.contrib,
    contribDay: member.contribDay,
    isOnline: !!member.isOnline,
    lastOnlineTime: member.lastOnlineTime,
    joinTime: member.joinTime,
    passStageId: member.passStageId,
    legionName: member.legionName,
    chargeTotal: member.chargeTotal
  };
}

function e0e1ReadMembers(legionInfo) {
  var list = [];
  var members = legionInfo.members;
  if (members && typeof members.forEach === "function") {
    members.forEach(function (member, roleId) {
      list.push(e0e1ReadMember(member, roleId));
    });
  }
  list.sort(function (a, b) {
    if (a.isOnline !== b.isOnline) return a.isOnline ? -1 : 1;
    if (a.job !== b.job) return a.job - b.job;
    return a.joinTime - b.joinTime;
  });
  return list;
}

function e0e1ReadLegionHead(legionInfo) {
  return {
    legionId: legionInfo.id,
    name: legionInfo.name,
    server: legionInfo.sName || legionInfo.serverId,
    level: legionInfo.level,
    exp: legionInfo.exp,
    leaderId: legionInfo.leaderId,
    leaderName: legionInfo.leaderName,
    memberNum: legionInfo.memberNum,
    memberNumMax: legionInfo.memberNumMax,
    fightPower: legionInfo.fightPower,
    notice: legionInfo.notice
  };
}

function e0e1RenderText(dump) {
  var lines = [];
  lines.push("===== 阴司成员 " + dump.dumpedAt + " =====");
  if (!dump.inLegion) {
    lines.push("[尚未加入阴司]");
    return lines.join("\n");
  }
  var head = dump.legion;
  lines.push("阴司: " + head.name + "(id=" + head.legionId + ")  等级=" + head.level +
    "  服=" + head.server + "  人数=" + head.memberNum + "/" + head.memberNumMax +
    "  总战力=" + head.fightPower + "  阎君=" + head.leaderName + "(" + head.leaderId + ")");
  lines.push("成员总数: " + dump.memberCount + "  在线: " + dump.onlineCount);
  lines.push("");
  lines.push("  #  角色ID      昵称            等级  战力         职位         日贡献  总贡献  状态");
  dump.members.forEach(function (m, i) {
    lines.push(
      String(i + 1).padStart(3, " ") + "  " +
      e0e1PadEnd(m.roleId, 11) + " " +
      e0e1PadEnd(String(m.name || "").slice(0, 12), 14) +
      e0e1PadEnd(m.level, 5) +
      e0e1PadEnd(m.fightPower, 12) +
      e0e1PadEnd(e0e1JobName(m.job), 13) +
      String(m.contribDay).padStart(6, " ") + " " +
      String(m.contrib).padStart(7, " ") + "  " +
      (m.isOnline ? "在线" : "离线")
    );
  });
  return lines.join("\n");
}

// runtime_toggle 模式下没有 __e0e1JsInjectionReport 桥接，日志只能靠控制器返回值带出去，
// 这里缓存最近一次导出文本（与 once 模式的 12000 字符上限保持一致）。
var e0e1LastReport = "";

function e0e1Emit(dump) {
  var text = e0e1RenderText(dump);
  e0e1LastReport = text.slice(0, 12000);
  console.log("[e0e1][阴司成员]\n" + text);
  console.log("[e0e1][阴司成员] 完整数据", dump);
  if (typeof globalThis.__e0e1JsInjectionReport === "function") {
    globalThis.__e0e1JsInjectionReport(text);
  }
  return dump;
}

// force=true 时强制重新请求一次 getLegionInfo，否则优先用本地缓存（为空时才请求）。
async function e0e1DumpLegionMembers(force) {
  var uiIns = e0e1GetUiIns();
  var module = e0e1FindLegionModule(uiIns);
  if (!module) {
    var message = "未找到阴司模块，请先进入阴司界面（或当前不在阴司相关界面）";
    console.log("[e0e1][阴司成员] " + message);
    if (typeof globalThis.__e0e1JsInjectionReport === "function") {
      globalThis.__e0e1JsInjectionReport(message);
    }
    return null;
  }
  globalThis.__legionModule = module;

  var inLegion = module.hasLegion;
  if (inLegion === undefined || inLegion === null) {
    inLegion = !!(module.legionInfo && module.legionInfo.id);
  }
  if (!inLegion) {
    return e0e1Emit({ title: "阴司成员", dumpedAt: new Date().toISOString(), inLegion: false, memberCount: 0, onlineCount: 0, members: [] });
  }

  var legionInfo = module.legionInfo;
  var empty = !legionInfo || !legionInfo.members || !legionInfo.members.size;
  if ((force || empty) && typeof module.refreshMyLegionInfo === "function") {
    legionInfo = await module.refreshMyLegionInfo();
  }
  if (!legionInfo) {
    var fail = "拉取阴司信息失败";
    console.log("[e0e1][阴司成员] " + fail);
    if (typeof globalThis.__e0e1JsInjectionReport === "function") {
      globalThis.__e0e1JsInjectionReport(fail);
    }
    return null;
  }

  var members = e0e1ReadMembers(legionInfo);
  var onlineCount = members.filter(function (m) { return m.isOnline; }).length;
  return e0e1Emit({
    title: "阴司成员",
    dumpedAt: new Date().toISOString(),
    inLegion: true,
    legion: e0e1ReadLegionHead(legionInfo),
    memberCount: members.length,
    onlineCount: onlineCount,
    members: members
  });
}

// 安装钩子 + 暴露控制台工具函数；可重复调用，已装则跳过。
async function e0e1Install() {
  globalThis.dumpLegionMembers = function (force) {
    return e0e1DumpLegionMembers(!!force);
  };
  if (globalThis.__legionAutoDump === undefined || globalThis.__legionAutoDump === null) {
    globalThis.__legionAutoDump = true;
  }

  // 长期脚本模式会在 document-start 注入，此时 game 分包还没执行，需要等 UIManager 挂上来。
  var uiIns = e0e1GetUiIns();
  for (var attempt = 0; attempt < 24 && !uiIns; attempt++) {
    await new Promise(function (resolve) { setTimeout(resolve, 250); });
    uiIns = e0e1GetUiIns();
  }
  if (!uiIns) {
    globalThis.__legionHooked = false;
    return { ok: false, message: "未找到 gameContext 里的 UIManager（等待 6 秒仍未挂载），请确认游戏已加载" };
  }

  var uiProto = Object.getPrototypeOf(uiIns);
  if (uiProto && typeof uiProto.open === "function" && !uiProto.__e0e1LegionHooked) {
    uiProto.__e0e1LegionOriginalOpen = uiProto.open;
    uiProto.open = function (cfg) {
      var viewParam = uiProto.__e0e1LegionOriginalOpen.apply(this, arguments);
      try {
        var uiId = (cfg && (cfg.id || cfg.cfgId)) || "";
        if (E0E1_LEGION_UI.test(String(uiId)) && viewParam) {
          var wait = viewParam.waitAfterOpen;
          (wait && typeof wait.then === "function" ? wait : Promise.resolve()).then(function () {
            try {
              if (viewParam.ui && viewParam.ui.module) {
                globalThis.__legionModule = viewParam.ui.module;
              }
              if (globalThis.__legionAutoDump && E0E1_DUMP_UI[String(uiId)]) {
                return e0e1DumpLegionMembers(false);
              }
            } catch (error) {}
            return null;
          }).catch(function (error) {});
        }
      } catch (error) {}
      return viewParam;
    };
    uiProto.__e0e1LegionHooked = true;
  }
  globalThis.__legionHooked = true;

  // 阴司界面已经开着的话，立刻导出一次。
  var already = e0e1FindLegionModule(uiIns);
  if (already) {
    globalThis.__legionModule = already;
    await e0e1DumpLegionMembers(false);
    return { ok: true, message: "已挂载钩子并导出当前阴司成员" };
  }
  return { ok: true, message: "已挂载 UIManager.open 钩子，进入阴司界面时自动导出；也可手动 dumpLegionMembers()" };
}

// 卸载：还原 UIManager.open，清掉自动导出开关。
function e0e1Uninstall() {
  globalThis.__legionAutoDump = false;
  var uiIns = e0e1GetUiIns();
  if (uiIns) {
    var uiProto = Object.getPrototypeOf(uiIns);
    if (uiProto && uiProto.__e0e1LegionHooked && typeof uiProto.__e0e1LegionOriginalOpen === "function") {
      uiProto.open = uiProto.__e0e1LegionOriginalOpen;
      delete uiProto.__e0e1LegionOriginalOpen;
      delete uiProto.__e0e1LegionHooked;
    }
  }
  globalThis.__legionHooked = false;
  return { ok: true, message: "已取消阴司成员自动导出" };
}

// 双模式：长期脚本模式注册控制器，否则（once / 手动注入）直接执行一次。
if (typeof globalThis.__e0e1RegisterRuntimeToggle === "function") {
  var e0e1LegionEnabled = false;
  globalThis.__e0e1RegisterRuntimeToggle({
    async enable() {
      var result = await e0e1Install();
      e0e1LegionEnabled = !!result.ok;
      return {
        ok: true,
        enabled: e0e1LegionEnabled,
        message: result.message || "阴司成员导出已启用",
        log: e0e1LastReport
      };
    },
    async disable() {
      var result = e0e1Uninstall();
      e0e1LegionEnabled = false;
      return { ok: true, enabled: false, message: result.message || "已取消", log: "" };
    },
    status() {
      return {
        ok: true,
        enabled: e0e1LegionEnabled,
        message: e0e1LegionEnabled ? "阴司成员导出已启用" : "阴司成员导出未启用",
        log: e0e1LastReport
      };
    }
  });
} else {
  var e0e1LegionResult = await e0e1Install();
  console.log("[e0e1][阴司成员] " + e0e1LegionResult.message);
  if (typeof globalThis.__e0e1JsInjectionReport === "function") {
    globalThis.__e0e1JsInjectionReport(e0e1LegionResult.message);
  }
}
