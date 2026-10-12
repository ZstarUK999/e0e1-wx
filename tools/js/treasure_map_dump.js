// ==UserScript==
// @name 摸金行动·地图数据导出
// @description 读取 globalThis.TREASURE 的全量地图缓存，打印每层格子的类型与状态（含尚未探索、被迷雾遮住的格子），并挂 globalThis.dumpTreasureMap() 供随时手动调用。
// @match *
// @run-at document-start
// @e0e1-mode once
// ==/UserScript==

// 说明：本脚本以语句形式直接执行（e0e1 的注入包装是 async 函数，可直接使用 await）。
// 数据来源：server-data.ts 暴露的 globalThis.TREASURE（GDTreasure / TreasureDataView）。
//   TREASURE.room.layers: Map<layerId, GDTreasureRoomLayer{rows, cols, cells}>
//   cells: Map<cellId+1, GDTreasureRoomCell{status, cellType, cfgId, lockData, rewards, mirrorRole}>
// 格子下标换算与游戏一致：index = x * cols + y，取 cells.get(index + 1)。

var E0E1_ROOM_TYPE = {
  0: "STARTROOM", 1: "COMBATROOM", 2: "ELITEROOM", 3: "BOSSROOM", 4: "KEYROOM",
  5: "BOXROOM", 6: "BIGBOXROOM", 7: "LOCKBOX", 8: "UPPERFLOOR", 9: "LOWERFLOOR",
  10: "NONEROOM", 11: "PKROOM", 12: "PRIZEROOM"
};

// 缩写用于 ASCII 地图，便于一眼扫出宝箱 / Boss / 上下楼层。
var E0E1_ABBREV = {
  0: "ST", 1: "CB", 2: "EL", 3: "BS", 4: "KY", 5: "BX", 6: "GB",
  7: "LK", 8: "UP", 9: "DN", 10: "--", 11: "PK", 12: "PZ"
};

var E0E1_STATUS = { 0: "init", 1: "active", 2: "finish" };
var E0E1_STATUS_MARK = { 0: ".", 1: "*", 2: "#" };

