# 微信与抖音血月模块静态比对（2026-10-17）

结论：核心血月客户端逻辑基本一致。不能说整个包一致；198 个按名称选中的 season/queue/service/define-index 模块中，174 个在消除格式和局部绑定变量名称后 AST 相同，24 个有差异。直接关系到本插件的差异主要是抖音隐藏服务器名称、依赖分块编号变化和宿主 Promise 引用变化。尚未证明服务端行为、动态配置及隐身授予条件相同。

## 文件身份与方法

- 微信：`D:/UGit/e0e1-wx/output/wx6d5e82c174635a48/65/subpackages/game/game.js`，15,517,208 字节，SHA256 `0f9f2b0be07e2e65cce06a69ed44ff2000a91ddf685d21de5d98293df4397eef`。
- 抖音：`C:/Users/AshenZhou/AppData/Roaming/douyin/microGameCache/resource/packages/tt310e47b3ae06acc002/0.1.71/subpackages/game/game.js`，10,571,697 字节，SHA256 `78c8ffdb0a9da9890ad92099fd241cfe13ed89698f10d8bcdc5a193589b77609`。
- `compare_modules.cjs` 按 `System.register` 的完整虚拟模块名确定边界，Babel `parseExpression` 仅解析、不执行代码。移除位置、注释和 raw 表示，另按函数词法作用域对参数及变量声明作顺序绑定规范化；属性名、字符串、数字、运算符、函数结构和变量引用关系仍参与比较。
- `module-comparison.json` 保存原文件身份、每模块原始 UTF-16 字符偏移、微信行号、长度、源码和 AST 哈希；`ast-diffs.json` 保存差异。原抖音文件主要在第 2 行，定位应使用字符偏移，不能把字符偏移当成 UTF-8 字节偏移。
- 这属于静态语法/绑定比对，不是形式化运行等价证明。只覆盖匹配的 198 个模块，不包含服务器、资源配置完整性和运行时改写。

## 关键模块与差异

- `service-manager.ts`：规范 AST 相同。微信原行 146358，抖音字符偏移 5067231。
- `types-season-map.ts`、`ui-season-op.ts`、`ui-season-march-speedup.ts` 及其 view：规范 AST 相同。
- `season-module.ts`：微信原行 137280，抖音字符偏移 4773329。规范 AST 只差 3 个叶子：副作用依赖 `./index2.ts` 变成 `./index3.ts`（对应 setter 为 null）；另 2 处微信自由变量 `Promise` 在抖音中为外包装第 5 个参数 `r`。单独提取模块不能证明该宿主参数实际值，因此保留为运行时未知。加速、挑战、队列、状态、建筑方法本体无其他 AST 差异。
- `season-helper.ts`：仅同一副作用依赖编号差异，隐身判断与阵营判断相同。
- `ui-season-queue-detail.ts`：微信原行 263472，抖音字符偏移 8972012。攻击和防御两种行渲染时，微信 `serverText: this.getRoleServerText(role)` 改成抖音 `serverText: ""`；其他内容，包括 `canAttack`、`tryStartBattle`、角色闭包、列表源和坐标，规范 AST 相同。
- `season-queue-detail-role-cell.ts`：微信原行 141469，抖音字符偏移 4914504。微信显示 `[serverText]`，抖音将 `lab_server.node.active=false`；其余角色/按钮关联无变化。
- `season-network-data.ts`：仅 `Promise.resolve` 对应的宿主参数引用差异。连接、请求转发和同步流程没有其他规范 AST 差异。
- `define-index.ts` 整体不同：抖音存在其他业务新增枚举/类型；不应以整体文件哈希推断血月 RPC 不兼容。血月枚举与关键方法已人工核验，见下。

## 请求签名和回执（实际源码）

`define-index.ts` 直接导出 `SeasonService`，正确函数身份是模块导出的 `SeasonService.moveSpeedUp` 与 `SeasonService.startPVPBattle`，不是臆造的 protobuf 路径。微信提取文件第 7413 行为直接导出，7259 行为 Season 服务注册中的 `moveSpeedUp`。

`ServiceManager.ins.service(fn, params, toast=true)` 内部执行 `await fn(params)`；返回 `code===0` 才转换为 `{err:null,resp:response.getData()}`，否则 `{err:response,resp:null}`。对应微信提取 `wx-service-manager.ts:84`（原文件 146441 行）。

`SeasonModule.requestMarchSpeedUp()` 无参数，调用 `SERVICE(SeasonService.moveSpeedUp,{warId:this.enteredMapId})`，等待后返回 `{ok:true}` 或 `{ok:false,errMsg}`。对应 `wx-season-module.ts:2790`（原文件 140069 行）。不存在名为 `marchSpeedUp` 的同义方法。

`SeasonModule.startPVPBattle(params)` 调用 `SERVICE(SeasonService.startPVPBattle,params)`，直接保留 `{err,resp}`。原 UI 的 params 为 `{targetId:role.id,warId:this.module.enteredMapId}`。对应 `wx-season-module.ts:1928`、`wx-ui-season-queue-detail.ts:192`（原 139207、263663 行）。

