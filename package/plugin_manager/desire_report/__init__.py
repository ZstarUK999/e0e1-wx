"""三尸合成报告：读日志 → 离线单文件 HTML（表格 + 直方图，无第三方依赖）。"""

from .aggregate import TYPE_KIND, TYPE_NAMES, batches_of, build_payload, failure_gaps, load_records, summarize
from .report import build_html, describe, write_outputs
from .template import HTML_TEMPLATE

__all__ = ["TYPE_KIND", "TYPE_NAMES", "HTML_TEMPLATE", "batches_of", "build_html", "build_payload",
           "describe", "failure_gaps", "load_records", "summarize", "write_outputs"]
