# e0e1-wx · 工作手册

面向后续会话的上下文文档。目标小程序/小游戏：**遗弃之地**
- 主体包：`wx6d5e82c174635a48/65`（小游戏，Cocos Creator 3.8.5）
- 插件包：`wxaed5ace05d92b218/43`

---

## 1. 工程定位

`e0e1-wx` 是一套 **微信小程序/小游戏逆向分析工作台**，能力分三层：

| 层 | 目录 | 作用 |
|---|---|---|
| 抓包与解包 | `package/decompiler`、`package/monitor` | 抓取小程序包、反编译 wxapkg、输出可读 JS |
| 调试注入 | `package/devtools`、`package/js_injection` | Frida hook WMPF → 建立 CDP 服务 → 向页面注入 JS |
| 分析工具 | `tools/` | 探针脚本、注入脚本、静态审计脚本 |

入口：`python main.py`（GUI）。反编译产物在 `output/`。

---

## 2. 调试链路

```
微信 → WeChatAppEx.exe(WMPF) --frida hook--> 开放调试
     --回连--> 9421(工具侧监听) --转发--> CDP WebSocket 62000~65535
```

- `DEBUG_PORT = 9421`（小程序回连）
- `CDP_PORT_START/END = 62000 / 65535`（工具对外提供 CDP）
- 端点格式：`ws://127.0.0.1:<port>`，**裸 WebSocket，没有 `/json/list` 等 HTTP 发现接口**

### 建立会话的正确顺序

1. `python main.py`
2. GUI → **DevTools CDP** → 开始调试
3. 小程序内打开调试开关 → **重启小程序**
4. 等状态 `frida / miniapp / devtools` 全绿、`status=running`
5. 之后才能用 CDP 命令（`Runtime.evaluate`）

**判活**：`1+1` 有响应才算真连上。端口在 listen 但无响应 = 小程序没回连，重启小程序。

代理会劫持回连：Proxifier 给 `WeChatApp.exe; WechatBrowser.exe; WeChatAppEx.exe` 加 `127.0.0.1; localhost; ::1` → Direct。

---

## 3. 运行时上下文结构（最关键的一条）

小程序页面里有 **4 个 frame**，游戏在 `name="gameContext"` 的 iframe 里：

```
top (servicewechat.com, keys≈264)      ← CDP Runtime.evaluate 默认打到这里
├── iframe[0] name="mainContext"                              keys≈39
├── iframe[1] name="gameContext"        ← UIManager / TREASURE / ROLE / System  keys≈147  ✅
└── iframe[2] name="gamePlugin_wxaed5ace05d92b218_mainContext" keys≈30
```

- 暴力试过 `contextId`：`contextId=7` 是 gameContext，但**每次会话会变，不要硬编码**
- 正确做法：用 `iframe[name="gameContext"].contentWindow` 跨进去（reachable，不跨域）
- 所有注入脚本都用这个解析函数（名为 `e0e1ResolveGameWindow`）

### gameContext 特有的坑

| 现象 | 原因 |
|---|---|
| `document.body.children === 0` | DOM shim，不是真 DOM |
| `canvas.parentElement === null` | 同上 |
| `appendChild` 静默失败、`getElementById` 查不到新元素 | 同上 |
| 没有全局 `cc` | Cocos 类要从场景节点借 |

**结论：DOM 覆盖层这条路走不通**，要在画面上画东西只能挂 Cocos 节点（见 `treasure_map_overlay.js` 的借类做法）。

### 注入模式的坑

- **进出摸金/战斗会重建 JS 上下文** → `once` 模式会被清掉，必须用 `--toggle`（`runtime_toggle`，走 `Page.addScriptToEvaluateOnNewDocument`，每个新 document 自动重注）
- `runtime_toggle` 的包装**不注入** `__e0e1JsInjectionReport`，脚本要自己把内容放进 `enable()` 返回的 `log` 字段
- `document-start` 注入时 `UIManager` 还不存在 → 脚本里要轮询等待（一般 6-8 秒）
- Console 里调不到函数 = 上下文没切对。脚本现在**同时挂 top 和 gameContext 两个 window**

---

## 4. 已做的工程侧代码修改

