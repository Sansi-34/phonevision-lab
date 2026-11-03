"""
PhoneVision Lab Web — 通用工具（JSON 响应、错误类型、路径校验）。

职责：给 web/server 下的所有处理器提供统一的小工具，避免每个模块重复写
"读 body / 回 JSON / 转错误"。

为什么这样设计：
  - web 服务不引入任何第三方 Web 框架（FastAPI/Flask 均未安装，也不为第一版
    新增依赖）：全部基于标准库 http.server，路由与 JSON 编解码集中在这里，
    行为可预测、可离线运行、可被现有 Python 测试直接驱动。
  - 错误一律结构化（ok=false + code + message），前端据此区分
    "未连接 / 环境不可用 / 参数错误 / 服务器内部错误"，不把堆栈抛给用户。
  - 所有用户可见文案用简体中文；英文键名留给后续 i18n（见 web/README.md）。
"""
from __future__ import annotations

import ipaddress
import json
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler

# 单次请求体上限（1 MB）：训练参数、连接参数都很小，超出视为异常请求。
MAX_BODY_BYTES = 1024 * 1024

# 允许访问本服务的回环主机名（Host / Origin 校验共用）。
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# 所有响应统一附加的浏览器侧防护头。
SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Content-Security-Policy", "frame-ancestors 'none'"),
    ("Referrer-Policy", "no-referrer"),
)

# 错误码（前端按 code 决定展示方式，不解析 message 文案）。
ERR_BAD_REQUEST = "bad_request"
ERR_NOT_FOUND = "not_found"
ERR_NOT_CONNECTED = "not_connected"
ERR_NO_DATASET = "no_dataset"
ERR_NO_FRAME = "no_frame"
ERR_TRAIN_ENV = "train_env_unavailable"
ERR_BUSY = "busy"
ERR_DEVICE = "device_error"
ERR_INTERNAL = "internal_error"
ERR_FORBIDDEN = "forbidden"


class ApiError(Exception):
    """带错误码的可展示错误。handler 捕获后统一转成 {ok: false, ...}。"""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _server_port(handler: BaseHTTPRequestHandler) -> int | None:
    """取当前服务真实监听端口（Origin 校验用）；测试假 handler 返回 None。"""
    server = getattr(handler, "server", None)
    address = getattr(server, "server_address", None)
    if not address:
        return None
    try:
        return int(address[1])
    except (IndexError, TypeError, ValueError):
        return None


def is_loopback_origin(origin: str, port: int | None = None) -> bool:
    """Origin 是否属于本机回环来源（http + 回环主机 + 同一端口）。

    本服务只提供 http；https 来源不可能与本进程同端口共存，也不该被
    当成同源。Origin 为 null（sandbox / file://）或任意外部站点一律 False。
    """
    if not origin:
        return False
    try:
        parsed = urllib.parse.urlsplit(origin)
    except ValueError:
        return False
    if parsed.scheme != "http":
        return False
    try:
        host = (parsed.hostname or "").lower()
        origin_port = parsed.port
    except ValueError:
        return False
    if host not in LOOPBACK_HOSTS:
        return False
    if origin_port is None:
        origin_port = 80
    if port is not None and origin_port != int(port):
        return False
    return True


def cors_headers(handler: BaseHTTPRequestHandler) -> list[tuple[str, str]]:
    """按请求 Origin 生成 CORS 头：只回显同源回环 Origin，绝不使用 *。

    跨站请求在 app._guard_request 里已经被 403 拦掉，这里再独立判断一次，
    避免将来新增入口忘了校验时把响应又放开给任意站点。被入口拒绝的请求
    （handler._deny_cors=True）一律不返回任何放行头。
    """
    if getattr(handler, "_deny_cors", False):
        return [("Vary", "Origin")]
    headers = getattr(handler, "headers", None)
    origin = ""
    if headers is not None:
        try:
            origin = (headers.get("Origin") or "").strip()
        except (AttributeError, TypeError):
            origin = ""
    if not origin or not is_loopback_origin(origin, _server_port(handler)):
        return [("Vary", "Origin")]
    return [
        ("Vary", "Origin"),
        ("Access-Control-Allow-Origin", origin),
        ("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"),
        ("Access-Control-Allow-Headers", "Content-Type"),
    ]


def _write_headers(handler: BaseHTTPRequestHandler, extra: list[tuple[str, str]]) -> None:
    for key, value in SECURITY_HEADERS:
        handler.send_header(key, value)
    for key, value in cors_headers(handler):
        handler.send_header(key, value)
    for key, value in extra:
        handler.send_header(key, value)


