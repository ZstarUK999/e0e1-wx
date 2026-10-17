# 插件管理器架构整理设计

日期：2026-10-15
范围：入口装配层 + `package/plugin_manager` 内部分层 + `damage_report` 拆包
性质：纯重构。不改动可观察行为（锁文件名、日志路径、报告落盘目录、调度语义均保持原样）。

## 1. 现状与问题

| 文件 | 行数 | 问题 |
| --- | --- | --- |
| `plugin_main.py` | 58 | 入口里同时做进程环境准备、路径编排、对象装配 |
| `package/plugin_manager/runtime.py` | 836 | 单对象承担 CDP 会话、注入、任务调度、摸金、伤害采集、文本渲染、报告落盘 |
| `package/plugin_manager/window.py` | 389 | 窗口装配 + 15 个 `set_*` 转发桩 + 单实例锁 + Chrome 打开逻辑 |
| `package/plugin_manager/damage_report.py` | 1185 | 其中 1000+ 行是 HTML 模板字符串 |

具体缺陷：

1. **启动样板重复**：`plugin_main.py:12-14` 与 `main.py:9-12` 各写一遍 `freeze_support()` + `configure_multiprocessing_for_gui_subprocesses()` + `run_qasync_window()`。
2. **路径知识分散**：配置路径在 `store.default_config_path()`，而锁文件 `plugin-manager.lock`（`plugin_main.py:26`）和日志 `logs/plugin_manager.log`（`:33`）在入口拼接。
3. **双向隐式契约**：入口 `window.runtime_controller = PluginRuntime(window)` 从外部挂属性；`PluginRuntime.__init__` 又回调 `window.attach_runtime()` 写 `window._runtime_attached`；`window.closeEvent`（`window.py:384`）反过来依赖 runtime 写入的 `_shutdown_complete`。
4. **应用名补丁**：`run_qasync_window` 设 `e0e1-wx-gui`，`plugin_main.py:38` 在窗口工厂里再覆盖成 `e0e1-wx-plugins`。
5. **runtime 无边界**：`poll()`（`:698-797`）里 CDP 连接、注入、配置下发、玩家信息、摸金、伤害、调度串行混写；`_render_damage`/`_damage_hint`/`_render_treasure` 是纯渲染逻辑；`_write_damage_report` 是 IO。
6. **模板与逻辑同文件**：`build_html` 用 `HTML_TEMPLATE.replace("__PAYLOAD__", blob)`，模板可独立成模块。

## 2. 目标结构

```
package/runtime/
  launch.py          新增：GUI 启动样板，main.py 与插件管理器共用
  instance_guard.py  新增：QLockFile 单实例（从 window.py 迁出）
  async_app.py       改动：configure_application(app, *, app_name, organization)

package/plugin_manager/
  paths.py           新增：config_dir / config / lock / log 四个路径函数
  logging_setup.py   改动：新增 configure_logging()（root + 文件），start_file_logging 保留
  state.py           新增：RuntimeState 共享状态
  session.py         新增：调试会话 / 进程探测 / CDP 连接 / probe / install / epoch
  automation.py      新增：handlers、到期表、优先级选择、任务执行
  features/
    treasure.py      新增：摸金注入、dump/overlay/status、轮询、渲染
    damage.py        新增：伤害注入、轮询取快照、渲染、报告落盘
  debug_link.py      新增：valid_debug_link / open_chrome
  app.py             新增：PluginApplication 装配
  runtime.py         836 → ~200：信号接线 + poll 编排 + shutdown
  window.py          389 → ~280：删掉 treasure/damage 转发桩与 InstanceGuard/open_chrome
  store.py           改动：路径改从 paths 引入（保留同名 re-export）
  damage_report/
    __init__.py      API 导出（对外签名不变）
    serialize.py     slim / render_csv / 字段常量
    report.py        build_html / write_outputs / describe
    template.py      HTML_TEMPLATE

plugin_main.py       → 3 行壳
main.py              → 改调 package/runtime/launch.py
```

## 3. 分层与接口

### 3.1 启动层 `package/runtime/launch.py`

```python
def run_gui(window_factory, *, app_name: str, organization: str = "e0e1") -> int
```