| 文件 | 改动 |
|---|---|
| `tools/hook.js` | ① 新增 `patchCDPFilterByCastToJson`（支持新版 `CastToJsonHookOffset`，用 `Interceptor.replace` 绕过 CDP 过滤——这是新版 flue 能连上的关键）<br>② 新增 `winHijackMiniAppConfig`，支持新结构 `MiniAppConfigStructOffsets`（LaunchConfigOffsets / SceneOffset / WebSocketURLStringOffset / RemoteDebugModeOffset）<br>③ 旧链路保留在 `winHijackLegacyScene`，51 个旧配置行为不变 |
| `package/devtools/engine.py` | ① `_is_radium_wmpf_path`：按路径过滤，排除企业微信 WXWork 的 `WeChatAppEx.exe`<br>② `_detect_wmpf_version`：版本号从**目录**解析（兼容 `RadiumWMPF\25715\` 布局），并优先选本机有 `addresses.{v}.json` 的版本 |
| `tools/cdp_inject.py` | 新增。命令行注入器，走 `build_injection_expression`（与 GUI 注入按钮同一套包装），支持 `--toggle` |
| `tools/cdp_probe.py` | 新增。枚举 executionContext、iframe 扫描、暴力试 contextId |
| `tools/cdp_snapshot_probe.py` | 新增。探测玩家快照字段结构 + ID→配置表反查 |
| `tools/cdp_deep_probe.py` | 新增。深度探针（嵌套结构、词条、觉醒分支） |
| `tools/audit_client_authority.py` | 新增。静态扫描 service 调用，按「客户端可控字段」排序 |
| `tools/extract_treasure.py` | 新增。从 `game.js` 抽出摸金行动相关模块到 `treasure-action/`（57 文件 / 10933 行） |
| `tools/js/*.js` | 见下节 |

---

## 5. 注入脚本（`tools/js/`，自动被扫描）

统一约定：
- 跨进 `gameContext` 用 `e0e1ResolveGameWindow()`
- 函数同时挂 top + gameContext（`e0e1Expose`）
- 双模式兼容：检测到 `__e0e1RegisterRuntimeToggle` 就注册控制器，否则按 `once` 跑一次

| 脚本 | 作用 | 用法 |
|---|---|---|
| `treasure_map_dump.js` | 摸金地图文本导出（ASCII 网格 + JSON） | `dumpTreasureMap()` |
| `treasure_map_overlay.js` | **在画面上给格子挂文字标签**（Cocos Label） | `treasureMapOverlayOn/Off/Status()` |
| `legion_members_dump.js` | 阴司成员列表导出 | `dumpLegionMembers(true)` 强制刷新 |
| `player_info_dump.js` | 玩家信息全量导出（已做配置表翻译） | `dumpPlayerInfo()` / `dumpPlayerInfoText()` |
| `desire_bag_dump.js` | 三尸背包与合成配置导出（按种类×品质的可合成数量 + `ComposeCfg` 真实成功率与失败返还），**只读、不消耗三尸** | `dumpDesireBag()` / `dumpDesireBagText()` |
| `damage_curve_probe.js` | 战斗/PVP 伤害采集：逐条记录伤害事件并分类（普攻/符咒/天书逐本/觉醒分支/技能）；PVP 下同时挂我方与敌方两个 World 并采样分数。跳过战斗见下 | `damageCurveText()` / `damageCurveJson()` / `damageCurveCsv()` / `damageCurveStatus()` / `damageCurveOrigins()` |

**当前完整支持的是好友切磋**（battleType 26）。它是唯一「跳过战斗也拿得到全量数据」的模式。
斗法／血月／酆都决斗／阴墟也能采，但**不能点跳过**（走服务端结算，会丢后续数据）。
面板和报告会按当前 battleType 实时提示该说哪句话。

报告里「双方每秒伤害」图 hover 到某一秒，会列出**该秒双方各自的伤害来源 Top5**
（技能名 + 来源 + 数值），来自采集端按秒预聚合的 `perSecondTop` / `perSecondBossTop`。
PVP 图用后者（对敌方英雄口径），因为分数只按 `BossDamage` 结算，这样才和曲线数值对得上。

#### 局内属性

`world.getFightHero().compAttributes.get(key)`，键见 `BattleAttributeKey`（`30142`）。
中文名取 **`AttrCfg.note`**（`AttrCfg.name` 是数字不能用）。
百分比**按采集端显式标记 `E0E1_ATTR_KEYS[].p` 判断，不依赖 `AttrCfg.style`**（配置取不到也不会错）。
`compAttributes` 里存的是**比率**，显示要 **×100**：9.2518 → 925%、2.135 → 213.5%、0.006 → 0.6%。
（实测 `logs/damage_curve_*.json` 确认。⚠ 不要改成 ÷100 —— 之前写错过一次。
  代码里的 `revertAttrFinalValue`（`10590`）走 `AttrCfg.parse` 且乘的是 10000，
  那是词条解析那一层，和这里读到的最终值不是同一个量，别混。）
显示取整（小于 10% 保留一位）；数值类（攻击/生命/攻速）不换算。
属性曲线纵轴同步：勾的全是百分比就按 % 显示，混了数值类（攻击）就退回原始值。

⚠ 面板读属性快照时**必须按字符串 key 查**：JSON 对象 key 都是字符串，用 int 查会全部落空
（只有字符串 key 的 `finalPvp` 能匹配上）。JS 没这个问题（`obj[1]` 等同 `obj['1']`）。
收录 19 项（攻击/生命/攻速/暴击率/暴击伤害/**法术暴击率(106)/法术爆伤(107)**/伤害加减成/
天书增伤/符咒增伤/PVP增减伤/最终增减伤/鬼仆增伤/法器增伤/普攻增减伤）。

