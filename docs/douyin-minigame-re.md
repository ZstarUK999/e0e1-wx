# 抖音 PC 客户端 · 小游戏加载机制逆向记录

目标：判断 e0e1-wx 的注入手段能否移植到抖音 PC 的同一个游戏（**遗弃之地**）。
版本：抖音 PC `8.7.0`（`C:\Program Files (x86)\ByteDance\douyin`）
游戏：appid `tt310e47b3ae06acc002`，版本 `0.1.70`，Cocos Creator **3.8.5**，发行 `hortor`（`sw-yqzd*.hortorgames.com`）

---

## 1. 抖音 PC 本体是什么

不是原生客户端，是 **字节自研 Electron 分支（TT Electron）**：

- 入口 `douyin.exe`（2.7MB 壳）→ 加载 `8.7.0/main.dll`（199MB，内含 Electron 主进程 JS，webpack 打包）
- `8.7.0/LICENSE.electron.txt`、`resources.pak`、`v8_context_snapshot.bin`、`tt_electron_config.json`
- `main.dll` 里能看到 Electron 主进程源码（`lib/browser/api/lynx-window.ts` 等）
- **原生扩展了 `electron.LynxWindow` / `LynxBaseWindow`**（`process._linkedBinding("electron_lynx_window")`），即抖音 PC 首页/业务用 Lynx 渲染
- 另带 `lynx.dll`（41MB）+ `lynx_core.js`，`parfait.dll`，`sscronet.dll`（Cronet 网络栈）

## 2. 小游戏的载体：Electron `<webview>` + 本地静态服务器

`resources/app.asar` 里有页面 `pages/gameBrowser/index.dc40ecba99cd9b1f.js`，核心渲染：

```jsx
<webview ref={...}
         src={initURL}
         allowpopups="true"
         preload={preloadPath}
         webpreferences="nodeIntegration=true, enableRemoteModule=true" />
<webview ref={...} className={...webviewSub} src={sub} ... />   // 副 webview
```

- `initURL` / `preloadPath` / `type` 来自 `document.location.href` 的 query 参数
- **`nodeIntegration=true, enableRemoteModule=true`** —— 游戏 webview 内具备完整 Node 能力
- 页面里跑字节 JSBridge（`bytedance://` scheme，`window.JSBridge` / `ToutiaoJSBridge`）

### 资源服务

`%APPDATA%\douyin\microGameCache\resource\file-server.js`（654KB webpack bundle）是 **Express 静态服务器**，由客户端每次开小游戏时 spawn 成子进程：

```js
s.all("*", (req,res,next) => {
  res.header("Access-Control-Allow-Origin","*");
  res.header("Access-Control-Allow-Private-Network","true");   // ← 关键
  next();
})
s.use("/resource", express.static(process.argv[2]))
const port = await portfinder.getPortPromise({port: 5678})
s.listen(port, () => process.send({port}))
```

- 默认端口 **127.0.0.1:5678**（被占用则 portfinder 顺延）
- 服务目录 = `microGameCache/resource`
- 响应头 `Access-Control-Allow-Private-Network: true` 说明**请求方是公网 origin 页面**向本地发请求（见第 5 节）

## 3. 小游戏包落在哪里（重点）

```
%APPDATA%\douyin\microGameCache\
├─ webview-preload.js                       # 游戏 webview 的 preload（内部 require("electron")）
├─ resource\
│  ├─ file-server.js                        # 本地静态服务器 (5678)
│  ├─ jssdk\4.31.0.0\                       # TMA/小游戏运行时
│  │   ├─ page-frame.html                   # 页面外壳 (1025B)
│  │   ├─ webview.js / tma-core.js / tmg-core.js / tmg-subcontext.html
│  │   ├─ high-performance-game-boot.js / -worker.js
│  │   ├─ vconsole.html / vconsole.js       # 「DEBUG PAGE」
│  │   └─ jssdkcheck.json                   # 417 个文件的「尺寸」清单
│  ├─ dynamic-tmar-sdk\bizApp\1.34.0.5\__dev__\    # webview.js / service.js / tma-open-lynx.js
│  │              bizGame\1.0.0.6\
│  └─ packages\tt310e47b3ae06acc002\
│      ├─ package-cache-v2.json             # {"__APP__":{"md5":"jkCD...","bytes":3810139}}
│      └─ 0.1.70\                           # ← 游戏包，明文
│          ├─ game.js           (3.2KB, __tt_define__/__tt_require__)
│          ├─ application.9006e.js
│          ├─ app-config.json   (subPackages: feed_v1/feed1/feed2/game)
│          ├─ preload-modules.json
│          ├─ web-adapter.5fadd.js / engine-adapter.df7bf.js
│          ├─ cocos-js\         (_virtual_cc-*.js 1.75MB, spine, meshopt)
│          ├─ hortor\           (HSDK.tt.js, env.js, sdk.js, polyfill.js)
│          ├─ src\              (settings.2baaa.json, system.bundle, bundle-scripts\*)
│          └─ assets\
└─ tt310e47b3ae06acc002\                    # 登录态 + user/gamecaches
    ├─ login-info.json
    └─ user\gamecaches\
```

