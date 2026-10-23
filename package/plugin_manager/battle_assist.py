"""控制链配置和独立界面。次数包含第一次手动释放。"""
from __future__ import annotations

import copy
import math

# 与战斗侧支持清单保持一致；时长由战斗侧按实际技能等级计算。
BOOKS = (
    (110100, "铜钱鬼剑", 0), (110200, "断佛手", 0),
    (110300, "玄水瓶", 0), (110400, "风沙琵琶", 2),
    (110500, "火焰山", 0), (110600, "青女", 0),
    (110800, "石敢当", 2), (110900, "业火幡", 2), (111000, "雷公", 2),
    (111200, "风煞阵", 3), (111300, "遣将阵", 0), (111400, "霜轮阵", 0),
    (111500, "万尸瀑", 0), (111600, "傩戏铃", 0), (111700, "黄天令", 0),
)


# 离线显示默认参考：当前配置8阶基础技能；战斗中用本场等级与觉醒替换。
DEFAULT_TIMING = {'110100': (8, 6), '110200': (16, 4), '110300': (20, 4), '110400': (20, 20), '110500': (15, 5), '110600': (18, 6), '110800': (20, 4), '110900': (12, 12), '111000': (20, 3), '111200': (12, 4), '111300': (24, 12), '111400': (20, 6), '111500': (20, 10), '111600': (20, 8), '111700': (40, 10)}


def default_battle_assist():
    return {"enabled": False, "shijue": False, "auto_speed": False,
            "shijue_settings": {"count": 0, "interval": 0.0},
            "zhongkui": {"enabled": False, "show_monsters": True, "monster_count": 5, "unlock_speed": True},
            "books": {str(key): {"enabled": False, "count": count, "interval": 0.0}
                      for key, _, count in BOOKS}}


def validate_battle_assist(raw):
    default = default_battle_assist()
    if raw is None:
        return default
    if not isinstance(raw, dict) or set(raw) - set(default):
        raise ValueError("battle_assist 只接受 enabled/shijue/shijue_settings/auto_speed/books/zhongkui")
    result = copy.deepcopy(default)
    for key in ("enabled", "shijue", "auto_speed"):
        value = raw.get(key, result[key])
        if type(value) is not bool:
            raise ValueError(f"battle_assist.{key} 必须是布尔开关")
        result[key] = value
    setting = raw.get('shijue_settings', {})
    if not isinstance(setting, dict) or set(setting) - {'count', 'interval'}:
        raise ValueError('十绝阵只接受count/interval')
    count, interval = setting.get('count', 0), setting.get('interval', 0.0)
    if type(count) is not int or not 0 <= count <= 10000:
        raise ValueError('十绝阵次数须为0持续或1至10000的整数')
    if type(interval) not in (int, float) or not math.isfinite(interval) or not 0 <= interval <= 3600:
        raise ValueError('十绝阵释放间隔须为0按冷却或0至3600秒')
    result['shijue_settings'] = {'count': count, 'interval': float(interval)}
    zhongkui = raw.get("zhongkui", {})
    if not isinstance(zhongkui, dict) or set(zhongkui) - set(result["zhongkui"]):
        raise ValueError("钟馗伏魔包含未知设置")
    for key, value in zhongkui.items():
        if key == "monster_count":
            if type(value) is not int or not 1 <= value <= 20:
                raise ValueError("怪物显示数量须为1至20的整数")
        elif type(value) is not bool:
            raise ValueError("钟馗伏魔开关须为布尔值")
        result["zhongkui"][key] = value
    books = raw.get("books", {})
    if not isinstance(books, dict) or set(books) - set(result["books"]):
        raise ValueError("控制链包含未知天书")
    for key, value in books.items():
        if not isinstance(value, dict) or not {"enabled", "count"} <= set(value) or set(value) - {"enabled", "count", "interval"}:
            raise ValueError("每本天书只接受 enabled/count/interval")
        if type(value["enabled"]) is not bool or type(value["count"]) is not int or not 0 <= value["count"] <= 20:
            raise ValueError("天书开关须为布尔值，次数须为0自动或1至20的整数")
        interval = value.get("interval", 0.0)
        if type(interval) not in (int, float) or not math.isfinite(interval) or not 0 <= interval <= 3600:
            raise ValueError("施法间隔须为0自动或0至3600秒的有限数值")
        result["books"][key] = {**value, "interval": float(interval)}
    return result


