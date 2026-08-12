"""
PhoneVision Lab — 一体化 GUI 的视觉主题（现代简约暗色系）。

职责：集中定义配色、字体、圆角等视觉常量，app_gui.py 只用这里取值，
改主题只需改这个文件，不散落各处。

为什么这样设计：
  - 把"视觉"和"逻辑"分离：app_gui 只关心布局与交互，颜色字体统一从这取。
  - 暗色深灰蓝 + 清爽青蓝主色，减少边框靠留白分层，现代简约。

初学者调试观察点：
  - 想整体换色，只改这里；想换字体，只改 FONT_* 常量。
"""

# ---- 配色 ----
BG = "#0f1115"          # 窗口背景（深灰蓝）
CARD = "#171b22"        # 卡片/面板背景
CARD_ACTIVE = "#1d232d"  # 卡片悬停/激活
INPUT_BG = "#232833"     # 滑块等输入区背景
TEXT = "#e6e9ef"        # 主文本
TEXT_DIM = "#8a94a6"    # 次要文本
TEXT_FAINT = "#5b6472"  # 弱文本

PRIMARY = "#3b82f6"     # 主色（清爽青蓝）
PRIMARY_HOVER = "#5b9af8"
PRIMARY_DIM = "#1e3a5f"
GREEN = "#34d399"       # 成功
AMBER = "#fbbf24"       # 警告
RED = "#f87171"         # 错误

CHIP_BG = "#1d232d"     # 状态栏指标块背景
CHIP_VALUE = "#e6e9ef"  # 指标值
CHIP_LABEL = "#5b6472"  # 指标标签

CANVAS_BG = "#000000"   # 画面区背景（纯黑）
FRAME_BORDER = "#232833"  # 卡片描边（同输入区，弱化边框感）

# ---- 字体 ----
FONT = "Segoe UI"
FONT_SEMIBOLD = "Segoe UI Semibold"
FONT_MONO = "Consolas"

SIZE_TITLE = 11
SIZE_GROUP = 9
SIZE_LABEL = 8
SIZE_CHIP_VALUE = 14
SIZE_CHIP_LABEL = 8
SIZE_STATUS = 9

# ---- 圆角半径 ----
RADIUS = 10