`0.1.70/src/settings.2baaa.json` 首行：`{"CocosEngine":"3.8.5", ...}` —— 与微信版一致，**确认就是遗弃之地**。
`hortor/env.js`：`APP_CDN=https://sw-yqzd-res.hortorgames.com/tap`，`APP_SERVER=https://sw-yqzd.hortorgames.com`。

### 和微信路线的对比

| 项 | 微信（WMPF） | 抖音 PC |
|---|---|---|
| 包格式 | `wxapkg`，需解密/解包 | **磁盘上直接是明文 JS**，无需解包 |
| 运行时 | `WeChatAppEx.exe`，游戏在 `gameContext` iframe | Electron `<webview>`，`nodeIntegration=true` |
| 拿 CDP | Frida hook WMPF 开调试 → 9421 回连 | 见第 4 节，常规手段全被封 |
| 静态分析 | 必须先反编译 | **直接读 `src/bundle-scripts/*`** |

**结论：静态分析这一侧，抖音比微信简单一个数量级。**

## 4. 拿调试通道的尝试（全部失败，记录以免重复踩）

| 手段 | 结果 |
|---|---|
| `douyin.exe --remote-debugging-port=9333` | 进程能起，**端口没监听** → TT Electron 不认/剥离该开关 |
| `--remote-debugging-pipe` | 无 `chrome_devtools_remote` 命名管道 |
| `--inspect=9334` | 无效 |
| `NODE_OPTIONS=--require=xxx.js` | Electron 打印 `Most NODE_OPTIONs are not supported in packaged apps.` |
| 卸载目录 `resources/app.asar`、`app.asar.unpacked\preload.js` 打补丁 | 都在 `8.7.0\md5.json`（1093 个文件）里 → 会自修复，且需管理员写 Program Files |
| 注册表 `HKCU\Software\ByteDance\douyin` | 只有 `use_lynx_douyin` / `enable_app_guard` 等，无调试开关 |
| 内置 `resources/edt/`（Extended DevTools 扩展 + `init_vconsole.min.js`） | 存在，但没找到启用开关 |

## 5. 完整性校验链（谁在还原，终点在哪）

实测：改文件后开小游戏，看是否被回滚。

| 文件 | 是否被还原 | 说明 |
|---|---|---|
| `microGameCache\webview-preload.js` | **每次启动都重写** | 改了必被覆盖 |
| `resource\file-server.js` | **会被还原**（改后 → 回滚成 793503 字节） | 平台运行时资源 |
| `resource\jssdk\4.31.0.0\**`（含 `page-frame.html`） | **不还原**（4 次重启 mtime 仍为首次下载时间） | ✅ 可持久化修改 |
| `resource\dynamic-tmar-sdk\**` | **不还原** | ✅ |
| `resource\packages\tt...\0.1.70\**`（游戏包） | **不还原** | ✅ 可持久化修改 |

→ **校验链的终点在 `resource/` 这一层**：运行时文件（preload / file-server）每次重写，缓存资源只按版本号拉一次。

本地没有能覆盖 `file-server.js` / `webview-preload.js` 的清单文件（`jssdkcheck.json` 只覆盖 `jssdk/` 内部，且只记录**字节数**不是 hash），说明还原动作在客户端内部，不走本地清单。

## 6. 页面 origin 与「回连失败」的真正原因

- `IndexedDB/` 下出现过 `https_minigame.zijieapi.com_0.indexeddb.leveldb`
- `8.7.0\..\config.json` 的 GECKO `web_white_list` 里含 `^https?://minigame\.zijieapi\.com/`（同列表还有 `store.steampowered.com`）

→ **游戏页的 origin 是 `https://minigame.zijieapi.com`（公网），本地资源走 127.0.0.1:5678**

