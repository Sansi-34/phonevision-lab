/*
 * PhoneVision Lab — LED 控制器固件（ESP32 + Arduino）
 *
 * 职责：接入局域网 Wi-Fi，暴露 HTTP 接口 POST /control，
 *       接收手机发来的 LED 开关命令并驱动真实 LED，回传结构化反馈。
 *
 * 为什么选 ESP32 + Arduino：
 *   - 便宜、常见、带 Wi-Fi，能独立连路由器（不依赖电脑中转，手机可直连）。
 *   - Arduino 生态资料多，初学者能自己改引脚与逻辑。
 *
 * 硬件接线（默认配置，改 LED_PIN 即可适配你的板子）：
 *   - LED 正极（长脚） -> GPIO 4（通过 220Ω 限流电阻）
 *   - LED 负极（短脚） -> GND
 *   - 板载 LED 引脚和有效电平因开发板而异，需查具体板卡原理图。
 *
 * 供电与电平注意（不要凭空假设，按你的板子确认）：
 *   - 根据具体开发板的数据手册确认引脚、电压与电流限制；LED 必须串限流电阻。
 *   - 红色 LED 压降约 2V：(3.3-2)/0.01 = 130Ω，取 220Ω 更安全（亮度略低）。
 *   - 驱动舵机/电机绝不能直接接 GPIO：需要独立电源与驱动板，
 *     见 docs/hardware.md 的舵机章节。
 *
 * 依赖（Arduino IDE 库管理器安装）：
 *   - WiFi（ESP32 板包自带）
 *   - WebServer（ESP32 板包自带）
 *   - ArduinoJson（Benoit Blanchon，v7）
 *
 * 上传后行为：
 *   - 串口 115200 打印本机 IP（手机 App 里填这个 IP，端口 8081）。
 *   - LED 状态同时上报到 /status，便于手机侧查询。
 *
 * 安全边界：
 *   - 本固件只监听局域网，不连接任何云端、不上报任何数据。
 *   - 没有身份认证：只应在可信局域网使用（与推流一致的安全前提）。
 */
#include <WiFi.h>
#include <WebServer.h>
#include <ArduinoJson.h>

// =====================================================================
// 配置区（按你的实际环境修改）
// =====================================================================

// Wi-Fi 凭据：不要提交到公开仓库；建议用 #include "secrets.h" 或
// 在上传前用 Arduino IDE 的 "Secret" 机制管理。
#ifndef WIFI_SSID
#define WIFI_SSID "YOUR_WIFI_SSID"
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#endif

// HTTP 服务端口：必须与手机端 ControlProtocol.DEFAULT_PORT 一致。
const uint16_t HTTP_PORT = 8081;

// LED 引脚（ESP32 GPIO4 = IO4）。改这里适配你的接线。
const int LED_PIN = 4;

// 协议版本：必须与手机端 ControlProtocol.VERSION 一致。
const int PROTOCOL_VERSION = 1;

// 动作名字符串：必须与手机端 ControlProtocol.ACTION_* 一致。
const char *ACTION_LED_ON = "led_on";
const char *ACTION_LED_OFF = "led_off";
const char *ACTION_SET_LED = "set_led";
const char *ACTION_SERVO_SET = "servo_set";
const char *ACTION_STOP = "stop";
const char *ACTION_STATUS = "status";

/** 构造 ack JSON（前向声明：handleControl 先用到底层实现）。 */
String buildAckJson(const String &requestId, const char *status,
                    const char *message);

// =====================================================================
// 状态
// =====================================================================

WebServer server(HTTP_PORT);

// 当前 LED 状态（true = 亮）。volatile：可能被 HTTP 回调改写。
volatile bool g_ledOn = false;

// 单调毫秒计数，用于反馈里的 executedAtMs（设备侧时间）。
unsigned long g_bootMs = 0;