def create_battle_assist_panel(store, *, root=False):
    from PySide6.QtCore import QSignalBlocker
    from PySide6.QtWidgets import QCheckBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QScrollArea, QPushButton, QSpinBox, QDoubleSpinBox, QVBoxLayout, QWidget

    panel = QWidget()
    layout = QVBoxLayout(panel)
    title = QLabel("PVE辅助" if root else "控制链")
    title.setObjectName("panelTitle")
    layout.addWidget(title)
    enabled = QCheckBox("启用PVE辅助")
    enabled.setObjectName("battle_assist.enabled")
    layout.addWidget(enabled)
    auto_speed = None
    if root:
        auto_speed = QCheckBox("解锁3倍速按钮（推关、走阴／肉鸽、鬼门关、酆都战场、诡道深渊）")
        auto_speed.setObjectName("battle_assist.auto_speed")
        auto_speed.setToolTip("需要启用PVE辅助；仅解锁倍率按钮，点击最高档可切换3倍速，也可手动切回其他倍率。不会自动切换或锁定倍率。")
        layout.addWidget(auto_speed)
    note = QLabel("首次手动释放启动该本辅助；再次手动释放停止。次数包含第一次手动释放。\n"
                  "按战斗时间衔接，冷却未好则顺延完整周期；战斗结束清空本场记录。\n"
                  "按本场实际技能（含觉醒）读取冷却与主效果时长；无持续效果时按冷却衔接。\n"
                  "次数选自动时，按本场冷却÷主效果时长向上取整；指定数字则按你的设置。\n"
                  "间隔设为0时自动取 min(主效果时长, 攻击周期÷数量)；也可指定秒数。\n"
                  "青女、霜轮采用基础冰冻时长，实际控制受敌方抗性影响。数量可按阵容调整。")
    note.setWordWrap(True)
    layout.addWidget(note)
    form = QFormLayout()
    layout.addLayout(form)
    fields = {}
    timing_rows = {}
    for key, name, _ in BOOKS:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        toggle, count = QCheckBox("开启"), QSpinBox()
        toggle.setObjectName(f"battle_assist.{key}.enabled")
        count.setObjectName(f"battle_assist.{key}.count")
        count.setRange(0, 20)
        count.setSpecialValueText("自动（按本场等级）")
        count.setSuffix(" 次（含首放）")
        interval = QDoubleSpinBox()
        interval.setObjectName(f"battle_assist.{key}.interval")
        interval.setRange(0, 3600)
        interval.setDecimals(2)
        interval.setSingleStep(0.1)
        interval.setSpecialValueText("释放间隔0秒")
        interval.setPrefix("释放间隔")
        interval.setSuffix("秒")
        interval.setMinimumWidth(120)
        interval.setToolTip("相对上一本的施法时间偏移；0为自动。冷却未好时顺延攻击周期。")
        line.addWidget(toggle)
        line.addWidget(count)
        line.addWidget(interval)
        reset = QPushButton("复位")
        reset.setObjectName(f"battle_assist.{key}.reset_interval")
        reset.setToolTip("将本书的施法偏移 l 恢复为自动计算，保留开关和次数")
        reset.clicked.connect(lambda checked=False, field=interval: field.setValue(0))
        line.addWidget(reset)
        line.addStretch()
        form.addRow(name, row)
        fields[str(key)] = (toggle, count, interval)
    shijue = QCheckBox("显示十绝阵悬浮开关（每场默认关闭）")
    shijue.setObjectName("battle_assist.shijue")
    layout.addWidget(shijue)
    shijue_count = QSpinBox()
    shijue_count.setObjectName('battle_assist.shijue.count')
    shijue_count.setRange(0, 10000)
    shijue_count.setSpecialValueText('持续释放')
    shijue_count.setSuffix(' 次')
    shijue_interval = QDoubleSpinBox()
    shijue_interval.setObjectName('battle_assist.shijue.interval')
    shijue_interval.setRange(0, 3600)
    shijue_interval.setDecimals(2)
    shijue_interval.setSpecialValueText('按冷却释放')
    shijue_interval.setSuffix(' 秒')
    shijue_form = QFormLayout()
    shijue_form.addRow('十绝阵释放次数', shijue_count)
    shijue_form.addRow('十绝阵释放间隔', shijue_interval)
    layout.addLayout(shijue_form)
    hint = QLabel("控制链布好后，在游戏内打开「十绝阵」。以本场首次成功释放为起点，间隔20秒时，首次在13秒释放则在33、53、73…秒检查；冷却或能量不足跳过本轮，等下个整周期。每次打开重新计数；0次表示持续，0秒表示按冷却释放。")
    hint.setWordWrap(True)
    layout.addWidget(hint)
    message = QLabel("")
    message.setWordWrap(True)
    layout.addWidget(message)
    layout.addStretch()

    def refresh_previews():
        for key, (_, count, interval) in fields.items():
            timing = timing_rows.get(key)
            if timing is None:
                period, duration = DEFAULT_TIMING[key]
                interval.setToolTip("默认参考：8阶基础技能；进入对战后按本场等级与觉醒更新。0为自动，复位恢复自动。")
            else:
                period, duration = timing['period'], timing['duration']
                interval.setToolTip("按本场等级与觉醒计算。此值为公式中的 l；冷却未好时顺延完整攻击周期。")
            target = count.value() or max(1, min(20, math.ceil(period / duration)))
            automatic = min(duration, period / target)
            text = f"释放间隔{automatic:g}秒" if automatic == int(automatic) else f"释放间隔{automatic}秒"
            blocker = QSignalBlocker(interval)
            interval.setSpecialValueText(text)
            interval.setMinimumWidth(max(160, interval.fontMetrics().horizontalAdvance(text) + 52))
            del blocker

    def set_timing_preview(rows):
        timing_rows.clear()
        for value in rows:
            if not isinstance(value, dict):continue
            if not all(type(value.get(k)) in (int,float) and math.isfinite(value[k]) and value[k]>0
                       for k in ('period','duration','level')):continue
            timing_rows[str(value.get('id'))] = {**value, 'recommendedCount': max(1,min(20,math.ceil(value['period']/value['duration'])))}
        refresh_previews()

    def sync(state):
        data = state["battle_assist"]
        pairs = [(enabled, data["enabled"]), (shijue, data["shijue"]),
                 (shijue_count, data['shijue_settings']['count']), (shijue_interval, data['shijue_settings']['interval'])]
        if auto_speed is not None:
            pairs.append((auto_speed, data["auto_speed"]))
        for key, (toggle, count, interval) in fields.items():
            pairs.extend([(toggle, data["books"][key]["enabled"]), (count, data["books"][key]["count"]), (interval, data["books"][key]["interval"])])
        for widget, value in pairs:
            blocker = QSignalBlocker(widget)
            widget.setChecked(value) if isinstance(widget, QCheckBox) else widget.setValue(value)
            del blocker
        refresh_previews()

    def save():
        data = {"enabled": enabled.isChecked(), "shijue": shijue.isChecked(),
                "shijue_settings": {'count': shijue_count.value(), 'interval': shijue_interval.value()},
                "auto_speed": auto_speed.isChecked() if auto_speed is not None else store.snapshot()["battle_assist"]["auto_speed"],
                "zhongkui": store.snapshot()["battle_assist"]["zhongkui"],
                "books": {key: {"enabled": toggle.isChecked(), "count": count.value(), "interval": interval.value()}
                          for key, (toggle, count, interval) in fields.items()}}
        try:
            store.set_battle_assist(data)
            message.setText("设置已保存")
        except (OSError, ValueError) as exc:
            message.setText(f"保存失败：{exc}")
            sync(store.snapshot())

    enabled.toggled.connect(save)
    if auto_speed is not None:
        auto_speed.toggled.connect(save)
    shijue.toggled.connect(save)
    shijue_count.valueChanged.connect(save)
    shijue_interval.valueChanged.connect(save)
    for toggle, count, interval in fields.values():
        toggle.toggled.connect(save)
        count.valueChanged.connect(save)
        interval.valueChanged.connect(save)
    store.changed.connect(sync)
    sync(store.snapshot())
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidget(panel)
    scroll.set_timing_preview = set_timing_preview
    return scroll