这正是 `file-server.js` 要回 `Access-Control-Allow-Private-Network: true` 的原因：
**公网 origin → 私有地址**会被 Chromium 的 **Private Network Access (PNA)** 拦截。

## 7. 已做过的注入实验与结论

| # | 注入点 | 现象 | 结论 |
|---|---|---|---|
| 1 | `webview-preload.js` 末尾追加探针 | 文件被重写，探针消失 | 该点不可持久化 |
| 2 | `resource/file-server.js` 加中间件（注入 html + 日志 + `/__e0e1__.js`） | 文件被还原 | 该点不可持久化 |
| 3 | `packages/.../0.1.70/game.js` 末尾追加（`require('fs')` 落盘 / localStorage / `document.title`） | **三种落盘痕迹全无** | 通道不可用或代码未执行 |
| 4 | 同上 + `location.href` 跳走 | 游戏**正常进入**，无跳转 | `document` 不可用 → 疑似跑在 Worker |
| 5 | 同上 + `fetch`/`XHR`/`Image` 回连 `127.0.0.1:9999` | 无回连 | 之后才补上 PNA 响应头 |
| 6 | `page-frame.html` 注入内联探针 | 无回连；**HTTP 缓存里查不到 page-frame.html 的请求记录** | 页面外壳不是从这个本地文件加载的 |
| 7 | `game.js` 追加 Worker 友好探针（PNA 头已修） | **未跑完验证**（UI 自动化没打通） | 待验证 |

### 已确证的事实

- `Cache/Cache_Data` 里**能查到被改过的 `game.js` 内容** → game.js 确实被 webview 从 5678 拉过
- `Cache/Cache_Data` 里**查不到** `page-frame.html` / `__e0e1__` → 外壳不来自本地 5678
- 探针 3 的 `document` / `localStorage` / `require('fs')` 全部无效，与「运行在 Worker（`high-performance-game-worker.js`）」一致

### 仍然未知（下一步要回答的）

1. `game.js` 到底是不是执行入口？还是只被拉取做模块预登记（`preload-modules.json` 里**没有**根 `game.js`，只有 `subpackages/*/game.js`）
2. 游戏真实执行上下文：主 frame / iframe / **Worker**？
3. 回连通道：PNA 头修好后，`fetch('http://127.0.0.1:9999/...')` 能否从游戏上下文发出？
4. 若 1 否：真正的入口是哪个文件（`application.9006e.js`？`src/system.bundle.f45da.js`？）

## 8. 可用的回连通道（PNA 感知）

`tools/_e0e1_listen.py` —— 本机 9999 端口 beacon 监听，日志 `Temp/e0e1_beacon.log`。
**必须**在 OPTIONS 预检里回 `Access-Control-Allow-Private-Network: true`，否则公网 origin 页面访问 127.0.0.1 会被 Chromium 拦掉。

## 9. 备用/后续方案（未验证）

1. **改游戏包 JS**：`resource/packages/**` 不会被还原，一旦确认执行入口即可持久注入（最像本工程「解包→改包」的做法）
2. **占坑 `webview-preload.js`**：用 `ReadDirectoryChangesW` 监听，客户端一写入就立刻覆盖补丁（抢在 spawn webview 之前），赢下这个竞态即可每次生效
3. **Frida / DLL 注入**：主进程是 Electron，拿到主进程即可 `webContents.debugger` 自建 CDP，对齐现有架构
4. **MITM**：`sscronet.dll` 走 Cronet，多半有证书固定；但页面资源走 Chromium 栈，可试系统代理 + 自签 CA
5. **`tt.setEnableDebug` / `tt.showVConsole`**：jssdk 里存在（`tmg-core.js`）。注意 `setEnableDebug` 对 `version_type ∈ {preview, latest, audit}` 才生效，release 是 no-op；`showVConsole` 无此限制，但前提是先在页面里执行到代码

## 10. 现场状态

- 所有被改过的文件已**还原为原始内容**（`game.js` 3230B、`page-frame.html` 1025B、`webview-preload.js` 38936B、`file-server.js` 793503B），备份副本 `*.e0e1bak` 仍在同目录
- 排查用脚本在 `tools/`：`asar_list.py`、`asar_extract.py`、`_e0e1_listen.py`、`_win_shot.py`、`_win_list.py`、`_open_game.py`
- 反编译产物在 `output/_re_douyin/main`、`output/_re_douyin/game`