内部依次：`mp.freeze_support()` → `configure_multiprocessing_for_gui_subprocesses()`
→ `configure_high_dpi_for_qt()` → `QApplication` → `configure_application(app, app_name=...)`
→ qasync 循环 → `install_ctrl_c_shutdown` → 显示窗口并等待退出。

`main.py` 改为 `return run_gui(MainWindow, app_name="e0e1-wx-gui")`；
插件管理器用 `app_name="e0e1-wx-plugins"`，不再需要窗口工厂里覆盖应用名。

### 3.2 路径层 `package/plugin_manager/paths.py`

```python
def config_dir() -> Path                 # <GenericConfigLocation>/e0e1/e0e1-wx-plugins
def default_config_path() -> Path        # config_dir()/"plugins.json"
def lock_path(config_path) -> Path       # 配置同目录/"plugin-manager.lock"
def log_path(config_path) -> Path        # 配置同目录/"logs"/"plugin_manager.log"
```

**落地修正**：锁与日志按"配置路径"派生，而不是固定放在 `config_dir()` 下。
原实现（`plugin_main.py:26,33`）就是取配置文件所在目录，测试也依赖这点
（`test_plugin_gui.py` 断言临时目录下的 `plugin-manager.lock` 不残留）。
改成固定目录后，测试会去抢真实用户目录里的锁——本机当时正好有一个 12:40 启动的
插件管理器实例持有它，入口弹"已有一个实例正在运行"的模态框，测试直接超时。
文件名本身保持原样（锁用连字符、日志用下划线）。

`store.py` 改为 `from .paths import default_config_path`，模块内仍保留该名字，兼容既有引用。

### 3.3 装配层 `package/plugin_manager/app.py`

```python
class PluginApplication:
    def __init__(self, config_path: Path | None = None) -> None
    def run(self) -> int
```

`run()` 流程：

1. `path = self.config_path or default_config_path()`，建父目录
2. `InstanceGuard(default_lock_path())`；`acquire()` 失败 → 弹"已有一个插件管理器实例正在运行"，返回 0
3. `configure_logging(default_log_path())`；日志失败不影响启动
4. `run_gui(self._create_window, app_name="e0e1-wx-plugins")`
5. `finally`：关文件日志、释放锁

`_create_window()`：

```python
store = PluginConfigStore(self.config_path)
window = window_module.PluginWindow(store)
runtime_module.PluginRuntime(window).start()
return window
```

**落地修正**：`window.runtime_controller` 直接删除，没有替代属性。
全仓库只有 `plugin_main.py:40` 写过它，没有任何地方读取（`window.closeEvent` 用的是
`_runtime_attached` / `_shutdown_complete`），属于只写状态。运行服务仍在自己的
`__init__` 里通过 `window.attach_runtime(capabilities)` 登记能力集，关闭流程不变。

**解析方式约束**：装配层通过模块属性取类（`window_module.PluginWindow`、`runtime_module.PluginRuntime`），
不用 `from .window import PluginWindow` 的顶层绑定，保证 monkeypatch 与导入顺序无关。

模块级 `def main(config_path: Path | None = None) -> int` 供 `plugin_main.py` 调用。
异常处理沿用现状：仅 `OSError` / `ValueError` 弹"插件配置加载失败"并返回 1，不覆盖现有配置。

### 3.4 共享状态 `package/plugin_manager/state.py`

现状 `_blocked` / `_blocked_session` / `_installed` / `_epoch` / `_closing` / `_stop_operation`
被 session、automation、features 交叉读写。抽成共享对象，由 `PluginRuntime` 创建并注入各模块：

```python
@dataclass
class RuntimeState:
    closing: bool = False
    stop_operation: bool = False
    blocked: str = ""
    blocked_session: str | None = None
    installed: str | None = None
    configured: dict | None = None
    epoch: tuple | None = None
```

features 只读 `installed` / `closing`；session 写 `installed` / `epoch`；automation 读写 `blocked`。

### 3.5 会话层 `session.py`

承接 `runtime.py` 的 `_ensure_debug_session`、`wechat_ready` 进程探测、transport 连接/重连、
probe、install、epoch 变更检测（`_on_state` 中 invalidate 的那段）。

