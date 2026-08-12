"""
PhoneVision Lab — Legacy Tkinter 客户端入口（兼容保留）。

职责：保留 P0-4B 之前的 Tkinter 一体化 GUI 作为"兼容/legacy 客户端"。
PySide6 工作台（python main.py）是正式默认客户端；本入口仅用于需要旧版
界面或调试 Tkinter 路径的场景，不再承担未来默认入口。

为什么这样设计：
  - URL 构造与 /ping 预检统一走 pc-client/connection.py，与 PySide6 入口共用，
    不在此重复实现另一套 URL/ping 逻辑。
  - GUI 本体复用 app_gui.py（PhoneVisionApp），不改其核心行为。
  - 本入口独立存在，不影响 root main.py 的 PySide6 默认入口。

注意：启动前请确认手机已点击"开始推流"并保持前台，且电脑与手机在同一 WiFi。
"""
import argparse
import sys

import connection

# 让 import 能找到 pc-client 根目录下的 app_gui / connection
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app_gui  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="PhoneVision Lab Legacy Tkinter 客户端")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--host", help="手机局域网 IP，如 192.168.2.14")
    group.add_argument("--stream-url", help="完整流地址，如 http://192.168.2.14:8080/stream")
    parser.add_argument("--port", type=int, default=8080, help="手机 HTTP 端口（默认 8080）")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    stream_url, ping_url = connection.build_urls(
        host=args.host, port=args.port, stream_url=args.stream_url)

    result = connection.ping_device(ping_url)
    if not result.success:
        connection.exit_with_error(result.error)
    ping_info = result.info

    print("-" * 50)
    print(f"手机型号     : {ping_info.get('device', '未知')}")
    print(f"分辨率       : {ping_info.get('width', '?')}x{ping_info.get('height', '?')}")
    print(f"手机采集 FPS : {ping_info.get('actualFps', '?')}")
    print(f"状态         : {ping_info.get('status', '?')}")
    print("-" * 50)
    print(f"流地址: {stream_url}")
    print("提示：本入口是 Legacy Tkinter 客户端；正式默认客户端为 PySide6（python main.py）。")
    if ping_info.get("status") != "streaming":
        print("提示：手机当前未在推流，请先在 App 点击\"开始推流\"。")

    app_gui.run(stream_url, ping_url, ping_info)


if __name__ == "__main__":
    main()