派生项 **最终PVP增伤 = 本方PVP增伤(117) − 对方PVP减伤(118)**，key 是字符串 `"finalPvp"`，
采集端 `e0e1WithFinalPvp` 在输出时按秒给双方各算一条（依赖对方同秒的值，所以不能采样时算）。

面板里展示 `ATTR_PANEL_KEYS`（攻击/伤害加成/天书增伤/法术爆伤/暴击伤害/PVP增减伤/最终PVP增伤/最终增减伤）；
表里 `—` 表示该秒没读到这个属性。
展示两种：拖滑块按秒即时对比（含差值）+ 勾选属性画变化曲线（最多 4 条属性 = 8 条线）。
面板里给的是最后一秒的精简快照。

⚠ 属性采样和分数采样共用 `timeBattleTickSignal`（`$skillDamageCollect` 之外的第二个钩子），
所以跳过战斗时也能逐秒采到。
| `damage_curve_report.py`（Python，非注入脚本） | CDP 取数 + 落盘；`--from-json latest` 可拿已存 JSON 重算 HTML，不用重打一场 | `python tools/damage_curve_report.py --port 62000 --csv --open` |

**插件管理器的「PVP伤害分析」节点**（`package/plugin_manager/`，入口 `python plugin_main.py`）已经把上面两步自动化了：
打开开关后持久注入采集脚本，进 PVP 自动采双方，战斗结束自动在 `logs/` 生成报告，
面板显示分数与双方拆解，「打开图表报告」按钮用系统浏览器打开。
渲染代码在 `package/plugin_manager/damage_report.py`，GUI 与 CLI 共用一份模板。
| `block_popups_runtime.js`、`test_injection.js`、`wx_environment_probe.js` | 工程自带样例 | — |

注入：
```powershell
python tools/cdp_inject.py --port 62000 tools/js/player_info_dump.js              # once
python tools/cdp_inject.py --port 62000 --toggle tools/js/treasure_map_overlay.js  # 持久（推荐）
```

---

## 6. 逆向结论速查

### 数据在哪

游戏把服务数据挂到 gameContext 全局（`server-data.ts`）：
`TREASURE` / `SERVER_DATA` / `ROLE` / `USER` / `BATTLEFIELDS` / `ROLE_EXT` / `GOOD_FRIEND` / `SEASON_MAP`
另有 `UIManager`、`System`（Cocos loader，`System.import("chunks:///_virtual/configs.ts")` 取配置表）、`CommonUICfgId`

`ui.module` 是 getter，直接返回模块单例，不用碰模块注册表。

### 摸金行动

- 地图**开局全量下发**（`TREASURE.room.layers: Map<layerId, {rows,cols,cells:Map<cellId+1, cell>}>`），揭示只是单格 `explore` 请求
- 迷雾纯客户端：`getCellVisualState` 只按 `status` + 四邻接判定；未探索格子的真实 `cellType` 本地就有
- 格子类型 `TreasureRoomType` 0-12：0起点 1战斗 2精英 3BOSS 5小宝箱 6大宝箱 7锁箱 8上楼 9下楼 10空 11对决 12转盘
- **代码里没有「祭坛」「棺木」**，只有上述 13 种
- `cell.rewards` 存在但客户端不读；奖励来自 `explore/openBox` 的响应

### 三尸合成（Desire）

- 协议 `desire_composegem`，请求 `{itemIds: number[]}` —— 传的是 **cfgId 数组、可重复**，不是 uuid；
  响应 `Desire_ComposeGemR {role, items, result}`，`result` 为 true 成功 / false 失败；**失败时 `resp.items` 仍有返还**
- **奖励与成败都来自响应**，本地改不动。翻牌（`cardGameTurnOver`）同理
- 背包 `ROLE.desire.bag`：Map<uuid, GDDesireItem{id(=uuid), cfgId, locked, num, planInfo}>
  品质 `ItemCfg.getById(cfgId).quality`（1白 2蓝 3紫 4橙 5红 6黑金 7幻彩 8轮回），种类 `DesireCfg.getById(cfgId).type`
- `DesireType`：TANHEART=1 CHENHEART=2 CHIHEART=3 TANORDINARY=4 CHENORDINARY=5 CHIORDINARY=6
  合成硬约束 `canDoCompose` = **type 相同 && quality 相同**（心与凡不能互合）
