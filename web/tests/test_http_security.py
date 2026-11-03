"""
PhoneVision Lab Web — HTTP 安全边界测试（真实起服务器，真实 socket）。

职责：验证本地服务的三类攻击面已经被封住：
  - 数据集 root 白名单：任意本地目录不能再被当作数据集写入 dataset.json；
  - 样本接口只允许 <root>/images/** 下的图片（不能读/删 secret.txt 等）；
  - 跨站防护：Host/Origin 白名单、CORS 不再返回 *、预检同样校验；
  - 协议健壮性：未读 body 的 POST 不破坏 keep-alive、超大 body 413、
    静态目录用 commonpath 判定（..\\staticX\\x 不能越界）；
  - 参数与错误契约：非法数值 400，内部异常只回固定文案。

不连接手机、不启动训练。
"""
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _WEB not in sys.path:
    sys.path.insert(0, _WEB)

_REPO = os.path.dirname(_WEB)
_PC_CLIENT = os.path.join(_REPO, "pc-client")
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)


class HttpSecurityTest(unittest.TestCase):
    """真实服务器 + 真实 HTTP/socket 请求。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="pvl-web-sec-")
        os.environ["PVL_DATA_DIR"] = cls.tmp
        from server.app import create_server
        cls.server = create_server("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        os.environ.pop("PVL_DATA_DIR", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- 请求工具 ----

    def _url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def _call(self, path, method="GET", payload=None, headers=None,
              timeout=20):
        """发一个请求；HTTP 错误也返回 (status, body, headers) 而不是抛出。"""
        data = None
        request_headers = dict(headers or {})
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(self._url(path), data=data,
                                         method=method,
                                         headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read(), dict(error.headers)

    def _json(self, path, method="GET", payload=None, headers=None):
        status, body, response_headers = self._call(
            path, method=method, payload=payload, headers=headers)
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self.fail(f"{path} 返回的不是 JSON: {body[:120]!r}")
        return status, data, response_headers

    def _create_dataset(self, name):
        status, payload, _headers = self._json(
            "/api/datasets/create", "POST",
            {"name": name, "classes": ["a", "b"]})
        self.assertEqual(status, 200)
        self.assertTrue(payload["data"]["opened"])
        return payload["data"]

    def _raw_exchange(self, raw: bytes, read_all=True) -> bytes:
        with socket.create_connection(("127.0.0.1", self.port),
                                      timeout=10) as sock:
            sock.sendall(raw)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if not read_all and b"\r\n\r\n" in b"".join(chunks):
                    break
        return b"".join(chunks)

    # ---- 数据集 root 白名单 ----

    def test_open_outside_root_rejected(self):
        outside = tempfile.mkdtemp(prefix="pvl-web-outside-")
        try:
            status, payload, _headers = self._json(
                "/api/datasets/open", "POST", {"root": outside})
            self.assertEqual(status, 400)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["error"]["code"], "bad_request")
            self.assertFalse(
                os.path.exists(os.path.join(outside, "dataset.json")),
                "越界目录绝不能写入 dataset.json")
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_open_datasets_root_itself_rejected(self):
        from pvl_paths import datasets_dir
        status, payload, _headers = self._json(
            "/api/datasets/open", "POST", {"root": datasets_dir()})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "bad_request")

    def test_open_relative_root_rejected(self):
        status, payload, _headers = self._json(
            "/api/datasets/open", "POST", {"root": "datasets/whatever"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "bad_request")

    def test_open_managed_root_still_accepted(self):
        created = self._create_dataset("sec-open")
        status, payload, _headers = self._json(
            "/api/datasets/open", "POST", {"root": created["root"]})
        self.assertEqual(status, 200)
        self.assertTrue(payload["data"]["opened"])
        self.assertEqual(payload["data"]["name"], "sec-open")

    # ---- 样本接口：只允许 images/** 下的图片 ----

    def test_sample_image_rejects_non_image(self):
        created = self._create_dataset("sec-image")
        secret = os.path.join(created["root"], "secret.txt")
        with open(secret, "w", encoding="utf-8") as fh:
            fh.write("top secret contents")
        for path in ("secret.txt", "dataset.json"):
            with self.subTest(path=path):
                query = urllib.parse.quote(path, safe="")
                status, payload, _headers = self._json(
                    f"/api/datasets/samples/image?path={query}")
                self.assertEqual(status, 404)
                self.assertEqual(payload["error"]["code"], "not_found")
                self.assertNotIn("top secret", json.dumps(payload))

    def test_sample_image_rejects_backslash_non_image(self):
        created = self._create_dataset("sec-image-bs")
        with open(os.path.join(created["root"], "secret.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("top secret contents")
        query = urllib.parse.quote(r"..\secret.txt", safe="")
        status, payload, _headers = self._json(
            f"/api/datasets/samples/image?path={query}")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_sample_delete_rejects_non_image(self):
        created = self._create_dataset("sec-delete")
        config = os.path.join(created["root"], "dataset.json")
        status, payload, _headers = self._json(
            "/api/datasets/samples/delete", "POST", {"path": "dataset.json"})
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")
        self.assertTrue(os.path.isfile(config), "非图片文件不得被删除")

    def test_sample_image_content_type_by_extension(self):
        created = self._create_dataset("sec-content-type")
        batch_dir = os.path.join(created["root"], "images", "a", "batch-test")
        os.makedirs(batch_dir, exist_ok=True)
        for name, expected in (("x.jpg", "image/jpeg"),
                               ("y.jpeg", "image/jpeg"),
                               ("z.png", "image/png")):
            with open(os.path.join(batch_dir, name), "wb") as fh:
                fh.write(b"\xff\xd8\xff\xd9" if expected == "image/jpeg"
                         else b"\x89PNG\r\n\x1a\n")
            with self.subTest(name=name):
                query = urllib.parse.quote(f"images/a/batch-test/{name}",
                                           safe="/")
                status, body, headers = self._call(
                    f"/api/datasets/samples/image?path={query}")
                self.assertEqual(status, 200)
                self.assertEqual(headers.get("Content-Type"), expected)
                self.assertTrue(body)

    # ---- 跨站防护 ----

    def test_cross_site_origin_forbidden_without_cors(self):
        foreign = "http://evil.example"
        status, payload, headers = self._json(
            "/api/health", headers={"Origin": foreign})
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "forbidden")
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        self.assertNotIn(foreign, headers.get("Access-Control-Allow-Origin", ""))

    def test_null_origin_forbidden(self):
        status, _payload, headers = self._json(
            "/api/health", headers={"Origin": "null"})
        self.assertEqual(status, 403)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_cross_site_preflight_forbidden(self):
        status, payload, headers = self._call(
            "/api/device/connect", method="OPTIONS",
            headers={"Origin": "http://evil.example",
                     "Access-Control-Request-Method": "POST"})
        self.assertEqual(status, 403)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        self.assertEqual(json.loads(payload)["error"]["code"], "forbidden")

    def test_same_origin_preflight_allowed(self):
        origin = f"http://127.0.0.1:{self.port}"
        status, _body, headers = self._call(
            "/api/device/connect", method="OPTIONS",
            headers={"Origin": origin,
                     "Access-Control-Request-Method": "POST"})
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), origin)

    def test_same_origin_browser_post_allowed(self):
        """模拟真实浏览器同源 POST：Origin 与 Sec-Fetch-Site 同时存在。"""
        origin = f"http://127.0.0.1:{self.port}"
        status, payload, headers = self._json(
            "/api/vision/mode", "POST", {"mode": "original"},
            headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), origin)

    def test_foreign_host_header_forbidden(self):
        """DNS rebinding：Host 不是本机回环名 → 403。"""
        status, payload, _headers = self._json(
            "/api/health", headers={"Host": f"evil.example:{self.port}"})
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "forbidden")

    def test_wrong_port_host_header_forbidden(self):
        status, payload, _headers = self._json(
            "/api/health", headers={"Host": f"127.0.0.1:{self.port + 1}"})
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "forbidden")

    def test_rejected_host_never_gets_cors_headers(self):
        """即便 Origin 是回环，只要入口拒绝，就不能回 CORS 放行头。"""
        origin = f"http://127.0.0.1:{self.port}"
        status, payload, headers = self._call(
            "/api/health",
            headers={"Origin": origin, "Host": f"evil.example:{self.port}"})
        self.assertEqual(status, 403)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        self.assertEqual(json.loads(payload)["error"]["code"], "forbidden")

    def test_localhost_host_header_accepted(self):
        status, payload, _headers = self._json(
            "/api/health", headers={"Host": f"localhost:{self.port}"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

    def test_cross_site_sec_fetch_site_forbidden(self):
        status, payload, _headers = self._json(
            "/api/health", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "forbidden")

    def test_cross_site_page_navigation_allowed(self):
        """从外部链接点进本地首页是正常操作；页面本身禁止被 iframe 嵌套。"""
        status, body, headers = self._call(
            "/", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertIn("PhoneVision Lab", body.decode("utf-8", "replace"))

    # ---- keep-alive / body 排空 ----

    def test_keepalive_survives_unread_body(self):
        """POST /capture/stop 不读 body；下一条同连接请求必须仍被正确解析。"""
        host = f"127.0.0.1:{self.port}"
        raw = (
            f"POST /api/datasets/capture/stop HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: 2\r\n"
            f"\r\n"
            f"{{}}"
            f"GET /api/health HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode("ascii")
        data = self._raw_exchange(raw)
        text = data.decode("utf-8", "replace")
        statuses = re.findall(r"HTTP/1\.1 (\d{3})", text)
        self.assertEqual(statuses, ["200", "200"],
                         f"keep-alive 脱同步: {text[:400]!r}")
        self.assertNotIn("Unsupported method", text)

    def test_oversized_content_length_rejected(self):
        host = f"127.0.0.1:{self.port}"
        raw = (
            f"POST /api/vision/mode HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {1024 * 1024 + 1}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode("ascii")
        data = self._raw_exchange(raw)
        self.assertIn(b" 413 ", data.split(b"\r\n", 1)[0])

    # ---- 参数与错误契约 ----

    def test_quality_non_numeric_returns_400(self):
        status, payload, _headers = self._json(
            "/api/vision/frame?quality=abc")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "bad_request")

    def test_quality_out_of_range_returns_400(self):
        status, payload, _headers = self._json(
            "/api/vision/frame?quality=999")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "bad_request")

    def test_perf_start_non_numeric_returns_400(self):
        status, payload, _headers = self._json(
            "/api/perf/start", "POST", {"warmup": "abc", "duration": 10})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "bad_request")

    def test_dataset_split_non_numeric_returns_400(self):
        self._create_dataset("sec-split-num")
        status, payload, _headers = self._json(
            "/api/datasets/split", "POST", {"val_ratio": "abc"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "bad_request")
        status, payload, _headers = self._json(
            "/api/datasets/split", "POST", {"val_ratio": 1.5})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "bad_request")

    def test_device_connect_port_out_of_range_returns_400(self):
        for port in (0, 65536, "abc"):
            with self.subTest(port=port):
                status, payload, _headers = self._json(
                    "/api/device/connect", "POST",
                    {"host": "192.168.1.5", "port": port})
                self.assertEqual(status, 400)
                self.assertEqual(payload["error"]["code"], "bad_request")

    def test_server_concurrency_limit_configured(self):
        from server.app import MAX_CONCURRENT_REQUESTS, REQUEST_TIMEOUT_SECONDS
        from server.app import ApiHandler
        self.assertGreater(MAX_CONCURRENT_REQUESTS, 0)
        self.assertTrue(hasattr(self.server, "_request_slots"))
        self.assertEqual(ApiHandler.timeout, REQUEST_TIMEOUT_SECONDS)

    def test_internal_error_message_is_generic(self):
        from server import device as device_module
        with mock.patch.object(device_module.DeviceSession, "status",
                               side_effect=RuntimeError("boom-secret")):
            status, payload, _headers = self._json("/api/device/status")
        self.assertEqual(status, 500)
        self.assertEqual(payload["error"]["code"], "internal_error")
        self.assertEqual(payload["error"]["message"], "服务内部错误，请稍后重试")
        self.assertNotIn("boom-secret", json.dumps(payload, ensure_ascii=False))

    def test_public_host_device_connect_rejected(self):
        for host in ("8.8.8.8", "example.com", "127.0.0.1", "169.254.1.1"):
            with self.subTest(host=host):
                status, payload, _headers = self._json(
                    "/api/device/connect", "POST",
                    {"host": host, "port": 8080})
                self.assertEqual(status, 400)
                self.assertEqual(payload["error"]["code"], "bad_request")

    # ---- 静态目录与响应头 ----

    def test_static_backslash_traversal_rejected(self):
        host = f"127.0.0.1:{self.port}"
        raw = (
            "GET /..\\staticX\\x HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")
        data = self._raw_exchange(raw)
        first_line = data.split(b"\r\n", 1)[0]
        self.assertTrue(b" 404 " in first_line or b" 403 " in first_line,
                        f"静态路径越界未被拒绝: {first_line!r}")

    def test_static_security_headers(self):
        status, body, headers = self._call("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("frame-ancestors 'none'",
                      headers.get("Content-Security-Policy", ""))
        self.assertNotIn("Python", headers.get("Server", ""),
                         "Server 头不能暴露 Python 版本")


if __name__ == "__main__":
    unittest.main()
