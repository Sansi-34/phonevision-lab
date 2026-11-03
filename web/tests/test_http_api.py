"""
PhoneVision Lab Web — HTTP 层集成测试（真实起服务器，验证路由与错误契约）。

职责：在随机端口启动 ThreadingHTTPServer，用 urllib 发真实请求，验证：
  - 主要 GET 路由返回 {ok:true,data:...}；
  - 错误路由返回 {ok:false,error:{code,message}} 且 HTTP 状态码合理；
  - 静态首页可访问；
  - 未知接口返回 404 结构化错误；
  - CORS 只回显同源 Origin（不再放行任意站点）。
不连接手机、不启动训练。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _WEB not in sys.path:
    sys.path.insert(0, _WEB)

_REPO = os.path.dirname(_WEB)
_PC_CLIENT = os.path.join(_REPO, "pc-client")
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)


class HttpServerTest(unittest.TestCase):
    """真实服务器 + 真实 HTTP 请求。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="pvl-web-http-")
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

    def _get(self, path, timeout=15):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers)

    def _get_slow(self, path):
        """给训练环境检测等慢接口用（首次导入 TensorFlow 可能很久）。"""
        return self._get(path, timeout=180)

    def _post(self, path, payload):
        url = f"http://127.0.0.1:{self.port}{path}"
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read(), dict(response.headers)

    def _post_expect_error(self, path, payload):
        url = f"http://127.0.0.1:{self.port}{path}"
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                self.fail(f"预期失败但返回了 {response.status}")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    # ---- 健康检查与首页 ----

    def test_health(self):
        status, body, headers = self._get("/api/health")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["service"], "phonevision-lab-web")

    def test_index_html_served(self):
        status, body, headers = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        text = body.decode("utf-8")
        self.assertIn("PhoneVision Lab", text)
        self.assertIn("app.js", text)

    def test_cors_header_echoes_same_origin_not_wildcard(self):
        """同源请求回显 Origin；绝不能再用 Access-Control-Allow-Origin: *。"""
        origin = f"http://127.0.0.1:{self.port}"
        url = f"http://127.0.0.1:{self.port}/api/health"
        request = urllib.request.Request(url, headers={"Origin": origin})
        with urllib.request.urlopen(request, timeout=15) as response:
            headers = dict(response.headers)
            self.assertEqual(response.status, 200)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), origin)
        self.assertNotEqual(headers.get("Access-Control-Allow-Origin"), "*")

    def test_no_cors_wildcard_without_origin(self):
        _status, _body, headers = self._get("/api/health")
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_unknown_api_returns_structured_404(self):
        try:
            self._get("/api/does-not-exist")
            self.fail("预期 404")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 404)
            payload = json.loads(error.read().decode("utf-8"))
            self.assertFalse(payload["ok"])
            self.assertIn("code", payload["error"])

    def test_static_path_traversal_rejected(self):
        try:
            self._get("/../server/app.py")
            self.fail("预期 404")
        except urllib.error.HTTPError as error:
            self.assertIn(error.code, (400, 404))

    # ---- 设备 ----

    def test_device_status_disconnected(self):
        status, body, _headers = self._get("/api/device/status")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))["data"]
        self.assertFalse(data["connected"])
        self.assertEqual(data["state"], "disconnected")
        for key in ("phone_fps", "receive_fps", "display_fps"):
            self.assertIsNone(data[key], f"未连接时 {key} 必须为 null")

    def test_connect_without_host_is_bad_request(self):
        status, payload = self._post_expect_error("/api/device/connect",
                                                  {"port": 8080})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "bad_request")

    def test_connect_bad_port_is_bad_request(self):
        _status, payload = self._post_expect_error(
            "/api/device/connect", {"host": "127.0.0.1", "port": 99999})
        self.assertEqual(payload["error"]["code"], "bad_request")

    def test_vision_state_default(self):
        """先把模式复位成 original，再断言默认态（避免受其他测试影响）。"""
        self._post("/api/vision/mode", {"mode": "original"})
        _status, body, _headers = self._get("/api/vision/state")
        data = json.loads(body.decode("utf-8"))["data"]
        self.assertEqual(data["mode"], "original")
        self.assertEqual(len(data["modes"]), 5)
        self.assertTrue(data["hint"])

    def test_vision_frame_without_device_reports_no_frame(self):
        """未连接设备时取帧必须返回明确的 no_frame 错误。"""
        try:
            self._get("/api/vision/frame")
            self.fail("预期 400")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 400)
            payload = json.loads(error.read().decode("utf-8"))
            self.assertEqual(payload["error"]["code"], "not_connected")

    # ---- 视觉模式与参数 ----

    def test_set_mode_and_params(self):
        self._post("/api/vision/mode", {"mode": "canny"})
        _status, body, _headers = self._get("/api/vision/state")
        data = json.loads(body.decode("utf-8"))["data"]
        self.assertEqual(data["mode"], "canny")
        self.assertEqual(len(data["params"]), 2)
        self._post("/api/vision/params", {"params": {"canny_low": 40}})
        _status, body, _headers = self._get("/api/vision/state")
        data = json.loads(body.decode("utf-8"))["data"]
        values = {p["key"]: p["value"] for p in data["params"]}
        self.assertEqual(values["canny_low"], 40)

    def test_set_unknown_mode_rejected(self):
        _status, payload = self._post_expect_error("/api/vision/mode",
                                                   {"mode": "thermal"})
        self.assertEqual(payload["error"]["code"], "bad_request")

    def test_params_out_of_range_clamped(self):
        self._post("/api/vision/mode", {"mode": "hsv"})
        self._post("/api/vision/params", {"params": {"h_min": 9999}})
        _status, body, _headers = self._get("/api/vision/state")
        data = json.loads(body.decode("utf-8"))["data"]
        values = {p["key"]: p["value"] for p in data["params"]}
        self.assertEqual(values["h_min"], 179)

    # ---- 数据集 ----

    def test_dataset_lifecycle_over_http(self):
        _status, body, _headers = self._get("/api/datasets")
        data = json.loads(body.decode("utf-8"))["data"]
        self.assertIn("datasets", data)

        _status, body, _headers = self._post(
            "/api/datasets/create", {"name": "http-test", "classes": ["a", "b"]})
        created = json.loads(body.decode("utf-8"))["data"]
        self.assertTrue(created["opened"])
        self.assertEqual(len(created["classes"]), 2)

        _status, body, _headers = self._get("/api/datasets/current")
        current = json.loads(body.decode("utf-8"))["data"]
        self.assertEqual(current["name"], "http-test")

        _status, body, _headers = self._get("/api/datasets/check")
        check = json.loads(body.decode("utf-8"))["data"]
        # 没有图片：必须给出阻断性问题，不能显示"可以训练"
        self.assertFalse(check["ready"])
        self.assertTrue(check["problems"])

    def test_capture_without_device_rejected(self):
        self._post("/api/datasets/create",
                   {"name": "http-noframe", "classes": ["a", "b"]})
        _status, payload = self._post_expect_error(
            "/api/datasets/capture/one", {"class": "a"})
        self.assertEqual(payload["error"]["code"], "not_connected")

    # ---- 训练 ----

    def test_train_environment_over_http(self):
        # 首次调用会导入 TensorFlow（可能数十秒），给足超时
        _status, body, _headers = self._get_slow("/api/train/environment")
        data = json.loads(body.decode("utf-8"))["data"]
        self.assertIn("tensorflow", data)
        self.assertIn("ready", data)
        self.assertIn("fix_command", data)

    def test_train_status_idle(self):
        _status, body, _headers = self._get("/api/train/status")
        data = json.loads(body.decode("utf-8"))["data"]
        self.assertEqual(data["state"], "idle")
        self.assertEqual(data["step"], 0)
        self.assertIsNone(data["loss"])

    def test_train_start_without_dataset_rejected(self):
        """先关闭所有数据集，再确认训练被拒绝且原因是"没有数据集"。"""
        self._post("/api/datasets/create",
                   {"name": "train-gate", "classes": ["a", "b"]})
        self._post("/api/datasets/split", {"val_ratio": 0.2})
        # 未划分的数据集 → no_split；关闭数据集 → no_dataset
        _status, payload = self._post_expect_error(
            "/api/train/start", {})
        self.assertIn(payload["error"]["code"], ("no_dataset", "no_split"))
        self.assertTrue(payload["error"]["message"])

    def test_train_export_before_training_rejected(self):
        _status, payload = self._post_expect_error("/api/train/export", {})
        self.assertEqual(payload["error"]["code"], "not_ready")

    # ---- 硬件 ----

    def test_hardware_status_disconnected(self):
        _status, body, _headers = self._get("/api/hardware/status")
        data = json.loads(body.decode("utf-8"))["data"]
        self.assertFalse(data["connected"])
        self.assertFalse(data["simulated"])
        self.assertEqual(data["auto_control"], "phone_only")
        action_ids = {a["id"] for a in data["actions"]}
        self.assertNotIn("servo_set", action_ids,
                         "舵机等未验证动作不得出现在可用列表")

    def test_hardware_send_without_connection_rejected(self):
        _status, payload = self._post_expect_error("/api/hardware/send",
                                                   {"action": "led_on"})
        self.assertEqual(payload["error"]["code"], "not_connected")

    def test_hardware_simulated_device_over_http(self):
        self._post("/api/hardware/connect", {"simulated": True})
        _status, body, _headers = self._post("/api/hardware/send",
                                             {"action": "led_on"})
        data = json.loads(body.decode("utf-8"))["data"]
        self.assertTrue(data["event"]["simulated"])
        self.assertEqual(data["event"]["status"], "executed")
        _status, body, _headers = self._get("/api/hardware/status")
        status = json.loads(body.decode("utf-8"))["data"]
        self.assertTrue(status["connected"])
        self.assertTrue(status["simulated"])
        self._post("/api/hardware/disconnect", {})

    def test_hardware_rejects_servo_over_http(self):
        self._post("/api/hardware/connect", {"simulated": True})
        _status, payload = self._post_expect_error(
            "/api/hardware/send", {"action": "servo_set", "params": {"angle": 90}})
        self.assertEqual(payload["error"]["code"], "bad_request")
        self._post("/api/hardware/disconnect", {})

    # ---- 性能 ----

    def test_perf_status_without_record(self):
        _status, body, _headers = self._get("/api/perf/status")
        data = json.loads(body.decode("utf-8"))["data"]
        self.assertFalse(data["has_record"])
        self.assertIsNone(data["metrics"])

    def test_perf_start_without_device_rejected(self):
        _status, payload = self._post_expect_error(
            "/api/perf/start", {"warmup": 3, "duration": 60})
        self.assertEqual(payload["error"]["code"], "not_connected")

    def test_perf_export_without_record_rejected(self):
        try:
            self._get("/api/perf/export?kind=csv")
            self.fail("预期 400")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 400)
            payload = json.loads(error.read().decode("utf-8"))
            self.assertFalse(payload["ok"])

    # ---- 错误处理 ----

    def test_malformed_json_body(self):
        url = f"http://127.0.0.1:{self.port}/api/vision/mode"
        request = urllib.request.Request(
            url, data=b"not-json", method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                self.fail("预期 400")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 400)
            payload = json.loads(error.read().decode("utf-8"))
            self.assertEqual(payload["error"]["code"], "bad_request")

    def test_wrong_method_rejected(self):
        url = f"http://127.0.0.1:{self.port}/api/device/connect"
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                self.fail("预期 405")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 405)


if __name__ == "__main__":
    unittest.main()