def send_json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    """把 dict 序列化为 JSON 响应（仅对同源回环页面放行 CORS）。

    注意：CORS 只决定浏览器能否读取响应，不代表手机推流本身有认证
    （见 README 安全说明）；跨站页面由 app.py 的 Host/Origin 校验直接拒绝。
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    _write_headers(handler, [])
    handler.end_headers()
    handler.wfile.write(body)


def send_error(handler: BaseHTTPRequestHandler, code: str, message: str,
               status: int = 400) -> None:
    send_json(handler, {"ok": False, "error": {"code": code, "message": message}}, status)


def read_json(handler: BaseHTTPRequestHandler) -> dict:
    """读取并解析请求体；空 body 视为 {}（便于 GET 风格 POST）。"""
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        raise ApiError(ERR_BAD_REQUEST, "Content-Length 不合法")
    if length <= 0:
        return {}
    if length > MAX_BODY_BYTES:
        raise ApiError(ERR_BAD_REQUEST, "请求体过大", 413)
    raw = handler.rfile.read(length)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ApiError(ERR_BAD_REQUEST, "请求体不是合法 JSON")
    if not isinstance(data, dict):
        raise ApiError(ERR_BAD_REQUEST, "请求体必须是 JSON 对象")
    return data


def send_bytes(handler: BaseHTTPRequestHandler, body: bytes, content_type: str,
               cache_seconds: int = 0) -> None:
    """发送二进制响应（截图、缩略图、模型包）。"""
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control",
                        "no-store" if cache_seconds <= 0 else f"max-age={cache_seconds}")
    _write_headers(handler, [])
    handler.end_headers()
    handler.wfile.write(body)


def safe_int(value, default: int, minimum: int | None = None,
             maximum: int | None = None) -> int:
    """把外部输入转成 int；非法或越界时抛 ApiError（不静默取默认值）。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ApiError(ERR_BAD_REQUEST, f"参数必须是整数: {value!r}")
    if minimum is not None and number < minimum:
        raise ApiError(ERR_BAD_REQUEST, f"参数不能小于 {minimum}: {number}")
    if maximum is not None and number > maximum:
        raise ApiError(ERR_BAD_REQUEST, f"参数不能大于 {maximum}: {number}")
    return number


def safe_float(value, default: float = 0.0, minimum: float | None = None,
               maximum: float | None = None, strict: bool = False) -> float:
    """把外部输入转成 float。

    strict=False 时保持旧行为（非法值回落到 default，供内部调用）；
    strict=True 时非法值/非有限值/越界一律抛 ApiError（HTTP 参数走这条）。
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        if strict:
            raise ApiError(ERR_BAD_REQUEST, f"参数必须是数字: {value!r}")
        return default
    if number != number or number in (float("inf"), float("-inf")):
        if strict:
            raise ApiError(ERR_BAD_REQUEST, f"参数必须是有限数字: {value!r}")
        return default
    if minimum is not None and number < minimum:
        if strict:
            raise ApiError(ERR_BAD_REQUEST, f"参数不能小于 {minimum}: {number}")
        return default
    if maximum is not None and number > maximum:
        if strict:
            raise ApiError(ERR_BAD_REQUEST, f"参数不能大于 {maximum}: {number}")
        return default
    return number


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def validate_private_host(host: str, label: str = "IP 地址") -> str:
    """校验连接目标只能是局域网私网 IP，返回规范化后的主机串。

    拒绝：空值、域名、回环、未指定地址、链路本地（169.254/fe80）、组播、
    保留地址与公网地址。IPv6 规范化成 ``[addr]``，可直接拼进 URL。
    """
    raw = (host or "").strip()
    if not raw:
        raise ApiError(ERR_BAD_REQUEST, f"请填写{label}")
    candidate = raw[1:-1] if raw.startswith("[") and raw.endswith("]") else raw
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        raise ApiError(ERR_BAD_REQUEST,
                       f"{label}必须是局域网 IP 地址（不支持域名）: {raw}")
    if (address.is_loopback or address.is_unspecified
            or address.is_link_local or address.is_multicast
            or address.is_reserved or not address.is_private):
        raise ApiError(
            ERR_BAD_REQUEST,
            f"{label}必须是局域网私网地址（禁止回环/链路本地/公网）: {raw}")
    if address.version == 6:
        return f"[{address.compressed}]"
    return str(address)


def image_content_type(name: str) -> str:
    """按扩展名推导图片 Content-Type（只认数据集允许的图片类型）。"""
    lowered = (name or "").lower()
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    return "application/octet-stream"


def safe_path_join(base: str, *parts: str) -> str:
    """把外部传入的相对路径拼到 base 下，拒绝越界（.. / 绝对路径）。

    与 pvl_dataset._safe_join 同样的严格程度：宁可拒绝，也不给路径穿越留空间。
    """
    for part in parts:
        if not part:
            raise ApiError(ERR_BAD_REQUEST, "路径片段为空")
        if os.path.isabs(part) or ".." in part.replace("\\", "/").split("/"):
            raise ApiError(ERR_BAD_REQUEST, f"非法路径片段: {part}")
    target = os.path.normpath(os.path.join(base, *parts))
    base_norm = os.path.normpath(base)
    if target != base_norm and not target.startswith(base_norm + os.sep):
        raise ApiError(ERR_BAD_REQUEST, "路径越界")
    return target


def is_image_file(name: str) -> bool:
    return name.lower().endswith((".jpg", ".jpeg", ".png"))


def now_stamp() -> str:
    import time
    return time.strftime("%Y%m%d-%H%M%S")


class StoppableThread:
    """可被请求取消的后台线程封装（训练/采样用）。

    不直接继承 threading.Thread：这里只需要"启动 + 协作式停止 + 查询存活"，
    包一层让调用方代码更短，也便于在测试里替换。
    """

    def __init__(self, target, name: str):
        self._target = target
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=name)

    def _run(self) -> None:
        try:
            self._target(self._stop_event)
        except Exception:  # noqa: BLE001 - 后台异常只记录，不影响服务
            import traceback
            traceback.print_exc()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def join(self, timeout: float = 3.0) -> None:
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event


def traceback_text(limit: int = 4) -> str:
    import traceback
    return traceback.format_exc(limit=limit).strip()
