"""
PhoneVision Lab — PySide6 桌面客户端入口（正式默认）。

职责：解析命令行参数（手机 IP/端口或完整流地址、语言）、用 connection 模块做
/ping 预检、加载 QSS 主题、初始化 Translator 与全局字体、启动 MainWindow。
这是"产品级"客户端的大门，也是 root main.py 委托的对象。

为什么这样设计：
  - URL 构造与 /ping 预检统一走 pc-client/connection.py（与 Legacy Tkinter 入口共用）。
  - 支持 `python -m qt_client.main`（包内相对导入），不依赖从特定子目录启动。
  - root `python main.py` 是默认入口，本模块是其委托实现。
  - 语言解析：--lang 命令行 > QSettings 保存 > 系统 locale；首次启动按系统 locale 选择。

常用命令：
  python main.py --host 192.168.x.x            # 中文（按系统/保存）
  python main.py --host 192.168.x.x --lang en  # 英文
  python -m qt_client.main --host 192.168.x.x --lang zh-CN
"""
import os
import sys

# 让 import 能找到 pc-client 根目录下的 mjpeg_reader / vision_modes / app_model
_PC_CLIENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

import argparse

from PySide6.QtWidgets import QApplication

import connection
from qt_client.main_window import MainWindow


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="PhoneVision Lab 桌面客户端（PySide6 工作台）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--host", help="手机局域网 IP，如 192.168.2.14")
    group.add_argument("--stream-url", help="完整流地址，如 http://192.168.2.14:8080/stream")
    parser.add_argument("--port", type=int, default=8080, help="手机 HTTP 端口（默认 8080）")
    parser.add_argument("--lang", choices=["zh-CN", "en"], default=None,
                        help="界面语言：zh-CN 或 en（默认按系统/保存语言）")
    return parser.parse_args(argv)


def _system_language() -> str:
    """按系统 locale 推断语言：含 zh 前缀 -> zh-CN，否则 en。"""
    try:
        import locale
        loc = locale.getlocale()[0] or locale.getdefaultlocale()[0] or "en_US"
    except Exception:
        loc = "en_US"
    return "zh-CN" if str(loc).lower().startswith("zh") else "en"


def main(argv=None):
    args = parse_args(argv)
    stream_url, ping_url = connection.build_urls(
        host=args.host, port=args.port, stream_url=args.stream_url)

    result = connection.ping_device(ping_url)
    if not result.success:
        connection.exit_with_error(result.error)
    ping_info = result.info
    print(f"手机: {ping_info.get('device', '?')}  "
          f"{ping_info.get('width', '?')}x{ping_info.get('height', '?')}  "
          f"采集FPS:{ping_info.get('actualFps', '?')}  状态:{ping_info.get('status', '?')}")
    if ping_info.get("status") != "streaming":
        print("提示：手机当前未在推流，请先在 App 点击\"开始推流\"。")
    print(f"流地址: {stream_url}")

    app = QApplication(sys.argv)

    # 加载 QSS 主题
    qss_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.qss")
    try:
        app.setStyleSheet(open(qss_path, encoding="utf-8").read())
    except FileNotFoundError:
        print("警告: 找不到 style.qss，使用默认外观。")

    # 语言解析：--lang > QSettings 保存 > 系统 locale
    from qt_client.i18n import Translator
    tr = Translator(initial_language="zh-CN")
    saved = tr.language()  # Translator 构造时若 QSettings 有保存值会优先
    cli = args.lang
    system = _system_language()
    lang = tr.resolve_initial_language(cli, saved, system)
    tr.set_language(lang, persist=False)

    # 全局字体：中文避免方框字
    from qt_client.fonts import apply_application_font
    apply_application_font(app, lang)

    win = MainWindow(stream_url, ping_url, ping_info, translator=tr)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
