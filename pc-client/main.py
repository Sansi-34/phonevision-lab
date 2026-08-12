"""
PhoneVision Lab — 正式默认客户端入口（PySide6 视觉工作台）。

职责：薄入口，委托 qt_client.main 启动 PySide6 工作台。
本文件不复制 URL 构造 / /ping 预检 / GUI 逻辑，全部由
qt_client.main（复用 connection.py）承担。不 import tkinter / app_gui / requests。

为什么这样设计：
  - PySide6 工作台是正式默认客户端（视觉工作台布局、双语、参数按模式过滤）。
  - Tkinter 旧版界面保留为兼容入口：python legacy_main.py。
  - 保持 `python main.py --host <手机IP>` 这一最简启动方式不变。

常用命令：
  python main.py --host 192.168.x.x            # 中文界面（按系统/保存语言）
  python main.py --host 192.168.x.x --lang en  # 英文界面
  python legacy_main.py --host 192.168.x.x     # Legacy Tkinter 客户端
"""
import os
import sys

# 让 import 能找到 pc-client 根目录下的模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qt_client.main import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