```python
@dataclass(frozen=True)
class SessionStatus:
    available: bool
    cdp_port: int | None
    epoch: tuple | None
    appid: str | None
    ready: bool
    resident_id: str | None

class GameSession:
    def __init__(self, service, transport, state, *, process_ready=wechat_ready)
    def request_debug(self) -> None          # 含重试计数与间隔
    def note_engine_state(self, state) -> bool   # 会话变更返回 True（原 _on_state 的 invalidate）
    async def connect(self) -> None
    async def probe(self) -> dict
    async def install(self) -> str
    def mark_installed(self, resident_id, epoch) -> None
    def invalidate(self) -> None
    def stale(self, epoch) -> bool
    @property
    def connected(self) -> bool
```

### 3.5.1 游戏操作封装 `resident.py`

`ResidentGame`（原 `runtime.py:55-100`）迁到独立模块：automation 需要它构造任务处理器，
而 runtime 又持有 automation，留在 runtime 里会形成循环 import。

### 3.6 调度层 `automation.py`

承接 `_new_handlers`、`_task_due`、优先级选择（`runtime.py:783-793`）、
`_begin_task` / `_run_task` / `set_automation`。

```python
class AutomationScheduler:
    def __init__(self, transport, state, view, store)
    def reset_handlers(self) -> None
    def capabilities(self) -> set[str]
    def set_automation(self, running: bool) -> None
    def begin(self, task_id, *, manual: bool = False) -> None
    async def run(self, context, manual: bool) -> None
    def pick(self, now, due) -> str | None
    async def wait_operation(self) -> None
    @property
    def operation(self)
```

### 3.7 功能层 `features/`

两个 feature 只依赖 `panels` 字典与 `transport`，不依赖 `QMainWindow`：

```python
class TreasureFeature:
    def __init__(self, transport, state, panel)      # panel = window.pages["treasure"]
    async def ensure_injected(self) -> None
    async def handle(self, op, args) -> None         # dump / overlay / status
    async def poll(self, config) -> None
    @staticmethod
    def render(dump) -> tuple[str, str]

class DamageFeature:
    def __init__(self, transport, state, panel, store)
    async def ensure_injected(self) -> None
    async def handle(self, op, args) -> None         # refresh / debug / reset / stop
    async def poll(self, config) -> None
    async def take(self, *, force=False) -> None
    def status_text(data) -> str
    def hint(data) -> str
    def summary(data) -> str
    def write_report(data, label) -> None
```

`panels.py` 已实现 `set_map` / `set_message` / `set_enabled` / `set_ready` / `set_status` /
`set_hint` / `set_summary` / `set_report_path`，feature 直接调用，无需新增方法。

### 3.8 窗口层 `window.py` 瘦身

删除：`InstanceGuard`（迁 `runtime/instance_guard.py`）、`valid_debug_link` / `open_chrome`
（迁 `debug_link.py`）、以及 9 个转发桩
`set_treasure_map` / `set_treasure_message` / `set_treasure_ready` /
`set_damage_ready` / `set_damage_status` / `set_damage_hint` / `set_damage_summary` /
`set_damage_message` / `set_damage_report_path`。

保留（会话级，由 runtime / automation 使用）：`set_connection`、`set_automation_running`、
`set_automation_ready`、`set_operation_running`、`set_debug_link`、`set_player_information`、
`set_offset_detecting`、`attach_runtime`、`finish_test`、`reset_session`、`complete_shutdown`、
`action_label`、`task_panels`、`pages`。

`_open_damage_report` 保留在窗口（面板信号 → 打开文件），`chrome_opener` 保留为可替换属性。

### 3.9 协调层 `runtime.py`

只留：信号接线、`poll()` 编排、`request_shutdown` / `shutdown` / `wait_closed`、`_on_config`。
编排顺序沿用现状：进程探测 → 调试会话 → 连接 → probe → appid 校验 → install → 配置下发
→ 调试链接/连接状态 → 玩家信息 → 摸金 → 伤害 → 摘要 → 调度。

**正确性约束**：现状在每次 `await` 之后重新比对 epoch 才改 UI 或发命令
（`runtime.py:747, 763, 771, 778`）。重写时必须保留每个检查点，统一走 `session.stale(epoch)`，
不得因为"看起来冗余"而删除。

### 3.10 `damage_report` 拆包

拆成 `serialize.py` / `report.py` / `template.py`，`__init__.py` 导出
`slim` / `render_csv` / `describe` / `write_outputs` / `build_html`。
模板留在 Python 模块内（不用独立 `.html` 资源），避免打包时的数据文件配置。
`tools/damage_curve_report.py:35` 的 import 语句无需修改。