def create_zhongkui_panel(store):
    from PySide6.QtCore import QSignalBlocker
    from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox, QSpinBox, QFormLayout, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView
    from PySide6.QtCore import Qt
    panel=QWidget();layout=QVBoxLayout(panel)
    title=QLabel("钟馗伏魔");title.setObjectName("panelTitle");layout.addWidget(title)
    master=QCheckBox("启用PVE辅助");master.setObjectName("battle_assist.enabled");layout.addWidget(master)
    widgets={}
    for key,text in (("enabled","启用钟馗伏魔"),("show_monsters","显示最低存活波次的怪物与位置箭头"),("unlock_speed","提前显示并启用3倍加速图标（无需释放15本天书）")):
        box=QCheckBox(text);box.setObjectName("zhongkui."+key);layout.addWidget(box);widgets[key]=box
    count=QSpinBox();count.setRange(1,20);count.setSuffix(" 个");count.setObjectName("zhongkui.monster_count")
    form=QFormLayout();form.addRow("怪物显示数量",count);layout.addLayout(form);widgets["monster_count"]=count
    note=QLabel("仅PvE；怪物列表和加速仅在钟馗伏魔中生效。默认显示5个，死亡后保留2秒。\n游戏内点击圆球展开，点击收起可恢复圆球；展开后选择控制链或钟馗伏魔。\n3倍按钮提前可用，是否切换到3倍由玩家点击决定。")
    note.setWordWrap(True);layout.addWidget(note)
    status=QLabel('等待钟馗伏魔战斗');status.setObjectName('zhongkui.live_status');layout.addWidget(status)
    table=QTableWidget(0,5);table.setObjectName('zhongkui.monsters')
    table.setHorizontalHeaderLabels(['怪物','波次','当前血量 / 总血量','血量比例','状态'])
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
    layout.addWidget(table)
    def set_monster_status(value, stale=False):
        if stale:
            status.setText('连接中断，以下保留最后一次数据（非实时）')
            return
        table.setRowCount(0)
        if not isinstance(value,dict) or not value.get('active'):
            status.setText('等待钟馗伏魔战斗')
            return
        rows=[m for m in value.get('monsters',[]) if isinstance(m,dict)][:20]
        live=[m.get('wave') for m in rows if not m.get('deadUntil') and isinstance(m.get('wave'),(int,float))]
        status.setText(f'最低存活波次：第{min(live):g}波 · 实时同步' if live else
                       '波次配置未匹配' if value.get('waveUnavailable') else '等待怪物入场')
        table.setRowCount(len(rows))
        def number(v):
            return f'{v:,.0f}' if type(v) in (int,float) and math.isfinite(v) else '—'
        for row,m in enumerate(rows):
            ratio=m.get('ratio',0)
            percent=f'{ratio*100:.2f}%' if type(ratio) in (int,float) and math.isfinite(ratio) else '—'
            values=[str(m.get('name','未知怪物')),str(m.get('wave','—')),
                    number(m.get('hp'))+' / '+number(m.get('max')),percent,'已死亡' if m.get('deadUntil') else '存活']
            for col,text in enumerate(values):table.setItem(row,col,QTableWidgetItem(text))
    panel.set_monster_status=set_monster_status
    def sync(state):
        data=state["battle_assist"]
        for widget,value in [(master,data["enabled"]),*[(w,data["zhongkui"][k]) for k,w in widgets.items()]]:
            blocker=QSignalBlocker(widget)
            widget.setValue(value) if widget is count else widget.setChecked(value)
            del blocker
    def save():
        data=store.snapshot()["battle_assist"];data["enabled"]=master.isChecked()
        data["zhongkui"]={k:(w.value() if w is count else w.isChecked()) for k,w in widgets.items()}
        store.set_battle_assist(data)
    master.toggled.connect(save)
    for key,w in widgets.items():
        (w.valueChanged if w is count else w.toggled).connect(save)
    store.changed.connect(sync);sync(store.snapshot());return panel