- 不能合：`locked` 的、`planInfo.size > 0`（镶嵌在方案里）的；`canQulityCompose(q)` = 存在 `ComposeCfg.quality-1 == q`
- `ComposeCfg {id, num, quality(目标品质), ratio(万分比), returned(失败返还)}` **运行时可读**（`.list` / `.getById`）
  → 二合一真实成功率按 `quality == 材料品质+1 && num == 2` 查；**`returned < 2` 时二合一净亏材料，"永远不亏"不成立**
- 模块 `GET_MODULE(ModuleLocalType.DEASIRE)`（注意官方拼写 DEASIRE）：
  `putInGem(item)` / `putInGems=[0×5]` / `getPutInGems()` / `clearPutInGems()`（**不清 UUIDs**）/ `composeGem(itemIds)`
- UI：`DesireUI` 的 pages[1] 是合成页（`UIDesireComposePage`）；按钮 `btn_compose` / `btn_compose2`（`hasComposeAll`）
  `onComposeClick` 只读 `getPutInGems()` → **不关心列表怎么填的，所以可以直接调 `putInGem` 避开虚拟列表点击**
  任一放入品质 `>= 4`（橙色及以上）会先弹 `cfg.CommonConfirm`；⚠ 它**不在** `blockedViews()` 白名单，没关掉会挡死后续所有写操作和 `home()`
- 种类过滤器在背包页（`fifter = [[],[1,4],[2,5],[3,6]]`，cc.Toggle），**与合成无关**，只影响列表展示

#### 自动合成（`package/plugin_manager/features/desire.py`）

- 面板「三尸合成」手动点开始。策略是**一轮一轮跑**，每轮都从最低的、凑得出一对的品质档开始：
  连续失败到该档上限 → 升一档；升档后**成功一次**或**撞到品质上限** → 结束本轮、回最低档重新走。
  一整轮一次都没合成（材料都不够了）才收尾。
- ⚠ 同一档里先用「凡」；**本档最后一次机会时，只要有「心」就改用「心」**。
  `KIND_TYPES[kind] = (心, 凡)`，用反就会一上来把心当材料烧掉
- 日志一次操作一行：`UI操作：desire_compose_once 贪·凡·蓝 → 合成成功`
  （"开始"那行降到 debug，排查卡死时再开）
- JS op 在 `package/plugin_manager/desire_runtime.js`：**独立运行时，不进日常任务那套**。
  `desire_bag_stats`（只读）/ `desire_compose_open` / `desire_compose_once` / `desire_compose_close` / `desire_compose_probe`
  ⚠ 连续合成**不能**每次调 `h.open()`：它在页面未打开时会先 `home()`，那是日常任务"每个操作完回大厅"的机制，
  批次内只在开始时导航一次，之后复用已打开的合成页（页面意外关闭要报 unavailable，由批次重开）
- 合成不可逆：回执必须有 `confirmed: true` 且 `success` 是布尔，否则 `ExecutionUncertain` 立刻终止整批，绝不重试
- 日志 `logs/desire_compose.csv`：`seq` 全局累计递增、`batch` 每次开始 +1（都从日志反推，不另存状态）
- 报告 `logs/desire_compose_<stamp>.html`（`desire_report/`，手写内联 SVG）；
  直方图理论柱 = 间隔总数 × (1−p)^k × p，**p 默认 30%（官方宣称）、页面上可改**
- 只读探针 `tools/js/desire_bag_dump.js`（`dumpDesireBag()`），不消耗任何三尸，用来核对可合成库存与真实成功率

### 玩家信息（GDRoleSnap）

`Setting` UI（`CommonUICfgId.Setting`）→ `onOpen(isSelf, targetId)` → `getRolePreviewInfo` → `ui.info`

| 字段 | 结构 | 配置表 / 名称字段 |
|---|---|---|
| `equipSkill` | `Map<槽位, 天书ID>`（**值**才是 ID） | `SkillBookCfg.name` |
| `skillLevel` | `Map<天书ID, 等级>` | `SkillBookCfg.name` |
| `epicAwakening` | `Map<天书ID, Map<觉醒ID, 等级>>`（两层） | 外 `SkillBookCfg` / 内 `SkillBookEvolutionCfg` |
| `desirePlan` | `Map<槽位<<16\|序号, 三尸ID>`（**值**才是 ID） | `DesireCfg.getById(v).itemId.name` + `.itemId.desc` |
| `allDesirePlan` | `Map<方案ID(0/1/2), Map<18条>>` — **三套方案** | 同上 |
| `equipment` | `Map<槽位,{configId,level,entry[]}>` | `EquipmentCfg` + `EquipmentEntryCfg`（词条名在 `name`，百分比看 `group`） |
| `pet` / `formationPetInfo` | 鬼仆 + 阵法，`pet.skillLevel` | `PetCfg` / `PetEntryCfg`；**鬼仆技能走 `SkillBookCfg`** |
| `magic` | `{onUseMagic, plan}` | `MagicArtifactBaseCfg`；**方案条目 `cfgId` 属 `MagicArtifactEntryCfg`，名字在 `des`**，其 `attrType` 指向 `AttrCfg` |
| `attribute` | `Map<属性ID, 值>`，共 59 条 | `AttrCfg.note`（**名字在 `note`，`name` 是数字**）<br>`AttrCfg.style === 2` → 百分比，值 ÷100 |
| `previewHide` | 位掩码 | `EPreviewHideType`：0天书 1三尸 2脸谱 3鬼仆阵法 4法器<br>自己看自己时从 `stats.statistics.get(94)` 取 |