## 4. 迁移步骤

每步结束时仓库必须可运行（不存在中间态 import 失败）。

1. 新增 `runtime/launch.py`、`runtime/instance_guard.py`、`plugin_manager/paths.py`；
   扩展 `logging_setup.configure_logging`；新增 `app.py`；`plugin_main.py` 壳化；`main.py` 改调 launch。
   → 验证：`tools/test_plugin_gui.py`
2. `damage_report.py` 拆包，API 不变。
   → 验证：`tools/damage_curve_report.py`、`grep -rn damage_report`
3. 新增 `debug_link.py`；`window.py` 迁出 `InstanceGuard` 与 Chrome 逻辑（先加后删，同步更新 import）。
   → 验证：`tools/test_plugin_gui.py`
4. 新增 `state.py`；迁出 `features/treasure.py`、`features/damage.py`；runtime 改为委托。
   → 验证：`tools/test_plugin_runtime.py`、`tools/test_plugin_gui.py`
5. 迁出 `session.py`、`automation.py`；重写 `runtime.poll()` 为编排；
   删除 `window.py` 的 9 个转发桩。
   → 验证：`tools/test_plugin_runtime.py`、`tools/test_plugin_gui.py`
6. 全量跑 `tools/test_*.py`，手动冒烟启动一次插件管理器。

## 5. 实际调整过的测试

| 位置 | 原状 | 调整 |
| --- | --- | --- |
| `test_plugin_gui.py` 入口断言 | 断言 `inspect.getsource(plugin_main.main)` 含 `"package.plugin_manager.window"` | 改为断言入口壳引用 `package.plugin_manager.app`、装配方法引用 `window_module.PluginWindow`，且不含 `MainWindow` |
| `test_plugin_gui.py` 两个 subprocess 入口测试 | monkeypatch `store.default_config_path` | 改为 `plugin_main.main(path)` 传参 |
| `test_plugin_gui.py` 单实例锁两处 | `w.InstanceGuard`（window 模块） | 改为 `package.runtime.instance_guard.InstanceGuard` |
| `test_plugin_runtime.py` | `c._blocked` / `c._installed` / `c._blocked_session` | 改为 `c.state.*` |
| `test_plugin_runtime.py` | `c.set_automation()` / `c.operation` / `c.automation`（布尔） | 改为 `c.automation.set_automation()` / `c.automation.operation` / `c.automation.running` |
| `test_plugin_runtime.py` | `c.process_ready` / `c._next_debug_retry` / `runtime_module.DEBUG_MAX_RETRIES` | 改为 `c.session.*` 与 `session_module.DEBUG_MAX_RETRIES` |
| `test_plugin_gui.py` 两条陈旧断言 | 树节点缺 `PVP伤害分析`、配置键缺 `damage`（改动前就红） | 按当前界面与 schema 修正 |

新增 `tools/test_plugin_features.py`（6 条）：摸金渲染与轮询、未就绪时的回执、
伤害采集关闭开关即停止、战斗结束落盘报告、跳过战斗的提示分支。

## 6. 落地结果

| 文件 | 前 | 后 |
| --- | --- | --- |
| `plugin_main.py` | 58 | 12（壳） |
| `plugin_manager/runtime.py` | 836 | 226 |
| `plugin_manager/window.py` | 389 | 328（另删 9 个转发桩） |
| `plugin_manager/damage_report.py` | 1185 | 拆为 template 1048 / serialize 81 / report 59 |
| 新增 | — | `app.py` `paths.py` `state.py` `session.py` 127 `automation.py` `resident.py` `debug_link.py` `features/treasure.py` 109 `features/damage.py` 329 |

测试：`tools/` 全量 357 通过（含新增 6 条），改动前基线为 62 通过 / 2 失败，
那 2 条是陈旧断言，已按当前界面修正。

## 7. 非目标

- 不改行为：报告仍写到 `Path("logs")`，锁文件名、日志路径、配置 schema、调度语义均不变。
- 不动 `panels.py`（配置面板内部）、`transport.py`（CDP 协议）、`package/daily_tasks/*`（任务实现）。
- 不引入新的第三方依赖、不改打包配置。
- 不处理 `package/ui/main_window.py` 主工具的内部结构。
