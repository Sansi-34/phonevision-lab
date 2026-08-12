"""
PhoneVision Lab — PySide6 桌面客户端入口。

职责：解析命令行参数（手机 IP/端口或完整流地址）、用 connection 模块做 /ping
预检、加载 QSS 主题、启动 MainWindow。这是"产品级"客户端的大门。

为什么这样设计：
  - URL 构造与 /ping 预检统一走 pc-client/connection.py（与 Tkinter 入口共用），
    消除双入口的分叉。
  - 支持 `python -m qt_client.main`（包内相对导入），不依赖从特定子目录启动。
  - 保留 Tkinter（`python main.py`）为当前默认入口，本阶段不切换。

初学者调试观察点：
  - 启动报"无法连接手机"：看 connection.ping_device 返回的中文提示。
  - 界面丑/样式不生效：确认 style.qss 存在且编码 utf-8。
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


def parse_args():
    parser = argparse.ArgumentParser(description="PhoneVision Lab 桌面客户端")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--host", help="手机局域网 IP，如 192.168.2.14")
    group.add_argument("--stream-url", help="完整流地址，如 http://192.168.2.14:8080/stream")
    parser.add_argument("--port", type=int, default=8080, help="手机 HTTP 端口（默认 8080）")
    return parser.parse_args()


def main():
    args = parse_args()
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

    win = MainWindow(stream_url, ping_url, ping_info)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
