"""
PhoneVision Lab Web — HTTP 路由与请求处理器。

职责：把 URL 映射到 device / dataset / training / hardware / performance 五个
服务，统一处理 JSON 响应、错误与 OPTIONS 预检。

为什么这样设计：
  - 用标准库 http.server 自建路由：项目现有依赖里没有 Web 框架，第一版不为
    一个本地学习平台引入 FastAPI/Flask。路由表是一张显式列表，便于测试直接
    构造请求驱动，不需要起真服务器。
  - 处理器只做"取参数 -> 调服务 -> 序列化"，业务逻辑全在 services 里，
    与 pc-client 的模块边界一致。
  - 所有错误都经过 ApiError -> {ok:false, error:{code,message}}，
    前端按 code 显示"未连接/环境不可用/参数错误"，不展示堆栈。
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .util import (  # noqa: E402
    ApiError, ERR_BAD_REQUEST, ERR_FORBIDDEN, ERR_INTERNAL, ERR_NOT_FOUND,
    LOOPBACK_HOSTS, MAX_BODY_BYTES, SECURITY_HEADERS, cors_headers,
    image_content_type, is_loopback_origin, safe_float, safe_int, send_bytes,
    send_error, send_json,
)

# 单进程并发上限：超过后新连接直接 503，避免线程被无限请求堆满。
MAX_CONCURRENT_REQUESTS = 16

# 单连接空闲/读超时（秒）：防止 keep-alive 或慢速 body 永久占用线程。
REQUEST_TIMEOUT_SECONDS = 30

# 单例服务（进程内共享）。训练/性能是有状态任务，硬件与设备连接同理。
_services_lock = threading.RLock()
_services: dict = {}


def services() -> dict:
    """惰性创建服务单例（避免 import 时就导入 TensorFlow 等重依赖）。"""
    with _services_lock:
        if not _services:
            from .dataset import DatasetService
            from .device import DeviceSession
            from .hardware import HardwareService
            from .performance import PerformanceService
            from .training import TrainingJob
            _services.update({
                "device": DeviceSession(),
                "dataset": DatasetService(),
                "training": TrainingJob(),
                "hardware": HardwareService(),
                "performance": PerformanceService(),
            })
            # 性能采样后台线程：独立于请求线程，页面关闭也不影响采样
            _services["_sampler_thread"] = threading.Thread(
                target=_sampler_loop, daemon=True, name="pvl-web-sampler")
            _services["_sampler_thread"].start()
    return _services


def _sampler_loop() -> None:
    """每秒推进一次性能采样（仅在有测试运行时做真实工作）。"""
    import time
    while True:
        time.sleep(1.0)
        svc = _services
        if not svc:
            continue
        performance = svc.get("performance")
        device = svc.get("device")
        if performance is None or device is None:
            continue
        try:
            performance.tick(device)
        except Exception:  # noqa: BLE001 - 采样异常不影响服务
            pass


# ----------------------------------------------------------------------
# 路由表
# ----------------------------------------------------------------------

class Route:
    """一条路由：方法 + 路径正则 + handler + 需要从 query 读取的参数名。

    query 用参数名列表而不是 (name, default) 元组：_dispatch 里直接把 URL
    上的同名参数填进 ctx.query，handler 自己决定默认值（例如 quality 缺省 82）。
    早期版本把 (name, default) 元组塞进 ctx.query，导致 handler 拿到 tuple 再
    int() 直接 TypeError——那个 bug 由 test_http_api 抓到并修复。
    """

    def __init__(self, method: str, pattern: str, handler, query: list | None = None):
        self.method = method
        self.regex = re.compile("^" + pattern + "$")
        self.handler = handler
        self.query = query or []


def _q(*names):
    """声明这条路由要从 URL query 读取哪些参数名。"""
    return list(names)


def _opt_int(data: dict, key: str, default: int, minimum: int, maximum: int) -> int:
    """从 JSON body 取可选整数：缺省/空串用默认值，非法值 400 而不是 500。"""
    raw = data.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raw = default
    return safe_int(raw, default, minimum=minimum, maximum=maximum)


def _opt_float(data: dict, key: str, default: float, minimum: float,
               maximum: float) -> float:
    """从 JSON body 取可选浮点数：缺省/空串用默认值，非法值 400。"""
    raw = data.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raw = default
    return safe_float(raw, default, minimum=minimum, maximum=maximum, strict=True)


def _build_routes() -> list:
    def device_status(ctx):
        return ctx.device.status()

    def device_connect(ctx):
        data = ctx.body()
        host = str(data.get("host") or "").strip()
        port = _opt_int(data, "port", 8080, 1, 65535)
        return ctx.device.connect(host, port)

    def device_disconnect(ctx):
        ctx.device.disconnect()
        return {"connected": False}

    def device_reconnect(ctx):
        status = ctx.device.status()
        if not status.get("host"):
            raise ApiError("not_connected", "尚未连接过设备，请先输入手机 IP")
        return ctx.device.connect(status["host"], status["port"])

    def vision_state(ctx):
        return ctx.device.vision_state()

    def vision_mode(ctx):
        data = ctx.body()
        mode = str(data.get("mode") or "")
        ctx.device.set_mode(mode)
        return ctx.device.vision_state()

    def vision_params(ctx):
        data = ctx.body()
        ctx.device.set_params(data.get("params") or {})
        return ctx.device.vision_state()

    def vision_frame(ctx):
        quality = safe_int(ctx.query.get("quality") or 82, 82,
                           minimum=1, maximum=100)
        body = ctx.device.frame_jpeg(quality=quality)
        return ("bytes", body, "image/jpeg")

    def vision_snapshot(ctx):
        body = ctx.device.snapshot_jpeg()
        return ("bytes", body, "image/jpeg")

    def vision_displayed(ctx):
        ctx.device.mark_frame_displayed()
        return {"ok": True}

    def vision_metrics(ctx):
        return ctx.device.transport_metrics()

    # ---- 数据集 ----
    def dataset_list(ctx):
        return {"datasets": ctx.dataset.list_datasets()}

    def dataset_create(ctx):
        data = ctx.body()
        classes = [str(c).strip() for c in (data.get("classes") or []) if str(c).strip()]
        return ctx.dataset.create(str(data.get("name") or ""), classes)

    def dataset_open(ctx):
        data = ctx.body()
        return ctx.dataset.open(str(data.get("root") or ""))

    def dataset_current(ctx):
        return ctx.dataset.current()

    def dataset_add_class(ctx):
        data = ctx.body()
        return ctx.dataset.add_class(str(data.get("name") or ""))

    def dataset_rename_class(ctx):
        data = ctx.body()
        return ctx.dataset.rename_class(str(data.get("name") or ""),
                                        str(data.get("new_name") or ""))

    def dataset_remove_class(ctx):
        data = ctx.body()
        return ctx.dataset.remove_class(str(data.get("name") or ""))

    def dataset_samples(ctx):
        class_name = ctx.query.get("class") or None
        return {"samples": ctx.dataset.samples(class_name)}

    def dataset_sample_image(ctx):
        path = ctx.query.get("path") or ""
        return ("bytes", ctx.dataset.sample_image(path),
                image_content_type(path))

    def dataset_delete_sample(ctx):
        data = ctx.body()
        return ctx.dataset.delete_sample(str(data.get("path") or ""))

    def dataset_check(ctx):
        return ctx.dataset.check()

    def dataset_split(ctx):
        data = ctx.body() or {}
        ratio = _opt_float(data, "val_ratio", 0.2, 0.0, 1.0)
        if ratio <= 0.0 or ratio >= 1.0:
            raise ApiError(ERR_BAD_REQUEST, "验证集比例必须在 0 和 1 之间")
        seed = _opt_int(data, "seed", 1234, 0, 2**31 - 1)
        return ctx.dataset.split(val_ratio=ratio, seed=seed)

    def dataset_split_status(ctx):
        return ctx.dataset.split_status()

    def dataset_capture_one(ctx):
        data = ctx.body() or {}
        ctx.dataset.select_class(str(data.get("class") or ""))
        return ctx.dataset.capture_one(ctx.device)

    def dataset_capture_start(ctx):
        data = ctx.body() or {}
        ctx.dataset.select_class(str(data.get("class") or ""))
        return ctx.dataset.start_capture(ctx.device)

    def dataset_capture_stop(ctx):
        return ctx.dataset.stop_capture()

    # ---- 训练 ----
    def train_env(ctx):
        from .training import training_environment
        return training_environment()

    def train_env_reset(ctx):
        from .training import reset_environment_cache, training_environment
        reset_environment_cache()
        return training_environment()

    def train_start(ctx):
        data = ctx.body() or {}
        current = ctx.dataset.current()
        return ctx.training.start(current["root"], current["name"], data)

    def train_status(ctx):
        return ctx.training.snapshot()

    def train_cancel(ctx):
        return ctx.training.cancel()

    def train_export(ctx):
        return ctx.training.export()

    def train_last_run(ctx):
        return ctx.training.last_run()

    # ---- 硬件 ----
    def hw_status(ctx):
        return ctx.hardware.status()

    def hw_connect(ctx):
        data = ctx.body() or {}
        host = str(data.get("host") or "")
        port = _opt_int(data, "port", 8081, 1, 65535)
        return ctx.hardware.connect(host, port, bool(data.get("simulated")))

    def hw_disconnect(ctx):
        return ctx.hardware.disconnect()

    def hw_send(ctx):
        data = ctx.body() or {}
        params = data.get("params") or {}
        return {"event": ctx.hardware.send(str(data.get("action") or ""), params)}

    def hw_events(ctx):
        return {"events": ctx.hardware.events()}

    # ---- 性能 ----
    def perf_start(ctx):
        data = ctx.body() or {}
        warmup = _opt_float(data, "warmup", 3.0, 0.0, 3600.0)
        duration = _opt_float(data, "duration", 60.0, 0.001, 86400.0)
        return ctx.performance.start(warmup, duration, ctx.device)

    def perf_stop(ctx):
        return ctx.performance.stop()

    def perf_status(ctx):
        return ctx.performance.snapshot()

    def perf_export(ctx):
        kind = ctx.query.get("kind") or "csv"
        path = ctx.performance.export(kind)
        return {"path": path, "ok": True}

    routes = [
        Route("GET", r"/api/health", lambda ctx: {"ok": True, "service": "phonevision-lab-web"}),
        Route("GET", r"/api/device/status", device_status),
        Route("POST", r"/api/device/connect", device_connect),
        Route("POST", r"/api/device/disconnect", device_disconnect),
        Route("POST", r"/api/device/reconnect", device_reconnect),
        Route("GET", r"/api/vision/state", vision_state),
        Route("POST", r"/api/vision/mode", vision_mode),
        Route("POST", r"/api/vision/params", vision_params),
        Route("GET", r"/api/vision/frame", vision_frame, _q("quality")),
        Route("GET", r"/api/vision/snapshot", vision_snapshot),
        Route("POST", r"/api/vision/displayed", vision_displayed),
        Route("GET", r"/api/vision/metrics", vision_metrics),
        Route("GET", r"/api/datasets", dataset_list),
        Route("POST", r"/api/datasets/create", dataset_create),
        Route("POST", r"/api/datasets/open", dataset_open),
        Route("GET", r"/api/datasets/current", dataset_current),
        Route("POST", r"/api/datasets/classes/add", dataset_add_class),
        Route("POST", r"/api/datasets/classes/rename", dataset_rename_class),
        Route("POST", r"/api/datasets/classes/remove", dataset_remove_class),
        Route("GET", r"/api/datasets/samples", dataset_samples, _q("class")),
        Route("GET", r"/api/datasets/samples/image", dataset_sample_image,
              _q("path")),
        Route("POST", r"/api/datasets/samples/delete", dataset_delete_sample),
        Route("GET", r"/api/datasets/check", dataset_check),
        Route("POST", r"/api/datasets/split", dataset_split),
        Route("GET", r"/api/datasets/split", dataset_split_status),
        Route("POST", r"/api/datasets/capture/one", dataset_capture_one),
        Route("POST", r"/api/datasets/capture/start", dataset_capture_start),
        Route("POST", r"/api/datasets/capture/stop", dataset_capture_stop),
        Route("GET", r"/api/train/environment", train_env),
        Route("POST", r"/api/train/environment/recheck", train_env_reset),
        Route("POST", r"/api/train/start", train_start),
        Route("GET", r"/api/train/status", train_status),
        Route("POST", r"/api/train/cancel", train_cancel),
        Route("POST", r"/api/train/export", train_export),
        Route("GET", r"/api/train/last-run", train_last_run),
        Route("GET", r"/api/hardware/status", hw_status),
        Route("POST", r"/api/hardware/connect", hw_connect),
        Route("POST", r"/api/hardware/disconnect", hw_disconnect),
        Route("POST", r"/api/hardware/send", hw_send),
        Route("GET", r"/api/hardware/events", hw_events),
        Route("POST", r"/api/perf/start", perf_start),
        Route("POST", r"/api/perf/stop", perf_stop),
        Route("GET", r"/api/perf/status", perf_status),
        Route("GET", r"/api/perf/export", perf_export, _q("kind")),
    ]
    return routes


ROUTES = _build_routes()


class HandlerContext:
    """给 handler 用的上下文：body 缓存 + 服务引用 + query 参数。"""

    def __init__(self, handler, query: dict | None = None):
        self._handler = handler
        self._body = None
        self.query = query or {}
        svc = services()
        self.device = svc["device"]
        self.dataset = svc["dataset"]
        self.training = svc["training"]
        self.hardware = svc["hardware"]
        self.performance = svc["performance"]

    def body(self) -> dict:
        if self._body is None:
            from .util import read_json
            try:
                self._body = read_json(self._handler)
            finally:
                # 即使 JSON 解析失败，字节也已经从 rfile 读走，必须标记消费，
                # 否则 _dispatch 的 drain 会再等一遍 Content-Length 字节。
                self._handler._body_consumed = True
        return self._body


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "PhoneVisionLabWeb/0.1"
    sys_version = ""            # 不把 Python 版本写进 Server 头
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_TIMEOUT_SECONDS

    def setup(self):
        super().setup()
        # 超时必须落在 socket 上：rfile 是 BufferedReader，多数 Python 版本
        # 没有 settimeout（有则一并设置），真正生效的是 connection。
        try:
            self.connection.settimeout(self.timeout)
            self.rfile.settimeout(self.timeout)
        except (AttributeError, OSError):
            pass

    def version_string(self) -> str:
        """Server 头只暴露产品名与版本，不暴露 Python/解释器版本。"""
        return self.server_version

    # 静默访问日志里的静态资源噪声，但保留 API 日志便于本地排查
    def log_message(self, fmt, *args):  # noqa: A003 - 标准库钩子
        sys.stderr.write("[web] %s\n" % (fmt % args))

    # ------------------------------------------------------------------
    # 入口防护：Host / Origin / Sec-Fetch-Site
    # ------------------------------------------------------------------

    def _server_port(self) -> int | None:
        try:
            return int(self.server.server_address[1])
        except (AttributeError, IndexError, TypeError, ValueError):
            return None

    def _host_allowed(self, raw: str | None) -> bool:
        """只接受 127.0.0.1 / localhost / [::1] + 本服务真实端口。

        这条校验挡住 DNS rebinding：攻击者域名即使解析到 127.0.0.1，
        浏览器发来的 Host 仍是攻击者域名，会被直接拒绝。
        """
        if not raw:
            return False
        raw = raw.strip()
        if raw.startswith("["):
            end = raw.find("]")
            if end <= 0:
                return False
            host = raw[1:end]
            rest = raw[end + 1:]
            if not rest.startswith(":"):
                return False
            port_text = rest[1:]
        else:
            if raw.count(":") != 1:
                return False
            host, port_text = raw.rsplit(":", 1)
        if not port_text.isdigit():
            return False
        if host.strip().lower() not in LOOPBACK_HOSTS:
            return False
        expected = self._server_port()
        return expected is None or int(port_text) == expected

    def _origin_allowed(self) -> bool:
        origin = (self.headers.get("Origin") or "").strip()
        if not origin:
            return True
        return is_loopback_origin(origin, self._server_port())

    def _fetch_site_allowed(self, method: str = "GET", path: str = "") -> bool:
        """现代浏览器的跨站子资源/表单请求会带 Sec-Fetch-Site: cross-site。

        跨站"顶级导航"要放行（用户从外部链接点进本地页面是正常操作）：页面
        本身由 X-Frame-Options/CSP 防止被嵌套，页面内的请求又是同源的。
        跨站 API 与写请求一律拒绝——它们才是 CSRF/数据读取的入口。
        """
        site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if not site or site in ("same-origin", "none"):
            return True
        if method == "GET" and not path.startswith("/api/"):
            return True
        return False

    def _reject_cross_site(self, message: str) -> None:
        self.close_connection = True
        # 被入口拒绝的请求一律不返回 CORS 放行头（即使 Origin 恰好是回环）。
        self._deny_cors = True
        send_error(self, ERR_FORBIDDEN, message, 403)

    def _guard_request(self, method: str = "GET", path: str = "") -> bool:
        if not self._host_allowed(self.headers.get("Host")):
            self._reject_cross_site("拒绝访问：Host 不在本机白名单内")
            return False
        if not self._origin_allowed():
            self._reject_cross_site("拒绝访问：跨站 Origin 已被禁止")
            return False
        if not self._fetch_site_allowed(method, path):
            self._reject_cross_site("拒绝访问：跨站请求已被禁止")
            return False
        return True

    def do_OPTIONS(self):  # noqa: N802 - 标准库命名
        if not self._guard_request("OPTIONS", self.path):
            return
        self._body_consumed = False
        if not self._drain_body():
            send_error(self, ERR_BAD_REQUEST, "请求体过大", 413)
            return
        self.send_response(204)
        for key, value in SECURITY_HEADERS:
            self.send_header(key, value)
        for key, value in cors_headers(self):
            self.send_header(key, value)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        self._dispatch("GET")

    def do_POST(self):  # noqa: N802
        self._dispatch("POST")

    def do_DELETE(self):  # noqa: N802
        self._dispatch("DELETE")

    # ------------------------------------------------------------------
    # 请求体：预检 / 排空（keep-alive 脱同步防护）
    # ------------------------------------------------------------------

    def _content_length(self) -> int:
        raw = self.headers.get("Content-Length")
        if raw is None or not str(raw).strip():
            return 0
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return -1

    def _drain_body(self) -> bool:
        """读掉未被 handler 消费的请求体，避免下一条请求从 body 中间解析。

        返回 False 表示请求体超限（应回 413 并关闭连接）。
        """
        if getattr(self, "_body_consumed", False):
            return True
        length = self._content_length()
        if length <= 0:
            return length == 0
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            return False
        remaining = length
        try:
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    self.close_connection = True
                    break
                remaining -= len(chunk)
        except (OSError, TimeoutError):
            self.close_connection = True
        finally:
            self._body_consumed = True
        return True

    def _dispatch(self, method: str):
        from urllib.parse import parse_qs, unquote, urlparse
        try:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
        except ValueError:
            self.close_connection = True
            send_error(self, ERR_BAD_REQUEST, "请求路径不合法", 400)
            return
        if not self._guard_request(method, path):
            return
        if "\x00" in path:
            self.close_connection = True
            send_error(self, ERR_BAD_REQUEST, "请求路径不合法", 400)
            return
        if (self.headers.get("Transfer-Encoding") or "").strip().lower() not in ("", "identity"):
            # 标准库 handler 不解码分块请求体，无法安全复用连接。
            self.close_connection = True
            send_error(self, ERR_BAD_REQUEST, "不支持分块请求体", 400)
            return
        length = self._content_length()
        if length < 0:
            self.close_connection = True
            send_error(self, ERR_BAD_REQUEST, "Content-Length 不合法", 400)
            return
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            send_error(self, ERR_BAD_REQUEST, "请求体过大", 413)
            return

        self._body_consumed = False
        raw_query = parse_qs(parsed.query)
        query = {k: v[0] for k, v in raw_query.items()}

        for route in ROUTES:
            match = route.regex.match(path)
            if not match:
                continue
            if route.method != method:
                self._drain_body()
                send_error(self, "method_not_allowed",
                           f"该路径只接受 {route.method} 请求", 405)
                return
            try:
                # query 只保留该路由声明的参数名；未提供的参数不出现在 ctx.query 里，
                # handler 自行决定默认值（例如 quality 缺省 82）。
                route_query = {}
                for name in route.query:
                    if name in query:
                        route_query[name] = query[name]
                ctx = HandlerContext(self, route_query)
                result = route.handler(ctx)
            except ApiError as exc:
                if not self._drain_body():
                    send_error(self, ERR_BAD_REQUEST, "请求体过大", 413)
                    return
                send_error(self, exc.code, exc.message, exc.status)
                return
            except Exception:  # noqa: BLE001 - 未预期错误转结构化错误
                import traceback
                traceback.print_exc()
                # 未预期异常可能发生在读 body 的中途，连接状态不可信，直接关闭。
                self.close_connection = True
                if not self._drain_body():
                    send_error(self, ERR_BAD_REQUEST, "请求体过大", 413)
                    return
                # 内部异常文本只写日志，不回给前端。
                send_error(self, ERR_INTERNAL, "服务内部错误，请稍后重试", 500)
                return
            if not self._drain_body():
                send_error(self, ERR_BAD_REQUEST, "请求体过大", 413)
                return
            if isinstance(result, tuple) and result[0] == "bytes":
                _, body, content_type = result
                send_bytes(self, body, content_type)
            else:
                send_json(self, {"ok": True, "data": result})
            return

        self._drain_body()
        # 静态文件（前端构建产物）
        self._serve_static(path)

    def _serve_static(self, path: str):
        web_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        static_root = os.path.normpath(os.path.join(web_root, "static"))
        if path in ("/", "/index.html"):
            target = os.path.join(static_root, "index.html")
        else:
            safe = path.lstrip("/")
            if safe.startswith("api/"):
                send_error(self, ERR_NOT_FOUND, f"接口不存在: {path}", 404)
                return
            target = os.path.normpath(os.path.join(static_root, safe))
            # 用 commonpath 判定包含关系：单纯 startswith 会把
            # ..\staticX\x 这类同前缀兄弟目录当成合法路径。再对 realpath
            # 判一次，防止 static 目录内被放置指向外部的目录联接。
            if (target == static_root
                    or not _is_within(static_root, target)
                    or not _is_within(os.path.realpath(static_root),
                                      os.path.realpath(target))):
                send_error(self, ERR_NOT_FOUND, "非法路径", 404)
                return
        if not os.path.isfile(target):
            send_error(self, ERR_NOT_FOUND, f"资源不存在: {path}", 404)
            return
        content_type = _guess_content_type(target)
        try:
            with open(target, "rb") as fh:
                body = fh.read()
        except OSError:
            send_error(self, ERR_NOT_FOUND, "资源不可读", 404)
            return
        send_bytes(self, body, content_type, cache_seconds=0)


def _is_within(root: str, target: str) -> bool:
    """target 是否位于 root 之下（大小写不敏感；拒绝跨盘/非法路径）。"""
    try:
        root_key = os.path.normcase(os.path.abspath(root))
        target_key = os.path.normcase(os.path.abspath(target))
        return os.path.commonpath([root_key, target_key]) == root_key
    except (OSError, ValueError):
        return False


def _guess_content_type(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".html"):
        return "text/html; charset=utf-8"
    if lower.endswith(".js"):
        return "application/javascript; charset=utf-8"
    if lower.endswith(".css"):
        return "text/css; charset=utf-8"
    if lower.endswith(".json"):
        return "application/json; charset=utf-8"
    if lower.endswith(".svg"):
        return "image/svg+xml"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    if lower.endswith(".woff2"):
        return "font/woff2"
    return "application/octet-stream"


class LimitedThreadingHTTPServer(ThreadingHTTPServer):
    """带并发上限的 ThreadingHTTPServer。

    ThreadingHTTPServer 默认每来一个连接就开一个线程，本地服务被脚本刷时
    会堆出大量线程。这里用信号量限制同时处理的请求数，超出直接 503。
    """

    daemon_threads = True
    request_queue_size = 64

    def __init__(self, address, handler,
                 max_concurrent: int = MAX_CONCURRENT_REQUESTS):
        super().__init__(address, handler)
        self._request_slots = threading.BoundedSemaphore(max_concurrent)

    def process_request(self, request, client_address):
        if not self._request_slots.acquire(timeout=10.0):
            _send_busy_response(request)
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


def _send_busy_response(request) -> None:
    """并发槽位耗尽时的最小 503 响应（不进 handler，避免继续堆积线程）。"""
    body = json.dumps(
        {"ok": False, "error": {"code": "busy", "message": "服务繁忙，请稍后重试"}},
        ensure_ascii=False).encode("utf-8")
    head = (
        "HTTP/1.1 503 Service Unavailable\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    try:
        request.sendall(head + body)
    except OSError:
        pass


def create_server(host: str = "127.0.0.1", port: int = 8088) -> ThreadingHTTPServer:
    """创建 HTTP 服务器（不启动，便于测试）。"""
    return LimitedThreadingHTTPServer((host, port), ApiHandler)


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="PhoneVision Lab Web 学习与实践平台服务")
    parser.add_argument("--host", default="127.0.0.1",
                        help="监听地址（默认 127.0.0.1；Host 校验只接受本机回环地址）")
    parser.add_argument("--port", type=int, default=8088, help="监听端口（默认 8088）")
    args = parser.parse_args(argv)

    server = create_server(args.host, args.port)
    print(f"PhoneVision Lab Web 已启动: http://{args.host}:{args.port}")
    print("提示：手机需在同一局域网并先在 App 点击“开始推流”。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务…")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
