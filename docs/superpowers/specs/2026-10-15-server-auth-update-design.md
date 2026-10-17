# 插件服务器：登录鉴权与软件更新

日期：2026-10-15
状态：待审阅

## 目标

为本地插件（`e0e1-wx-plugins`，Windows exe）提供一个服务器，只做两件事：

1. **登录鉴权**：校验"包里绑定的玩家 ID"与"游戏里实际登录的玩家 ID"一致，且该 ID 在白名单内。
2. **软件更新**：文件级增量下发 exe 与资源。

非目标（本期不做）：付费、多租户、聊天、数据统计看板、客户端源码强保护。

## 已确认的决策

| 项 | 决定 |
| --- | --- |
| 服务形态 | 单进程双协议：uvicorn(FastAPI) + grpc.aio 并行，共享 domain 层与数据库 |
| 传输加密 | 自签 CA 双向 TLS（mTLS），客户端证书所有玩家共用一份随包分发 |
| 鉴权严格度 | 白名单 + 绑定锁死，**不绑机器指纹**（游戏自带顶号机制） |
| 在线维持 | **无心跳**：启动时一次性握手校验，运行期间不重验 |
| 离线 | 握手失败即不可用；握手成功后进程存活期间不再校验 |
| 解绑 | 不需要（不绑机器） |
| 公会名 | 只上报记录，不参与校验 |
| 更新粒度 | exe + 资源整体更新，走文件级清单 diff |
| 强制更新 | 只有开关，不设最低版本门槛 |
| 发布渠道 | 单一渠道，不分 beta（每个玩家的包各自绑定，灰度无意义） |
| 更新体验 | 启动静默下载，就绪后提示重启 |
| 版本号 | 构建时 `--version` 手填，写进产物的 build.json |
| 构建模式 | `--mode debug`（不连后台，默认）/ `release`（连后台做鉴权与更新） |

## 发布与分发：三层产物

分发包是**一人一份**的（各自绑定 player_id），所以"发布物"分三层，不能混：

