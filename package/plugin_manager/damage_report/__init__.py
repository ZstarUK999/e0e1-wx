"""战斗／PVP 伤害报告的渲染：HTML 模板、载荷压缩与 CSV。

插件管理器和 tools/damage_curve_report.py 共用这一份，改模板只需要动这里。
渲染逻辑拆在 serialize.py（字段与 CSV）、report.py（渲染与落盘）、template.py（模板）。
"""

from .report import build_html, describe, write_outputs
from .serialize import render_csv, slim
from .template import HTML_TEMPLATE

__all__ = ["build_html", "describe", "render_csv", "slim", "write_outputs", "HTML_TEMPLATE"]
