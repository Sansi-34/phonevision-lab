"""
PhoneVision Lab — PySide6 桌面客户端入口。

职责：解析命令行参数（手机 IP/端口或完整流地址）、检查 /ping 确认手机在线、
加载 QSS 主题、启动 MainWindow。这是"产品级"客户端的大门。

为什么这样设计：
  - main.py 只做"参数 + 连接检查 + 启动"，UI 全在 main_window.py，职责清晰。
  - 用 QSS 样式表（style.qss）实现产品级外观，代码与视觉分离。

初学者调试观察点：
  - 启动报"无法连接手机"：看 check_ping 的中文提示。
  - 界面丑/样式不生效：确认 style.qss 存在且编码 utf-8。
"""
import os
import sys

# 让 import 能找到 pc-client 根目录下的 mjpeg_reader / vision_modes
_PC_CLIENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

import argparse
import requests

from PySide6.QtWidgets import QApplication

from main_window import MainWindow


def parse_args():
    parser = argparse.ArgumentParser(description="PhoneVision Lab 桌面客户端")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--host", help="手机局域网 IP，如 192.168.2.14")
    group.add_argument("--stream-url", help="完整流地址，如 http://192.168.2.14:8080/stream")
    parser.add_argument("--port", type=int, default=8080, help="手机 HTTP 端口（默认 8080）")
    return parser.parse_args()


def build_urls(args):
    """由参数构造 stream 和 ping 的 URL。"""
    if args.stream_url:
        stream_url = args.stream_url
        if stream_url.endswith("/stream"):
            base = stream_url[: -len("/stream")]
        else:
            base = stream_url.rstrip("/")
            stream_url = f"{base}/stream"
    else:
        base = f"http://{args.host}:{args.port}"
        stream_url = f"{base}/stream"
    return stream_url, f"{base}/ping"


def check_ping(ping_url):
    """启动前访问 /ping，打印手机信息。失败给出清晰中文错误。"""
    print(f"正在检查手机服务: {ping_url} ...")
    resp = None
    try:
        resp = requests.get(ping_url, timeout=5)
        resp.raise_for_status()
        info = resp.json()
    except requests.exceptions.ConnectionError:
        print("错误：无法连接手机。请确认：")
        print("  1. 手机 App 已点击\"开始推流\"（状态为推流中）")
        print("  2. 电脑和手机在同一 WiFi 局域网")
        print("  3. IP/端口填写正确（手机 App 界面上显示）")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("错误：连接手机超时。请检查网络后重试。")
        sys.exit(1)
    except Exception as e:
        print(f"错误：/ping 响应异常：{e}")
        sys.exit(1)
    finally:
        if resp is not None:
            resp.close()

    print(f"手机: {info.get('device', '?')}  {info.get('width', '?')}x{info.get('height', '?')}  "
          f"采集FPS:{info.get('actualFps', '?')}  状态:{info.get('status', '?')}")
    if info.get("status") != "streaming":
        print("提示：手机当前未在推流，请先在 App 点击\"开始推流\"。")
    return info


def main():
    args = parse_args()
    stream_url, ping_url = build_urls(args)
    ping_info = check_ping(ping_url)
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
