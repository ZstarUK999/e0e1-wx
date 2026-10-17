"""插件管理器里的可选功能：只依赖 transport 与面板，不依赖主窗口。"""

from .damage import DamageFeature
from .desire import DesireFeature
from .season import SeasonFeature
from .treasure import TreasureFeature

__all__ = ["DamageFeature", "DesireFeature", "SeasonFeature", "TreasureFeature"]