// 重复命令去重：记住最近处理过的 requestId（线性小缓存，足够本场景）。
const int DEDUP_CACHE_SIZE = 16;
String g_seenRequestIds[DEDUP_CACHE_SIZE];
int g_seenIndex = 0;

/** 判断 requestId 是否已成功处理过。失败的命令不能记为成功。 */
bool alreadyHandled(const String &requestId) {
  for (int i = 0; i < DEDUP_CACHE_SIZE; i++) {
    if (g_seenRequestIds[i] == requestId && requestId.length() > 0) {
      return true;
    }
  }
  return false;
}

void rememberHandled(const String &requestId) {
  g_seenRequestIds[g_seenIndex] = requestId;
  g_seenIndex = (g_seenIndex + 1) % DEDUP_CACHE_SIZE;
}

// =====================================================================
// LED 控制
// =====================================================================

void setLed(bool on) {
  g_ledOn = on;
  digitalWrite(LED_PIN, on ? HIGH : LOW);
  Serial.printf("[led] %s\n", on ? "ON" : "OFF");
}

// =====================================================================
// HTTP 处理
// =====================================================================

/**
 * POST /control —— 手机下发的控制命令。
 *
 * 请求体（JSON）：
 *   {"v":1,"requestId":"req-xxx","target":"led0","action":"led_on",
 *    "params":{"brightness":255}}
 *
 * 响应（JSON）：
 *   {"requestId":"req-xxx","status":"received","message":"GPIO updated; LED not sensed"}
 *
 * status 取值：
 *   received —— 已处理 GPIO 命令，无法确认 LED 实际发光
 *   failed   —— 参数或动作不合法
 *
 * 没有 LED 状态传感器，所以不能声称物理动作已确认。
 */
void handleControl() {
  if (server.method() != HTTP_POST) {
    server.send(405, "application/json", "{\"status\":\"failed\",\"message\":\"method not allowed\"}");
    return;
  }

  String body = server.arg("plain");
  if (body.length() == 0) {
    server.send(400, "application/json", "{\"status\":\"failed\",\"message\":\"empty body\"}");
    return;
  }

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, body);
  if (err) {
    server.send(400, "application/json",
                "{\"status\":\"failed\",\"message\":\"invalid json\"}");
    return;
  }

  int version = doc["v"] | 0;
  String requestId = doc["requestId"] | "";
  String target = doc["target"] | "led0";
  String action = doc["action"] | "";
  JsonObject params = doc["params"].as<JsonObject>();

  if (version != PROTOCOL_VERSION) {
    server.send(400, "application/json",
                "{\"status\":\"failed\",\"message\":\"protocol version mismatch\"}");
    return;
  }
  if (requestId.length() == 0 || action.length() == 0) {
    server.send(400, "application/json",
                "{\"status\":\"failed\",\"message\":\"missing requestId/action\"}");
    return;
  }
  if (target != "led0") {
    server.send(400, "application/json", buildAckJson(requestId, "failed", "unknown target"));
    return;
  }

  // 重复命令去重：同一个 requestId 只执行一次
  if (alreadyHandled(requestId)) {
    Serial.printf("[ctrl] duplicate requestId=%s (ignored)\n", requestId.c_str());
    server.send(200, "application/json",
                buildAckJson(requestId, "received", "duplicate ignored"));
    return;
  }

  Serial.printf("[ctrl] id=%s target=%s action=%s\n",
                requestId.c_str(), target.c_str(), action.c_str());

  // ---- 执行动作 ----
  if (action == ACTION_LED_ON) {
    setLed(true);
  } else if (action == ACTION_LED_OFF) {
    setLed(false);
  } else if (action == ACTION_SET_LED) {
    server.send(501, "application/json", buildAckJson(requestId, "failed", "brightness not implemented"));
    return;
  } else if (action == ACTION_STOP) {
    // 立即停止所有执行器：LED 灭。接舵机/电机时这里必须同时切断它们
    // 的动力，作为"设备端超时停止"的手动版本。
    setLed(false);
  } else if (action == ACTION_STATUS) {
    // 只读查询：不回 executed，回 received + 当前状态
    String json = "{\"requestId\":\"" + requestId +
                  "\",\"status\":\"received\",\"ledOn\":" +
                  (g_ledOn ? "true" : "false") + "}";
    server.send(200, "application/json", json);
    return;
  } else if (action == ACTION_SERVO_SET) {
    // 尚未实现舵机：明确拒绝，不假装成功
    server.send(501, "application/json",
                "{\"status\":\"failed\",\"message\":\"servo not implemented in this firmware\"}");
    return;
  } else {
    server.send(400, "application/json",
                "{\"status\":\"failed\",\"message\":\"unknown action\"}");
    return;
  }

  rememberHandled(requestId);
  server.send(200, "application/json", buildAckJson(requestId, "received", "GPIO updated; LED not sensed"));
}

