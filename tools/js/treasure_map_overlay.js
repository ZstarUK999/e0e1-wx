// ==UserScript==
// @name 摸金地图标注
// @description 在摸金地图上给每个格子挂 Cocos Label，标出楼梯/大宝箱/小宝箱/锁箱/钥匙/转盘/战斗等，随层数与探索状态实时刷新（含未探索格子的真实类型）。
// @match *
// @run-at document-start
// @e0e1-mode runtime_toggle
// ==/UserScript//

// 说明：本脚本以语句形式直接执行（e0e1 的注入包装是 async 函数，可直接使用 await）。
//
// 重要：小游戏上下文里的 document 是 DOM shim（canvas 没有父节点、body 不在活动树、appendChild 静默失败），
//       所以不能用 DOM 覆盖层。这里改成往格子节点上挂 Cocos Label —— 位置天然对齐，不用做坐标换算。
//
// 注意：进入/退出摸金会重建 JS 上下文，once 模式会被清掉，所以用 runtime_toggle
//       （Page.addScriptToEvaluateOnNewDocument，每个新 document 自动重新注入）。
//       GUI 里要点「启用」而不是「注入」；CLI 用：
//       python tools/cdp_inject.py --port 62000 --toggle tools/js/treasure_map_overlay.js

// TreasureRoomType（game.js:30269）
var E0E1_CELL_LABELS = {
  0: { text: "起点", rgb: [200, 200, 200] },
  1: { text: "战斗", rgb: [255, 138, 128] },
  2: { text: "精英", rgb: [255, 171, 145] },
  3: { text: "BOSS", rgb: [255, 82, 82] },
  4: { text: "钥匙", rgb: [255, 224, 130] },
  5: { text: "小宝箱", rgb: [144, 202, 249] },
  6: { text: "大宝箱", rgb: [255, 204, 128] },
  7: { text: "锁箱", rgb: [224, 224, 224] },
  8: { text: "↑上楼", rgb: [185, 246, 202] },
  9: { text: "↓下楼", rgb: [185, 246, 202] },
  10: null,
  11: { text: "对决", rgb: [206, 147, 216] },
  12: { text: "转盘", rgb: [244, 143, 177] }
};

// CellVisualState（treasure-action-module）
var E0E1_STATE_TEXT = {
  UNKNOWN: "未探索",
  EXPLOREABLE: "可探索",
  READY_TO_INTERACT: "可交互",
  EXPLORED: "已完成"
};

var E0E1_TIMER = null;
var E0E1_LABEL_NODES = {};
var E0E1_NODE_CLASS = null;
var E0E1_LABEL_CLASS = null;

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

function e0e1FindMapUi() {
  var game = e0e1ResolveGameWindow();
  var ins = game && game.UIManager && game.UIManager.ins;
  if (!ins || !ins.viewParams) return null;
  for (var key in ins.viewParams) {
    var param = ins.viewParams[key];
    if (!param || !param.showing || !param.ui) continue;
    var uiId = param.cfgId || (param.cfg && param.cfg.id);
    if (uiId === "TreasureActionMapUI") return param.ui;
  }
  return null;
}

// ── 从场景里借 Node / Label 类（小游戏没有全局 cc）──

function e0e1LooksLikeLabel(comp) {
  return !!comp &&
    typeof comp.string === "string" &&
    comp.fontSize !== undefined &&
    comp.lineHeight !== undefined;
}

function e0e1FindClasses(game) {
  if (E0E1_NODE_CLASS && E0E1_LABEL_CLASS) return true;
  var ins = game && game.UIManager && game.UIManager.ins;
  var root = ins && ins.root;
  if (!root) return false;
  if (!E0E1_NODE_CLASS && root.constructor) E0E1_NODE_CLASS = root.constructor;

  var queue = [root];
  var visited = 0;
  while (queue.length && visited < 600) {
    var node = queue.shift();
    visited++;
    var comps = node.components || [];
    for (var i = 0; i < comps.length; i++) {
      if (!E0E1_LABEL_CLASS && e0e1LooksLikeLabel(comps[i])) {
        E0E1_LABEL_CLASS = comps[i].constructor;
        return !!E0E1_NODE_CLASS;
      }
    }
    var children = node.children || [];
    for (var j = 0; j < children.length; j++) queue.push(children[j]);
  }
  return !!(E0E1_NODE_CLASS && E0E1_LABEL_CLASS);
}

// 节点上找房间格子组件（TreasureActionRoomCell 有 roomType / _visualState）
function e0e1CellOf(node) {
  var comps = node.components || [];
  for (var i = 0; i < comps.length; i++) {
    var comp = comps[i];
    if (comp && comp.roomType !== undefined) return comp;
  }
  return null;
}

function e0e1MakeLabel(cellNode, text, rgb) {
  var child = new E0E1_NODE_CLASS("__e0e1CellLabel");
  try {
    if (cellNode.layer !== undefined) child.layer = cellNode.layer;
  } catch (error) {}
  cellNode.addChild(child);
  try {
    child.setSiblingIndex((cellNode.children || []).length - 1);
  } catch (error) {}
  var label = child.addComponent(E0E1_LABEL_CLASS);
  label.string = text;
  label.fontSize = 13;
  label.lineHeight = 16;
  try {
    label.horizontalAlign = 1;
    label.verticalAlign = 1;
    label.overflow = 1;
    label.enableWrapText = false;
  } catch (error) {}
  try {
    label.color.set(rgb[0], rgb[1], rgb[2], 255);
  } catch (error) {}
  try {
    label.enableOutline = true;
    label.outlineWidth = 2;
    label.outlineColor.set(0, 0, 0, 255);
  } catch (error) {}
  return child;
}