其他：
- 名称必须含中文才算有效（`/[\u4e00-\u9fa5]/`），否则丢弃——避免输出 `ID1001` 垃圾
- PVP 汇总用正则从描述文本抠（`N%pvp增伤` / `pvp增伤+N%`，「PVP减免」也算减伤）
- 脸谱**只有一套**：快照里没有 `allEquipment` 类字段，`ROLE.equipment` 是「穿戴 8 件 + 背包 58 件」

### 战斗

- 符咒抽取**本地算**，种子 `battleData.randomSeed` 服务器下发；有官方调试后门 `cardDrawRuntime.forceCardId`（队列非空时按顺序发牌）
- 上报 `endStageBattle`：只有 `win / dropItems / wave / static / verifyData / battleTime / killMonster`，`input` 空、`inputGzip` null（摸金线胜局会传 gzip 操作记录）
- `dropItems` = 本地 `statistics.CollectItems`（Map<itemId,count>），**输赢都传**；道具 ID 空间含 `10003 金币`、`10004 钻石`
- 摸金 `Treasure_BattleEndR` 响应**回 items**，客户端用 resp → 篡改无效
- 关卡 `Battle_EndStageBattleR` 响应只有 `{wave, resultType}` → **服务端是否独立算掉落，静态判不了，待实测**

#### 伤害计算（`game.js:160584-160647` 是带日志版的 `calcDamage`）

```
dmg = ATK_V × baseCoeff × dmgAddRate × elementAddRate
    × [暴击 max(1,1+CRIT_PWR)] × [技能暴击 max(1,1+skillCritPwr)]
    × (1 + dmgTypeRate + hpDmgAddRate + skillTypeAddRate + attackDmgRate) → floor
    × max(0.5, 1+pvpDmgRate) × max(0.25, 1+finalDmgRate) × [血月/赛季修正]
dmg = max(1, dmg)
```

- `baseCoeff` = 技能系数×等级×增伤 buff（灼烧/爆裂等）；距离伤害、已损/当前/最大生命伤害都只是换系数
- `dmgAddRate` 下限 0.25；`pvpDmgRate` 下限 0.5；`finalDmgRate` 下限 0.25
- **`def` / `dmgRed` 是死字段**（`35007` 初始化为 0，只出现在调试日志）→ 没有独立防御减伤，全靠 `DMG_RED` 系列属性
- 普攻有**按距英雄初始点 X 的分段加成**（B1/B2 插值，`35161-35171`）
- 最后过 `CompLife.sub`（`27002`）：伤害免疫/格挡/护盾/生命保底/clamp，**统计记的是扣血后的实际值**，会被 overkill 截断

#### 伤害分类（`system-skill.ts:164590-164615`）

按 `SkillFunctionType`（`30336`）分流到 `BattleStatisticsKey`（`172620`）：

| 类型 | 统计键 |
|---|---|
| `ATTACKSKILL`(1) 普攻 | `AttackDamage` |
| `SKILL`(3) 符咒 | `CardDamage` + `CardDamageWater/Fire/Wind/Terra` |
| `RARESKILL`/`_SUMMON`/`_CAST`(4/13/17) 天书 | `SpecialCardDamage` + `SpecialCardDamage<bookId>` |
| `PETSKILL`/`_PASSIVE`/`_AUTO`(5/10/11) 鬼仆 | `PetDamage` |
| 三尸(6) / 15,16 / 法相(12,14) / 战旗(18) / 鬼店(8) / 傀儡装(7) | `DesireDamage` / `CardDamageEpic` / `BaseDamage` / `FlagDamage` / `StoreDamage` / `FashionDamage` |

- 🐞 **`PETFUZHOUSKILL`(9) 官方漏统计**（`164613` 判定没写 9），鬼仆符咒伤害掉进 `OtherDamage`，结算面板的"鬼仆伤害"偏低