/** 构造 ack JSON；仅确有完成反馈时附带设备侧时间。 */
String buildAckJson(const String &requestId, const char *status,
                    const char *message) {
  String json = "{\"requestId\":\"" + requestId + "\",\"status\":\"" + status +
                "\"";
  if (strcmp(status, "executed") == 0) json += ",\"executedAtMs\":" + String(millis());
  if (message && strlen(message) > 0) {
    json += ",\"message\":\"" + String(message) + "\"";
  }
  json += "}";
  return json;
}

/** GET /status —— 只读查询当前状态（手机连接前用它验证链路）。 */
void handleStatus() {
  String json = "{\"ledOn\":" + String(g_ledOn ? "true" : "false") +
                ",\"uptimeMs\":" + String(millis()) + "}";
  server.send(200, "application/json", json);
}

void handleNotFound() {
  server.send(404, "application/json", "{\"status\":\"failed\",\"message\":\"not found\"}");
}

// =====================================================================
//  Arduino 入口
// =====================================================================

void setup() {
  Serial.begin(115200);
  delay(200);
  g_bootMs = millis();

  pinMode(LED_PIN, OUTPUT);
  setLed(false);   // 上电默认灭：绝不"上电就亮"

  Serial.println();
  Serial.println("[boot] PhoneVision Lab LED controller");

  // ---- 连接 Wi-Fi ----
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("[wifi] connecting to %s", WIFI_SSID);
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 60) {
    delay(500);
    Serial.print(".");
    tries++;
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println();
    Serial.println("[wifi] FAILED — 请检查 SSID/密码，或改用手机热点");
    // 连不上也不死循环刷屏；继续跑 HTTP（至少 /status 可被本机访问）
  } else {
    Serial.println();
    Serial.print("[wifi] connected, IP = ");
    Serial.println(WiFi.localIP());
    Serial.printf("[http] listening on port %d\n", HTTP_PORT);
    Serial.println("[hint] 在手机 App 的硬件联动面板填上面的 IP，端口 8081");
  }

  server.on("/control", HTTP_POST, handleControl);
  server.on("/status", HTTP_GET, handleStatus);
  server.onNotFound(handleNotFound);
  server.begin();
}

void loop() {
  server.handleClient();
  // 设备端看门狗：如果超过 10 分钟没有任何命令，且 LED 是亮的，
  // 自动熄灭。这样即使手机死机/断网，LED 也不会一直亮着。
  // 说明：这是"设备端超时停止"，不依赖手机在断线后还能发命令。
  static unsigned long lastCommandAt = 0;
  static bool watchdogArmed = false;
  if (g_ledOn && !watchdogArmed) {
    watchdogArmed = true;
    lastCommandAt = millis();
  }
  if (watchdogArmed && g_ledOn && millis() - lastCommandAt > 600000UL) {
    Serial.println("[watchdog] 10 分钟无命令，自动关闭 LED");
    setLed(false);
    watchdogArmed = false;
  }
  if (!g_ledOn) {
    watchdogArmed = false;
  }
  delay(2);
}