function e0e1CellTypeName(type) {
  return E0E1_ROOM_TYPE[type] || ("UNKNOWN_" + type);
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

function e0e1ResolveTreasure() {
  try {
    var game = e0e1ResolveGameWindow();
    if (game && game.TREASURE) return game.TREASURE;
    if (game && game.SERVER_DATA && game.SERVER_DATA.treasure) return game.SERVER_DATA.treasure;
  } catch (error) {}
  return null;
}

// 复刻 TreasureActionModule.getNeighborStatus / hasAdjacentFinishedCell / getCellVisualState，
// 用于标注"游戏当前真正显示成什么样"，与真实 cellType 对照即可看出迷雾遮了什么。
function e0e1NeighborStatus(layer, row, col) {
  var rows = layer.rows || 0;
  var cols = layer.cols || 0;
  if (row < 0 || col < 0 || row >= rows || col >= cols) return null;
  var cell = layer.cells.get(row * cols + col + 1);
  return cell ? cell.status : null;
}

function e0e1HasAdjacentActive(layer, index) {
  var cols = layer.cols || 0;
  var rows = layer.rows || 0;
  if (cols <= 0 || rows <= 0) return false;
  var row = Math.floor(index / cols);
  var col = index % cols;
  var around = [
    e0e1NeighborStatus(layer, row, col - 1),
    e0e1NeighborStatus(layer, row, col + 1),
    e0e1NeighborStatus(layer, row - 1, col),
    e0e1NeighborStatus(layer, row + 1, col)
  ];
  for (var i = 0; i < around.length; i++) {
    if (around[i] === 1 || around[i] === 2) return true;
  }
  return false;
}

function e0e1VisualState(cell, layer, index) {
  if (!cell) return "UNKNOWN";
  if (cell.status === 2) {
    return cell.cellType === 8 || cell.cellType === 9 ? "READY_TO_INTERACT" : "EXPLORED";
  }
  if (cell.status === 1) return "READY_TO_INTERACT";
  return e0e1HasAdjacentActive(layer, index) ? "EXPLOREABLE" : "UNKNOWN";
}

function e0e1ReadCell(rawCell, layer, index) {
  return {
    index: index,
    x: Math.floor(index / (layer.cols || 1)),
    y: index % (layer.cols || 1),
    status: rawCell.status,
    statusName: E0E1_STATUS[rawCell.status] || String(rawCell.status),
    cellType: rawCell.cellType,
    cellTypeName: e0e1CellTypeName(rawCell.cellType),
    cfgId: rawCell.cfgId,
    visualState: e0e1VisualState(rawCell, layer, index),
    lockData: Array.isArray(rawCell.lockData) ? rawCell.lockData.slice(0, 8) : [],
    rewardCount: rawCell.rewards && rawCell.rewards.length ? rawCell.rewards.length : 0,
    hasMirrorRole: !!rawCell.mirrorRole
  };
}

function e0e1ReadLayer(layerId, layer) {
  var rows = layer.rows || 0;
  var cols = layer.cols || 0;
  var cells = [];
  var grid = [];
  // 与 ui-treasure-action-map.updateRoomCells 保持一致的遍历顺序：x < cols，y < rows，index = x * cols + y。
  for (var x = 0; x < cols; x++) {
    var line = [];
    for (var y = 0; y < rows; y++) {
      var index = x * cols + y;
      var rawCell = layer.cells.get(index + 1);
      if (!rawCell) {
        line.push(" ?? ");
        continue;
      }
      var cell = e0e1ReadCell(rawCell, layer, index);
      cells.push(cell);
      line.push((E0E1_ABBREV[cell.cellType] || "??") + E0E1_STATUS_MARK[cell.status] + (cell.visualState === "UNKNOWN" ? "~" : " "));
    }
    grid.push(line.join(" "));
  }
  return {
    layerId: layerId,
    rows: rows,
    cols: cols,
    cellCount: cells.length,
    ascii: grid,
    cells: cells
  };
}

function e0e1BuildDump(treasure) {
  var room = treasure.room || {};
  var layers = [];
  var layerIds = [];
  if (room.layers && typeof room.layers.forEach === "function") {
    room.layers.forEach(function (layer, layerId) {
      layerIds.push(layerId);
      layers.push(e0e1ReadLayer(layerId, layer));
    });
  }
  var members = [];
  if (treasure.members && typeof treasure.members.forEach === "function") {
    treasure.members.forEach(function (member, roleId) {
      members.push({
        roleId: roleId,
        curLayer: member.curLayer,
        activeLayer: member.activeLayer,
        lastSite: Array.isArray(member.lastSite) ? member.lastSite.slice(0, 4) : [],
        score: member.score,
        energy: member.energy,
        currentPenalty: !!member.currentPenalty,
        autoExplore: !!member.autoExplore
      });
    });
  }
  return {
    title: "摸金行动地图数据",
    dumpedAt: new Date().toISOString(),
    treasureId: treasure.id,
    state: treasure.state,
    targetId: treasure.targetId,
    score: treasure.score,
    layerIds: layerIds,
    members: members,
    layers: layers
  };
}

function e0e1RenderText(dump) {
  var lines = [];
  lines.push("===== 摸金行动地图 " + dump.dumpedAt + " =====");
  lines.push("treasureId=" + dump.treasureId + " state=" + dump.state + " targetId=" + dump.targetId + " score=" + dump.score);
  lines.push("层: " + JSON.stringify(dump.layerIds));
  if (dump.members.length) {
    lines.push("成员: " + dump.members.map(function (m) {
      return m.roleId + "(L" + m.curLayer + ",site" + JSON.stringify(m.lastSite) + ",score" + m.score + ",能量" + m.energy + (m.autoExplore ? ",自动探索" : "") + (m.currentPenalty ? ",惩罚中" : "") + ")";
    }).join(" "));
  }
  if (!dump.layers.length) {
    lines.push("[未进入摸金场景，TREASURE.room 为空]");
    return lines.join("\n");
  }
  dump.layers.forEach(function (layer) {
    lines.push("");
    lines.push("--- 第 " + layer.layerId + " 层  " + layer.cols + "x" + layer.rows + "  格子数=" + layer.cellCount + " ---");
    lines.push("  y→ " + Array.apply(null, Array(layer.rows)).map(function (_, i) { return String(i).padStart(3, " "); }).join(" "));
    layer.ascii.forEach(function (line, x) { lines.push("x=" + x + " | " + line); });
    lines.push("图例: 类型缩写(ST起点 CB普通 EL精英 BSBOSS KY钥匙 BX宝箱 GB大宝箱 LK锁箱 UP上楼 DN下楼 --空 PK玩家 PZ转盘) + 状态(.未探索 *已揭示 #已完成) + ~(被迷雾遮住)");
  });
  return lines.join("\n");
}

// runtime_toggle 模式下没有 __e0e1JsInjectionReport 桥接，日志只能靠控制器返回值带出去，
// 这里缓存最近一次导出文本（与 once 模式的 12000 字符上限保持一致）。
var e0e1LastReport = "";

function e0e1Emit(dump) {
  var text = e0e1RenderText(dump);
  e0e1LastReport = text.slice(0, 12000);
  console.log("[e0e1][摸金地图]\n" + text);
  console.log("[e0e1][摸金地图] 完整数据", dump);
  if (typeof globalThis.__e0e1JsInjectionReport === "function") {
    globalThis.__e0e1JsInjectionReport(text);
  }
  return dump;
}

// 安装：暴露 dumpTreasureMap()，给 TreasureDataView.setValue 挂可选自动导出，并立即导出一次。
async function e0e1Install() {
  globalThis.dumpTreasureMap = function () {
    var current = e0e1ResolveTreasure();
    if (!current) {
      console.log("[e0e1][摸金地图] 当前没有 TREASURE 数据");
      return null;
    }
    return e0e1Emit(e0e1BuildDump(current));
  };
  if (globalThis.__treasureMapAutoDump === undefined || globalThis.__treasureMapAutoDump === null) {
    globalThis.__treasureMapAutoDump = false;
  }

  // 等待 TREASURE 就绪（登录后才由 server-data.createServerData 创建）。
  // CDP Runtime.evaluate 超时是 10s，这里最多等 5s。
  var treasure = null;
  for (var attempt = 0; attempt < 20 && !treasure; attempt++) {
    treasure = e0e1ResolveTreasure();
    if (!treasure) {
      await new Promise(function (resolve) { setTimeout(resolve, 250); });
    }
  }

  if (!treasure) {
    globalThis.__treasureHooked = false;
    return { ok: false, message: "未找到 gameContext 里的 TREASURE，可能尚未登录或游戏未加载" };
  }

  try {
    var proto = Object.getPrototypeOf(treasure);
    if (proto && typeof proto.setValue === "function" && !proto.__e0e1TreasureHooked) {
      proto.__e0e1TreasureOriginalSetValue = proto.setValue;
      proto.setValue = function (value) {
        var result = proto.__e0e1TreasureOriginalSetValue.call(this, value);
        if (globalThis.__treasureMapAutoDump) {
          try {
            e0e1Emit(e0e1BuildDump(this));
          } catch (error) {}
        }
        return result;
      };
      proto.__e0e1TreasureHooked = true;
    }
  } catch (error) {}
  globalThis.__treasureHooked = true;

  e0e1Emit(e0e1BuildDump(treasure));
  return { ok: true, message: "摸金地图已导出；控制台可随时 dumpTreasureMap()，__treasureMapAutoDump=true 开启自动导出" };
}

// 卸载：还原 setValue，关掉自动导出。
function e0e1Uninstall() {
  globalThis.__treasureMapAutoDump = false;
  var treasure = e0e1ResolveTreasure();
  if (treasure) {
    var proto = Object.getPrototypeOf(treasure);
    if (proto && proto.__e0e1TreasureHooked && typeof proto.__e0e1TreasureOriginalSetValue === "function") {
      proto.setValue = proto.__e0e1TreasureOriginalSetValue;
      delete proto.__e0e1TreasureOriginalSetValue;
      delete proto.__e0e1TreasureHooked;
    }
  }
  globalThis.__treasureHooked = false;
  return { ok: true, message: "已取消摸金地图自动导出" };
}

// 双模式：长期脚本模式注册控制器，否则（once / 手动注入）直接执行一次。
if (typeof globalThis.__e0e1RegisterRuntimeToggle === "function") {
  var e0e1TreasureEnabled = false;
  globalThis.__e0e1RegisterRuntimeToggle({
    async enable() {
      var result = await e0e1Install();
      e0e1TreasureEnabled = !!result.ok;
      return {
        ok: true,
        enabled: e0e1TreasureEnabled,
        message: result.message || "摸金地图导出已启用",
        log: e0e1LastReport
      };
    },
    async disable() {
      var result = e0e1Uninstall();
      e0e1TreasureEnabled = false;
      return { ok: true, enabled: false, message: result.message || "已取消", log: "" };
    },
    status() {
      return {
        ok: true,
        enabled: e0e1TreasureEnabled,
        message: e0e1TreasureEnabled ? "摸金地图导出已启用" : "摸金地图导出未启用",
        log: e0e1LastReport
      };
    }
  });
} else {
  var e0e1TreasureResult = await e0e1Install();
  console.log("[e0e1][摸金地图] " + e0e1TreasureResult.message);
  if (typeof globalThis.__e0e1JsInjectionReport === "function") {
    globalThis.__e0e1JsInjectionReport(e0e1TreasureResult.message);
  }
}