#### ⚠ 15/16 那一档：枚举名是坑，别按名字认

`SkillFunctionType` 15 `EQUIPMENT_SKILL` / 16 `EQUIPMENT_STONE_SKILL` 名字像"装备/脸谱"，
**但真正提供技能的是法器系配置表**，不是 `EquipmentSuitSkillCfg`。判定方法是按配置表反查
`skillId` 落在哪张表里（采集脚本 `e0e1BuildOriginIndex` 就是这么做的）：

| 配置表 | 字段 | 含义 |
|---|---|---|
| `MagicArtifactBaseCfg`(`31732`) | `skill` | 法器 |
| `MagicArtifactStoneCfg`(`31828`) | `skill` | 法器宝石 |
| `MagicArtifactTemperSkillCfg`(`31812`) | `skill` | 法器淬炼（定义处之外**无调用**，可能服务端/未解包） |
| `EquipmentSuitSkillCfg`(`31320`) | `skillId` | 脸谱套装 |
| `FashionCfg`(`31464`) | `skill` / `attackSkill` | 傀儡装 |
| `BaseSkinCfg`(`30909`) | `skill` | 基地法相 |

另：`CardDamageEpic` 在结算文案里叫「法器伤害」（`62570`，实测确认为法器宝石），
`BaseDamage` 叫「道法水晶伤害」（`62571`），与枚举注释（`36347`）不一致，以实测反查为准。
`damage-context.ts:35132` 的 `isArtifactStoneSkillFunctionType` 施加 `DMG_ARTIFACT`(133)，命名也是"法器"侧。

⚠ 界面用词（用户确认）：**傀儡装**（不是"时装"）、**法相**（不是"基地"）。
#### PVP 双分数对抗（好友切磋 / 斗法 / 血月对战）

双分数 PVP 会建**两个 World**：`selfBattleWorld` / `otherBattleWorld`（`2010`、`46504`），
两者都在 `BattleManager.ins.getBattles()` 里。

- **`options.mineInfo` 就是各自主人的分数对象 `{ isSelf, score }`**（`1981-1988`、`46476-46483`）
  → 有 `mineInfo` 即双分数 PVP；`isSelf` 直接区分敌我；`score` 是真实分数。不需要找管理类单例。
- 敌方 World 的 `battleData.leftTeam` 被换成了 `rightTeam`（`1992`），所以读觉醒/队伍时拿到的是敌方数据。

每秒结算一次（`2015`、`46533`；公式在 `2027-2045` 与 `46549-46565`）：

```
a = 本秒我方 BossDamage 增量,   l = 本秒敌方增量,   t = floor(curFightTime)
p = a/(a+l) − 0.5,   f = l/(a+l) − 0.5
g = PVPInitVariable^t × PVPBaseBonus          ← 时间权重，指数放大
selfScore += g*p,    otherScore += g*f
```

- 伤害占比正好五成时不加分；**越到后面同一占比给的分数越高**（`PVPInitVariable^t`）
- 双方分数**初值都是 `PVPInitScore`**（`1983`、`46478`），复算时必须加上，否则差一个 `PVPInitScore`
- 胜负：任一方分数 > `2 × PVPInitScore`（`2044`、`46562`）；或 `PVPLimitTime` 到时比分高者胜
- 配置表 `PVPcfg`（`32049`，有 `.list`）按 `PVPType` 取行

覆盖的 battleType（`getPvpType`，`10437` + `PVPType` 枚举 `30197`）：

| battleType | 值 | PVPType |
|---|---|---|
| `mine` 阴墟 | 8 | MINE(1) |
| `battlefieldDuel` 酆都战场决斗 | 16 | THEATER(2) |
| `arena` 竞技场/斗法 | 19 | ARENA(3) |
| `season` 血月 | 20 | SEASON(5) |
| `goodFriend` 好友切磋 | 26 | FRIEND(6) |

- 伤害事件 `battleSignal["$skillDamageCollect"]` → `(source, skillId, damage, target, isCrit)`，不受 `APP_DEBUG` 门控
- 但 `__battle` 控制台和 `getDamageMap()`（分技能伤害表）**只在非 production 包里有**（`9326`、`164591`）
- 时间轴 `world.battleTime.battleTime`，**单位秒**
- 结算界面本来就展示 `damageStatisticsSelf` / `damageStatisticsOther`（`46433`），采敌方数据不算越界
- 玩家信息从战斗数据的 `leftTeam` / `rightTeam` 队伍成员上读（`roleId` / `name` / `level` / `fightPower` /
  `equipSkill` / `skillLevel` / `epicAwakening` / `desirePlan` / `pet` / `formationPetInfo` / `equipment`）；
  字段不一定齐全，`damage_curve_probe.js` 里是防御式读取，缺哪个就少哪个