function e0e1ClearLabels() {
  for (var key in E0E1_LABEL_NODES) {
    var node = E0E1_LABEL_NODES[key];
    try {
      if (node && node.isValid) node.destroy();
    } catch (error) {}
    delete E0E1_LABEL_NODES[key];
  }
}

function e0e1Update() {
  var game = e0e1ResolveGameWindow();
  if (!game) return;
  if (!e0e1FindClasses(game)) return;

  var ui = e0e1FindMapUi();
  var root = ui && ui.view && ui.view.node_room_root;
  if (!ui || !root) {
    if (Object.keys(E0E1_LABEL_NODES).length) e0e1ClearLabels();
    return;
  }

  var alive = {};
  var children = root.children || [];
  for (var i = 0; i < children.length; i++) {
    var node = children[i];
    if (!node) continue;
    var cell = e0e1CellOf(node);
    if (!cell) continue;
    var style = E0E1_CELL_LABELS[cell.roomType];
    if (!style) continue;

    var key = String(node.uuid || node.name || i);
    alive[key] = true;
    var state = E0E1_STATE_TEXT[cell._visualState] || "";
    var text = state ? style.text + "·" + state : style.text;

    var labelNode = E0E1_LABEL_NODES[key];
    if (!labelNode || !labelNode.isValid) {
      E0E1_LABEL_NODES[key] = e0e1MakeLabel(node, text, style.rgb);
      continue;
    }
    try {
      var label = labelNode.getComponent(E0E1_LABEL_CLASS);
      if (label && label.string !== text) label.string = text;
    } catch (error) {}
  }

  for (var existing in E0E1_LABEL_NODES) {
    if (alive[existing]) continue;
    var stale = E0E1_LABEL_NODES[existing];
    try {
      if (stale && stale.isValid) stale.destroy();
    } catch (error) {}
    delete E0E1_LABEL_NODES[existing];
  }
}

function e0e1Tick() {
  // 单次异常不能把定时器打死
  try {
    e0e1Update();
  } catch (error) {
    console.log("[e0e1][摸金标注] update error: " + error);
  }
}

function e0e1Start() {
  var game = e0e1ResolveGameWindow();
  if (!game) return "未找到 gameContext";
  if (!e0e1FindClasses(game)) return "没拿到 Node/Label 类（游戏还没加载完）";
  if (E0E1_TIMER) return "已在运行";
  E0E1_TIMER = game.setInterval(e0e1Tick, 300);
  e0e1Tick();
  return "摸金地图标注已开启";
}

function e0e1Stop() {
  var game = e0e1ResolveGameWindow();
  if (E0E1_TIMER && game) game.clearInterval(E0E1_TIMER);
  E0E1_TIMER = null;
  e0e1ClearLabels();
  return "摸金地图标注已关闭";
}

function e0e1Status() {
  return {
    running: !!E0E1_TIMER,
    labels: Object.keys(E0E1_LABEL_NODES).length,
    hasNodeClass: !!E0E1_NODE_CLASS,
    hasLabelClass: !!E0E1_LABEL_CLASS
  };
}

// ── 安装 ──

function e0e1Expose(name, value) {
  globalThis[name] = value;
  try {
    var game = e0e1ResolveGameWindow();
    if (game && game !== globalThis) game[name] = value;
  } catch (error) {}
}

async function e0e1Install() {
  e0e1Expose("treasureMapOverlayOn", e0e1Start);
  e0e1Expose("treasureMapOverlayOff", e0e1Stop);
  e0e1Expose("treasureMapOverlayStatus", e0e1Status);

  var game = e0e1ResolveGameWindow();
  for (var attempt = 0; attempt < 16 && !game; attempt++) {
    await new Promise(function (resolve) { setTimeout(resolve, 250); });
    game = e0e1ResolveGameWindow();
  }
  if (!game) return { ok: false, message: "未找到 gameContext，请确认游戏已加载" };
  e0e1Expose("treasureMapOverlayOn", e0e1Start);
  e0e1Expose("treasureMapOverlayOff", e0e1Stop);
  e0e1Expose("treasureMapOverlayStatus", e0e1Status);

  if (e0e1FindMapUi()) {
    e0e1Start();
    return { ok: true, message: "摸金地图标注已开启（当前已在地图界面）" };
  }
  var result = e0e1Start();
  return { ok: true, message: result + "，进入摸金地图后自动标注；treasureMapOverlayOff() 可关闭" };
}

function e0e1Uninstall() {
  e0e1Stop();
  return { ok: true, message: "已取消摸金地图标注" };
}

// 双模式：长期脚本模式注册控制器，否则（once / 手动注入）直接执行一次
if (typeof globalThis.__e0e1RegisterRuntimeToggle === "function") {
  var e0e1OverlayEnabled = false;
  globalThis.__e0e1RegisterRuntimeToggle({
    async enable() {
      var result = await e0e1Install();
      e0e1OverlayEnabled = !!result.ok;
      return { ok: true, enabled: e0e1OverlayEnabled, message: result.message || "摸金地图标注已启用", log: "" };
    },
    async disable() {
      var result = e0e1Uninstall();
      e0e1OverlayEnabled = false;
      return { ok: true, enabled: false, message: result.message || "已取消", log: "" };
    },
    status() {
      return {
        ok: true,
        enabled: e0e1OverlayEnabled,
        message: e0e1OverlayEnabled ? "摸金地图标注已启用" : "摸金地图标注未启用",
        log: ""
      };
    }
  });
} else {
  var e0e1OverlayResult = await e0e1Install();
  console.log("[e0e1][摸金标注] " + e0e1OverlayResult.message);
  if (typeof globalThis.__e0e1JsInjectionReport === "function") {
    globalThis.__e0e1JsInjectionReport(e0e1OverlayResult.message);
  }
}
