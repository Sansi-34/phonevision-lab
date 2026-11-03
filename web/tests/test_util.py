"""
PhoneVision Lab Web — 工具函数测试（JSON 响应、错误、路径校验）。

职责：验证 web/server/util.py 的统一响应与安全边界，不连网、不需要设备。
"""
import json
import os
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler

_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _WEB not in sys.path:
    sys.path.insert(0, _WEB)

from server.util import (  # noqa: E402
    ApiError, ERR_BAD_REQUEST, MAX_BODY_BYTES, clamp, image_content_type,
    is_image_file, is_loopback_origin, safe_float, safe_int, safe_path_join,
    validate_private_host,
)


class _FakeServer:
    def __init__(self, port):
        self.server_address = ("127.0.0.1", port)


class _CaptureHandler(BaseHTTPRequestHandler):
    """捕获 send_json / send_error 输出的假 handler（不真正写 socket）。"""

    def __init__(self, headers=None, port=8088):
        self.status = None
        self.headers_sent = {}
        self.body = b""
        self.headers = dict(headers or {})
        self.server = _FakeServer(port)

    def send_response(self, code):
        self.status = code

    def send_header(self, key, value):
        self.headers_sent[key] = value

    def end_headers(self):
        pass

    @property
    def wfile(self):
        import io
        if not hasattr(self, "_wfile"):
            self._wfile = io.BytesIO()
        return self._wfile

    def _capture(self):
        body = self.wfile.getvalue()
        self.body = body
        self._wfile = None
        return body


class SendJsonTest(unittest.TestCase):

    def test_send_json_serializes_chinese(self):
        handler = _CaptureHandler()
        from server.util import send_json
        send_json(handler, {"ok": True, "data": {"name": "苹果"}})
        handler._capture()
        self.assertEqual(handler.status, 200)
        self.assertIn("application/json", handler.headers_sent["Content-Type"])
        payload = json.loads(handler.body.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["name"], "苹果")

    def test_send_json_never_uses_wildcard_cors(self):
        handler = _CaptureHandler()
        from server.util import send_json
        send_json(handler, {"ok": True})
        handler._capture()
        self.assertIsNone(handler.headers_sent.get("Access-Control-Allow-Origin"))
        self.assertEqual(handler.headers_sent["Cache-Control"], "no-store")
        self.assertEqual(handler.headers_sent["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'",
                      handler.headers_sent["Content-Security-Policy"])
        self.assertEqual(handler.headers_sent["X-Content-Type-Options"], "nosniff")

    def test_send_json_echoes_same_origin(self):
        handler = _CaptureHandler(headers={"Origin": "http://127.0.0.1:8088"})
        from server.util import send_json
        send_json(handler, {"ok": True})
        handler._capture()
        self.assertEqual(handler.headers_sent["Access-Control-Allow-Origin"],
                         "http://127.0.0.1:8088")

    def test_send_json_ignores_foreign_origin(self):
        handler = _CaptureHandler(headers={"Origin": "http://evil.example"})
        from server.util import send_json
        send_json(handler, {"ok": True})
        handler._capture()
        self.assertIsNone(handler.headers_sent.get("Access-Control-Allow-Origin"))

    def test_send_error_structure(self):
        handler = _CaptureHandler()
        from server.util import send_error
        send_error(handler, ERR_BAD_REQUEST, "参数错误", 400)
        handler._capture()
        payload = json.loads(handler.body.decode("utf-8"))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], ERR_BAD_REQUEST)
        self.assertEqual(payload["error"]["message"], "参数错误")
        self.assertEqual(handler.status, 400)

    def test_send_bytes_content_type(self):
        handler = _CaptureHandler()
        from server.util import send_bytes
        send_bytes(handler, b"\xff\xd8\xff", "image/jpeg")
        handler._capture()
        self.assertEqual(handler.headers_sent["Content-Type"], "image/jpeg")
        self.assertEqual(handler.headers_sent["Content-Length"], "3")
        self.assertEqual(handler.body, b"\xff\xd8\xff")


class SafePathJoinTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pvl-web-test-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_allows_nested_relative(self):
        target = safe_path_join(self.tmp, "images", "apple", "0001.jpg")
        self.assertTrue(target.startswith(os.path.normpath(self.tmp)))

    def test_rejects_parent_traversal(self):
        with self.assertRaises(ApiError):
            safe_path_join(self.tmp, "..", "outside.txt")

    def test_rejects_absolute(self):
        with self.assertRaises(ApiError):
            safe_path_join(self.tmp, os.path.join(self.tmp, "x"))

    def test_rejects_escape_via_mixed(self):
        with self.assertRaises(ApiError):
            safe_path_join(self.tmp, "images", "..", "..", "..", "etc")


class NumberHelperTest(unittest.TestCase):

    def test_safe_int_rejects_non_numeric(self):
        with self.assertRaises(ApiError):
            safe_int("abc", 0)

    def test_safe_int_enforces_range(self):
        with self.assertRaises(ApiError):
            safe_int(-1, 0, minimum=0)
        self.assertEqual(safe_int("42", 0, minimum=0, maximum=100), 42)

    def test_safe_float_falls_back(self):
        self.assertEqual(safe_float(None, 1.5), 1.5)
        self.assertEqual(safe_float("bad", 2.0), 2.0)

    def test_clamp(self):
        self.assertEqual(clamp(5, 0, 3), 3)
        self.assertEqual(clamp(-5, 0, 3), 0)
        self.assertEqual(clamp(2, 0, 3), 2)

    def test_is_image_file(self):
        self.assertTrue(is_image_file("a.JPG"))
        self.assertTrue(is_image_file("b.png"))
        self.assertFalse(is_image_file("c.txt"))

    def test_max_body_bytes_is_reasonable(self):
        self.assertLessEqual(MAX_BODY_BYTES, 8 * 1024 * 1024)


class OriginAndHostTest(unittest.TestCase):

    def test_loopback_origins_accepted(self):
        self.assertTrue(is_loopback_origin("http://127.0.0.1:8088", 8088))
        self.assertTrue(is_loopback_origin("http://localhost:8088", 8088))
        self.assertTrue(is_loopback_origin("http://[::1]:8088", 8088))

    def test_foreign_origins_rejected(self):
        for origin in ("http://evil.example:8088", "https://127.0.0.1:8088",
                       "http://127.0.0.1:9999", "null", "file:///tmp/x",
                       "http://127.0.0.1.evil.example:8088"):
            with self.subTest(origin=origin):
                self.assertFalse(is_loopback_origin(origin, 8088))


class PrivateHostTest(unittest.TestCase):

    def test_private_lan_ips_accepted(self):
        self.assertEqual(validate_private_host("192.168.1.5"), "192.168.1.5")
        self.assertEqual(validate_private_host("10.0.0.9"), "10.0.0.9")
        self.assertEqual(validate_private_host("172.16.3.4"), "172.16.3.4")
        self.assertEqual(validate_private_host("fd00::1"), "[fd00::1]")

    def test_non_private_targets_rejected(self):
        for host in ("", "8.8.8.8", "127.0.0.1", "localhost", "::1",
                     "169.254.1.1", "0.0.0.0", "224.0.0.1", "example.com"):
            with self.subTest(host=host):
                with self.assertRaises(ApiError) as ctx:
                    validate_private_host(host)
                self.assertEqual(ctx.exception.code, ERR_BAD_REQUEST)


class ImageContentTypeTest(unittest.TestCase):

    def test_content_type_by_extension(self):
        self.assertEqual(image_content_type("a/b/c.JPG"), "image/jpeg")
        self.assertEqual(image_content_type("a/b/c.jpeg"), "image/jpeg")
        self.assertEqual(image_content_type("a/b/c.png"), "image/png")
        self.assertEqual(image_content_type("secret.txt"), "application/octet-stream")


if __name__ == "__main__":
    unittest.main()