- 局内属性走 `world.getFightHero().compAttributes`，键见 `BattleAttributeKey`（`30142`）

#### 跳过战斗对采集的影响（`skipBattle`，`46596`）

跳过是**两条完全不同的路径**，能不能拿到全量数据取决于战斗类型：

| 分支 | 条件 | 行为 | 数据 |
|---|---|---|---|
| 本地快进 | `battleType === goodFriend(26)` | `skipBattleLocalFastForward()`（`46619`）：先 `detachBattleWorlds` 把两个 World 移出 `battles`，再**同步紧循环** `world.update(ts)` 步进 0.03125s（`TICK_INTERVAL`）把整场跑完 | ✅ 全量：伤害事件照发、分数照常累计 |
| 服务端结算 | 其它 PVP | `_requestEndBattle` 请求服务端结束 → 直接 `endFight`，本地不补算 | ❌ 只有跳过前已模拟的部分，最终分来自服务端 |

因为本地快进是**一次同步调用**跑完的，靠实时定时器采样会全部错过 ——
所以分数采样必须挂 `world.battleSignal.timeBattleTickSignal`（在 `world.update()` 内部触发，
快进时每步都发），不能只靠 `setInterval`。采集脚本已经这么接了。
`battleTime.isSkipping`（`11791`）为真即处于跳过状态，脚本会记 `pvp.skipped` 并在报告里标注。

⚠ **光靠轮询 `getBattles()` 采不到跳过的战斗**：`skipBattleLocalFastForward` 第一件事就是
`detachBattleWorlds` 把两个 World 移出 `battles`（`46622`），如果用户一进战斗就点跳过，
500ms 轮询一次都轮不到。所以采集脚本在 `BattleManager.ins.createBattle` 上挂钩，
World 一创建就同步挂上（`e0e1PatchBattleManager` / `e0e1TryAttachWorld`），轮询只作兜底。

⚠ **分数采样是全局累积的，必须按场次归零**：`E0E1_SIDES`（伤害）每场会被新 World 替换，但 `E0E1_PVP.samples` 不会 —— 连打两场会拼成两场之和（曾因此出现"时间轴 100 秒"而实际每场 ≤60 秒）。
已在挂接 self World 时按 `instanceId|battleType|seed` 检测换场并归零（`e0e1ResetPvpIfNewBattle`）。

⚠ `PVPLimitTime` / `PVPInitScore` 等**以实测为准**，不要拿测试数据当真实配置：真实值在诊断输出 `pvp.cfg` 里。

排障：面板「诊断」按钮 = `damageCurveDebug()`，会报脚本在不在、`createBattle` 钩没钩上、
挂了几个 World、`getBattles()` 里还剩几个（被 detach 就是 0）、各方事件数、
分数样本数与秒范围 `pvpSampleSeconds`、当前场次 `pvpInstanceKey`、最近异常。

#### 觉醒分支的伤害归属

配置链：`SkillBookEvolutionCfg`（`33168`，含 `skillBookBelong` / `evolutionPath` / `evolutionSkillId[]`）
→ `EvolutionSkillCfg`（`33184`，含 `skillLevel` / `skillId`）。两张表都有 `.list`，可全量建
`skillId → {天书, 分支, 分支等级, 路径}` 反查索引，所以**分支级伤害拿得到**。

分支影响伤害有两条路径，语义不同：

| 路径 | 机制 | 能否单独拆 |
|---|---|---|
| 技能替换 | `getEvolutionSkillId`（`10535`）收集所有已激活分支各级的 skillId，**排序取最大**替换天书主技能 | ✅ |
| 属性加成 | `initRareSkillEvolutionProperties`（`160343`）按 `propertiesGroup` 去重合并所有分支的 `properties` 到主角属性 | ❌ 混进全局属性，无法从伤害数字剥离 |

`EvolutionPath`：1 主觉醒 / 2 主阶 / 3 分阶 / 4 副觉醒；`getEvolutionSkillId` 只处理 1，另三种在战斗侧的调用点**待实测**。
本场已激活分支读 `world.options.battleData.leftTeam.team[].epicAwakening`（`Map<bookId, Map<branchId, level>>`）。

### 赛季战场

- 潜行（`ESeasonExtKey.stealth = 4`，`player.ext.get(4) > 0`）：**状态服务端给，隐藏客户端做**（`shouldHideStealthMarch`），潜行单位数据照样下发
- 战旗：`flagId` 在同步的队伍数据 `{roleId, energy, flagId}` 里，渲染时直接读 → 同战场内可见（设计意图待确认）
- 可见范围：仅限你所在的那张战场地图

---

## 7. 安全审计结论（开发者视角）

### 已确认的信息泄露（客户端持有但不该给用户看）