```
1. 构建（通用，一次）
   build_exe.py --mode release --version 1.2.0 --target host:port --package
   → dist/e0e1-wx-plugins/              所有玩家共用，不含身份信息
   → dist/e0e1-wx-plugins-1.2.0-upload.zip   上传后台用

2. 出包（一人一份，两条路任选）
   A. 命令行：build_exe.py --skip-build --version 1.2.0 --player-id 10086 --package
      （用后台那把私钥就地签发 license 并打进包，不用去后台点）
   B. 后台网页：玩家列表点"下载分发包"
      （服务端把当前生效版本的文件 + 新签 license 压好，直接下载）

绑定发生在 **PyInstaller 之后、打 zip 之前**，不需要为每个人重新 PyInstaller。
两条路共用 `domain/license.py` 的签发逻辑和同一把私钥，产物格式一致。

### 为什么 license 必须签名

不签名的话，任何人都能用记事本给自己造一个写着自己 ID 的 license，
`bound == login` 天然成立，白名单在在线模式下也形同虚设。签名保证
**只有持有私钥的一方（后台／构建机）能签发**，白名单裁决才有意义。
（离线兜底那部分已经放弃了白名单，这是既定的取舍。）

**坑**：diff 以服务器清单为准，本地扫描到的 `license.bin` 不在清单里会被判成"多余文件"删掉，
所以本地上报清单必须排除 `license.bin`、`_staging/`、`logs/`。

## 威胁模型

本地校验只是第一道防线，最终裁决在服务器：客户端即使被 patch，也拿不到服务器签发的放行结果。

| 攻击 | 应对 |
| --- | --- |
| 改 license 里的 player_id | Ed25519 签名覆盖 player_id，改了就验签失败 |
| 自己伪造 license | 插件只内置公钥，私钥只在服务器 |
| 借别人的包 | 包内 bound_player_id 与游戏内 heroId 不符 |
| 整包拷贝给别人 | 不额外防御，依赖游戏自带顶号机制 |
| 断网绕过 | 握手失败即不可用 |

## 目录结构

```
server/
├── backend/
│   ├── app/
│   │   ├── main.py            # 装配：FastAPI + gRPC 同进程启停
│   │   ├── settings.py        # 端口、DB、证书、密钥路径
│   │   ├── db/                # SQLAlchemy 2.0 + SQLite
│   │   ├── domain/            # 协议无关业务层
│   │   │   ├── license.py     # Ed25519 签发与校验
│   │   │   ├── auth.py        # 握手校验链
│   │   │   └── updates.py     # 版本清单与 diff
│   │   ├── http/              # 管理端 API + 更新文件下载
│   │   └── grpc/              # proto 与 servicer
│   ├── certs/                 # 自签 CA / server / client 证书（不入库）
│   ├── tools/gen_certs.py     # 证书签发脚本
│   └── requirements.txt
└── web/                       # 零构建原生 JS，由 FastAPI 静态托管
```

## 数据模型

- `players`：`player_id`(unique，游戏内 heroId)、`nickname`、`guild`(最近上报的阴司名)、`note`、`enabled`、`created_at`
- `handshake_logs`：`player_id`、`bound_player_id`、`guild`、`client_version`、`ip`、`allowed`、`reason`、`created_at`
- `releases`：`version`(unique)、`changelog`、`mandatory`、`enabled`、`created_at`
- `release_files`：`release_id`、`path`(相对 app 根)、`sha256`、`size`
- `admins`：`username`、`password_hash`(bcrypt)

不建 `licenses` 表：license 是无状态签名凭证，吊销靠 `players.enabled`，签发动作记在后台操作日志里即可。

## license 格式

```json
{
  "license_id": "L-2026-0001",
  "player_id": "12345678",
  "issued_at": "2026-10-15T00:00:00Z",
  "nonce": "随机串",
  "signature": "base64(Ed25519 签名)"
}
```

签名覆盖 `license_id|player_id|issued_at|nonce`。文件放 **exe 同级目录**（不在 `_internal` 内），
这样一次构建可以复用 N 份 license，且更新替换 `_internal` 时不会冲掉它。

## gRPC 接口

```proto
service PluginService {
  rpc Handshake(HandshakeRequest) returns (HandshakeResponse);
  rpc CheckUpdate(UpdateRequest) returns (UpdateResponse);
}
```

`HandshakeRequest`：`license`(整份 license 内容)、`login_player_id`、`guild_name`、`client_version`、`nonce`、`timestamp`

`HandshakeResponse`：`allowed`、`reason`、`server_time`、`latest_version`、`update_required`

`UpdateRequest`：`client_version`、`files`(本地 `path` + `sha256` 清单)

`UpdateResponse`：`version`、`mandatory`、`changed_files`(`path`/`sha256`/`size`/`url`)、`removed_files`(`path`)

### 校验链（`Handshake`，顺序即短路顺序）

1. license 的 `signature` 有效 → 否则拒绝
2. `license.player_id == login_player_id` → 否则拒绝
3. `player_id` 在 `players` 且 `enabled` → 否则拒绝
4. 落 `handshake_logs`，返回放行 + 最新版本信息

### 后台连不上时的离线兜底

服务器挂了不能让玩家用不了插件，所以客户端在**连不上后台**时退化为纯本地判定：

1. **先验签**（客户端内置 Ed25519 公钥）
2. 包里绑定的 `player_id` == 游戏登录 id → 放行（`reason=offline_ok`）
3. 验签失败或 id 不一致 → 拒绝并**直接退出程序**

第 1 步不能省：license 是明文 JSON，只比对 id 的话，别人拿到包把 `player_id`
改成自己的号就能离线白用。客户端只持有公钥，所以能验不能签。

验签用 `package/plugin_manager/ed25519.py`（纯 Python，无第三方依赖，
启动时只跑一次约 125ms）。公钥烧在 `license.py` 的常量里而不是数据文件——
改 JSON 比改代码容易太多。换密钥时用 `server/backend/tools/show_pubkey.py` 取新值。

### 残余风险

- 逆向 exe 跳过校验、或把内置公钥换成攻击者自己的：需要改二进制，
  比改 JSON 高一个量级，但挡不住执着的逆向者（本地永远只是第一道防线）。
- 屏蔽服务器仍能绕过**白名单**（本地比对只看签名和 id）：已知并接受的取舍。

未通过鉴权（无论来自后台还是本地兜底）都弹提示后退出，不留半可用状态。

代价：屏蔽服务器（改 hosts / 断网）就能绕过白名单吊销，只剩"绑定 id 对得上"这一条。
这是"可用性优先"的取舍，已确认接受。

## 更新流程

1. 后台上传构建产物 zip → 服务端解压到 `releases/<version>/`，递归算 sha256 生成 `release_files`
2. 插件启动后 `CheckUpdate`，上报本地 app 目录的文件 hash 清单
3. 服务端 diff：hash 不同或缺失的进 `changed_files`，本地多出来的进 `removed_files`
4. 插件下载变更文件到 `<app>/_staging/<version>/`，逐个校验 sha256
5. 校验通过后生成 `apply_update.cmd`，提示用户重启；确认后插件退出，脚本把 staging 覆盖到 app 目录并重新拉起插件

`mandatory=true` 时 `Handshake` 直接返回 `update_required`，插件禁用自动化。

`license.bin` 位于 exe 同级、不在清单管理范围内，永远不被更新覆盖。

## mTLS

`tools/gen_certs.py` 生成自签 CA、server 证书（SAN 含服务器域名/IP）、client 证书。
gRPC 服务端强制校验客户端证书；client 证书随 app 目录分发（所有玩家共用一份，防的是"随便写个脚本直连"，
不防玩家本人；若将来要单人吊销，改为按 license 单独签发证书）。

## 前端页面（原生 JS，4 个视图）

登录 · 玩家白名单（增删改 / 启停 / 签发并下载 license.bin）· 握手日志（审计）· 版本发布（上传 zip、填版本与更新日志、强制开关、启用停用）

## 构建模式

`build_exe.py --mode debug|release`，产物内置 `build.json`（mode / version / target）：

- **debug（默认）**：不带证书、不带 gRPC（`--exclude-module grpc`），握手直接放行，不做更新检查。
  源码运行也走这条（没有 build.json）。
- **release**：打包客户端证书与 gRPC，启动后握手校验 + 更新检查，连不上后台即不可用（fail closed）。

客户端不验签（避免为此在包里塞 cryptography），license 原样发给服务器，裁决全在服务器。

## 插件侧改动

- 新增 `package/plugin_manager/license.py`：读 exe 同级 `license.bin`（不验签，交给服务器）
- 新增 `package/plugin_manager/server_client.py`：gRPC stub + mTLS 凭证 + 失败退避
- `package/plugin_manager/runtime.py`：启动时握手，失败则禁用任务调度并在界面提示原因
- `package/plugin_manager/panels.py`：显示绑定玩家 ID、版本、更新提示

绑定 ID 的唯一来源是 `license.bin`，**不写进 `plugins.json`**：避免两处状态不一致，
也就不必改 `store.py:107` 那段写死的 `player` 白名单。

## 测试

- `domain/license.py`：签名有效 / 篡改 player_id / 换签名
- `domain/auth.py`：校验链四条分支各一例
- `domain/updates.py`：diff 出增删改三类文件
- gRPC servicer：用测试证书起服务端跑一次真实握手
- 打包脚本产物：握手失败时插件能正常启动并给出提示（不崩）

## 未包含

- 付费 / 订阅 / 激活码
- 客户端源码保护（Nuitka / pyarmor）
- 多机互踢与在线会话管理（游戏自带顶号）
- 薄启动器（当前更新靠 `apply_update.cmd` 完成替换，启动器留作后续）
