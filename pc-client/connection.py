"""
PhoneVision Lab — 连接层（URL 构造与 /ping 预检）。

职责：把 host/port 或 stream-url 解析成 stream 与 ping 的完整 URL，执行带超时的
/ping 请求，返回结构化结果；并把 requests 异常转换成统一的可展示中文错误。

为什么这样设计：
  - Tkinter 与 PySide6 两个入口此前各自实现了一套 parse_args/build_urls/check_ping，
    逻辑几乎逐行相同。抽到这里，一套逻辑两处复用，消除分叉。
  - 本模块只处理"连接"（URL + ping + 错误文案），不含任何 GUI 逻辑，也不 import
    tkinter / PySide6，可被任意界面层安全使用。

初学者调试观察点：
  - 连不上看返回的 error 文案（无法连接/超时/响应异常）。
  - 想改 ping 超时或错误提示，只改这一个文件。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

import requests

# /ping 预检超时（秒）
PING_TIMEOUT = 5.0

# 状态常量（与 mjpeg_reader / app_model 一致）
CONNECTION_CONNECTING = "Connecting"
CONNECTION_STREAMING = "Streaming"
CONNECTION_RECONNECTING = "Reconnecting"
CONNECTION_STOPPED = "Stopped"
CONNECTION_ERROR = "Error"


@dataclass(frozen=True)
class PingResult:
    """/ping 的结构化结果。success=False 时 info 为空、error 有值。"""
    success: bool
    info: dict
    error: str | None = None


def build_urls(host: str | None = None, port: int = 8080,
               stream_url: str | None = None) -> tuple[str, str]:
    """由 host/port 或完整 stream-url 构造 (stream_url, ping_url)。

    若传入 stream_url，自动推导 ping 地址（去掉末尾 /stream 后加 /ping）。
    """
    if stream_url:
        s = stream_url
        if s.endswith("/stream"):
            base = s[: -len("/stream")]
        else:
            base = s.rstrip("/")
            s = f"{base}/stream"
        return s, f"{base}/ping"
    base = f"http://{host}:{port}"
    return f"{base}/stream", f"{base}/ping"


def ping_device(ping_url: str, timeout: float = PING_TIMEOUT) -> PingResult:
    """执行 /ping 预检，返回结构化结果。所有 requests 异常都转成中文文案。"""
    resp = None
    try:
        resp = requests.get(ping_url, timeout=timeout)
        resp.raise_for_status()
        info = resp.json()
        return PingResult(success=True, info=info)
    except requests.exceptions.ConnectionError:
        return PingResult(False, {}, "无法连接手机：请确认手机已推流、与电脑同一局域网、IP/端口正确")
    except requests.exceptions.Timeout:
        return PingResult(False, {}, "连接手机超时：请检查网络后重试")
    except Exception as e:  # noqa: BLE001 - 统一收敛为可展示错误
        return PingResult(False, {}, f"/ping 响应异常：{e}")
    finally:
        if resp is not None:
            resp.close()


def exit_with_error(message: str) -> None:
    """打印错误并退出（供入口在预检失败时使用）。"""
    print(f"错误：{message}")
    sys.exit(1)
