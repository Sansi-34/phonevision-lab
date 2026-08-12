"""
PhoneVision Lab — PC 端一体化 OpenCV 学习客户端入口。

职责：解析命令行参数（手机 IP/端口或完整流地址），检查 /ping，然后启动
Tkinter 一体化 GUI（画面区 + 命令台 + 状态栏）。实际逻辑在 app_gui.py。

为什么这样设计：
  - 把"入口 + 连接检查"与"GUI 界面"分开：main.py 只负责参数与启动，
    app_gui.py 负责界面与实时显示，职责清晰，适合学习。
  - 手机 IP 不硬编码，全部由命令行传入。
  - 用 Tkinter（内置）替代 OpenCV HighGUI：本机 Windows 高 DPI + OpenCV 5.0
    下 HighGUI 的 trackbar 和按键输入失灵，Tkinter 的滑块与按钮更可靠。

初学者调试观察点：
  - 启动报"无法连接手机"：见 check_ping 的中文提示（手机没推流/不在同一 WiFi/IP 错）。
  - GUI 画面不动：看状态栏 state=Reconnecting，说明流断了在等重连。
"""
import argparse
import sys

import requests

import app_gui


def parse_args():
    parser = argparse.ArgumentParser(description="PhoneVision Lab OpenCV 学习客户端")
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
    """启动前访问 /ping，打印手机信息。失败时给出清晰中文错误。"""
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

    print("-" * 50)
    print(f"手机型号     : {info.get('device', '未知')}")
    print(f"分辨率       : {info.get('width', '?')}x{info.get('height', '?')}")
    print(f"请求 FPS     : {info.get('requestedFps', '?')}")
    print(f"手机采集 FPS : {info.get('actualFps', '?')}")
    print(f"状态         : {info.get('status', '?')}")
    print("-" * 50)
    if info.get("status") != "streaming":
        print("提示：手机当前未在推流，请先在 App 点击\"开始推流\"。")
    return info


def main():
    args = parse_args()
    stream_url, ping_url = build_urls(args)

    ping_info = check_ping(ping_url)
    print(f"\n流地址: {stream_url}\n")
    print("启动一体化 GUI...")

    app_gui.run(stream_url, ping_url, ping_info)


if __name__ == "__main__":
    main()