若被动旁观 ServiceManager，必须用严格函数对象身份和本次 warId/targetId 过滤，并等待对应 Promise 完成。不应把旁观窗口内首个无关请求当作当前动作，不应将超时或未 settled 回执当成成功。

## 原 UI 前置条件与角色关联

原 `UISeasonOp.getSpeedUpDisabledReason()` 检查有行军、UI 冷却、剩余时间不小于 `MarchSpeedUpMinTime`，并且 `shopHelper.getItemCount(MarchSpeedUpItem[0]) >= MarchSpeedUpItem[1]`。加速成功后才设置 `_speedCooldownUntil = serverTime + 1000*MarchSpeedUpCD`；确认面板仅在 `{ok:true}` 后提示成功并关闭。证据 `wx-ui-season-op.ts:221,282,297` 和 `wx-ui-season-march-speedup.ts:46`。

原 `UISeasonQueueDetail.canAttack(role)` 要求目标非自己且有效、建筑存在、双方都在建筑 members、己方状态 idle、不同阵营。`tryStartBattle` 最后再排除己方 battle 状态。插件若绕开按钮层直接调用模块，不能只检查“不是战斗状态”。证据 `wx-ui-season-queue-detail.ts:177-199`。

原 `SeasonQueueDetailRoleCell.apply(data)` 并未保存 `roleId` 字段；按钮是 `btn_attack.addClick(data.onAttack,data)`。回调 target 是带 `role` 的 data，UI 当前角色来自 `attackEntries[index].role` / `defenseEntries[index].role`，并由闭包传给 `tryStartBattle(role)`。只按文本、按钮存在或行序号猜角色都不可靠。

## 行军身份与更新未知

`GDSeasonMoveInfo` 含 `id,pathLen,from,to,start,arrive`（`wx-define-index.ts:3096`）。`getSeasonMapMarchIsSpeedUp(move)` 通过基础路径行军时间与 `(arrive-start)/1000` 比较判断是否加速（`wx-season-module.ts:2147`），说明行军时间字段属于可变运行状态，不适合作为持久动作唯一身份。

本客户端 `requestMarchSpeedUp()` 的成功路径没有本地赋值 `arrive/start/from`；地图通过服务器同步更新。本轮静态分析不能证明加速后到底只改 arrive，还是也重置 start/from。`arrive+to` 作为去重键有重置风险；`start+to` 也不应未经验证宣称绝对稳定。更稳妥的实现应把一次行军的被动跟踪状态和可变 ETA 分开，记录动作前快照及成功回执、等待对应服务器同步；身份不能确定时停止自动重复发送，活动现场再进行只读前后比对。

## 隐身与水旗

`ESeasonExtKey.stealth=4`（`wx-define-index.ts:496-497`），`seasonHelper.isStealth(role)` 仅判断 `role.ext.get(4)` 是否为正整数（`wx-season-helper.ts:33`），并未要求特定 `flagId`。阵营过滤见其 `shouldHideStealthMarch`。

`seasonHelper.getBattlegroundSkillParam` 根据 `flagId` 对应配置和 `flagSkillLv` 选择 battlegroundSkill 技能组，随后按 skillEvent 找 params；这不能自动证明“所有 ext4 都是水旗”。当前工程 `血月调查与插件设计.md:134` 本身明确水旗 flagId 与授予条件未证实。因此现有标注宜叫“隐身状态”，具体旗名仅在取得实际配置名时展示。没有现场配置证据，不能凭 enum 或玩法称呼补足旗帜映射。

## REA 证据与边界

REA 只读解析了上述提取快照中的两平台 service-manager、ui-season-march-speedup 和 ui-season-queue-detail，共 6 文件 37,285 字节，0 解析失败。原包到快照的名称/偏移/哈希映射在 `module-comparison.json`；REA 分析的是快照，不应声称它独立分析了整个原包。

- Parent Evidence：`ev_9fbe34cc52bfdfafa4dd194a80777033e9913bf98347d11abecd08e6e7a8f668`
- Summary Evidence：`ev_0e9d2d734a310824ffb4898f2b2e32b66113360129c9977442a6971f58b1dad1`
- 快照根身份：`a0900f2203ffa979255db416aba46bf45df3a3017f7092cebdd33e192250768c`
- 可复用摘要：`rea-summary.json`；REA 标注 graph partial（另 10 文件未选）及 semantic partial/truncated（每文件 1000、总 5000 node 限额），不能作为行为缺失证明。具体一致性结论来自完整选中模块 AST 比对和源码核验，REA 提供静态解析的补充证据。

本轮没有执行游戏脚本，没有发出真实加速/挑战请求，没有修改 D 工程或游戏缓存。现场仍需验证：宿主 Promise 参数身份、服务器回执与同步时序、加速后 start/from/arrive 更新、实际旗帜配置。