| # | 系统 | 泄露内容 | 状态 |
|---|---|---|---|
| 1 | 个人信息 | 对方隐藏的天书/三尸/脸谱/鬼仆/法器 | ✅ 实测：位掩码 31（五项全隐藏）照样全读到 |
| 2 | 摸金地图 | 未探索格子的真实类型 | ✅ 实测 |
| 3 | 赛季战场 | 潜行单位的位置/行军 | ✅ 逻辑确认 |
| 4 | 阴墟矿 | `getOtherMine` 下发完整 `GDRoleSnap` 且**不读 `previewHide`** | ⚠️ 当前 UI 只用头像/名字/阴司，但数据在内存 |
| 5 | 敌方塔 / 战旗 | 驻守名单、战旗 | ⚠️ 明示，疑似设计 |

**根因（第 1/4 条）**：`previewHide` 在整个客户端**只在 `page_info.ts` 被检查过**（6 处，全在个人信息界面）。其他所有消费 `rolePreview` 的视图都不判断。

`getRolePreviewInfo` 的调用点有 **25 处**（排行榜、矿、斗法、竞技…），全部拿到全量快照。

**修法建议**：服务端下发 `GDRoleSnap` 前按对方 `previewHide` 裁剪字段（一次解决所有视图），而不是逐个视图加判断。

### 信任边界

| 等级 | 项 | 说明 |
|---|---|---|
| 🔴 待实测 | `reissueStage` | `battleId: 0` / `battleTime: 0`，`dropItems` 来自 localStorage 明文存档串，服务端无校验锚点 |
| 🔴 待实测 | 关卡 `endStageBattle` 掉落 | 响应不含 items，无法判定服务端是否独立算 |
| 🟡 | 8 处数值字段 | `addPrice(price)` / `forging(cost)` / `buffRally(duration)` / `CommonEnergyBuy(ratio)` / `teamUpdateRatio(ratio)` 等，服务端按 id 查配置重算即可 |
| 🟢 | 38 处 `num` | 购买数量，常规校验 |
| ✅ 非漏洞 | 行军加速 | 请求体只有 `warId`，扣费减半都在服务端 |
| ✅ 非漏洞 | 摸金战斗奖励 | resp 回 `itemMap`，客户端传空也照常发奖 |

**教训**：不能把「客户端传了某字段」等同于「服务端信了它」。判据应该是**响应里回不回权威结果 + 客户端用不用它**。

---

## 8. 常用命令

```powershell
# 起 GUI
python main.py

# 判活
python -c "import asyncio,sys; sys.path.insert(0,'tools'); sys.path.insert(0,'.'); import cdp_probe; print(asyncio.run(cdp_probe.scan_ports(62000,65535)))"

# 注入（持久模式推荐）
python tools/cdp_inject.py --port 62000 --toggle tools/js/treasure_map_overlay.js
python tools/cdp_inject.py --port 62000 tools/js/player_info_dump.js

# 探针
python tools/cdp_probe.py --port 62000
python tools/cdp_deep_probe.py --port 62000

# 静态审计
python tools/audit_client_authority.py --top 50
python tools/audit_client_authority.py --all-keys
```

输出落在 `logs/`（`cdp_*.log`、`player_dump.txt`）。

用 CDP 直接开界面（界面没开时导出用）：
```js
UIManager.ins.open(CommonUICfgId.Setting, false, <targetId>)
```

---

## 9. 待办 / 已知未决

1. **实测 `reissueStage` 与关卡 `endStageBattle`** —— 需要能构造协议包直接发的工具（目前没有）。这是唯一能把两个 🔴 定性的办法。
2. **黄泉货舫** —— 不在已反编译代码里。分包只解了 `game`，`feed_v1 / feed1 / feed2` 未解。
3. `unlockModuleIds` 里约 10 个 ID（`ID201`~`ID208`、`ID301/302`、`ID13`）没映射到中文名，`ModuleType` 枚举只到 121。
4. 三尸 PVP 汇总是正则从描述文本抠的，遇到「最多获得8次」这类叠加描述可能算不全。
5. 顺着 `getRolePreviewInfo` 的 25 个调用点逐个查是否也漏了 `previewHide`（第 4 条已确认矿漏了，其他的很可能同因）。

---

## 10. 用户协作偏好

- 偏好「抽代码 → 定点 hook → 可直接在 DevTools 跑的注入脚本」，不要泛泛而谈
- 图片无法被当前模型读取，需要信息时用文字或跑脚本输出纯文本
- 站在**开发者/审计**视角：要的是「调用点 + 可控字段 + 服务端该怎么校验」，不要含糊的"可能有风险"
- 结论要区分「已实测」和「静态推断」，推断的必须标注待实测
