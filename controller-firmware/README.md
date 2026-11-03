# PhoneVision Lab — LED 控制器固件（ESP32）

把识别结果变成真实灯光：手机通过局域网 HTTP 向这块板子发命令，板子驱动 LED
并回报状态。

> 完整协议（命令/反馈格式、四态语义、去重与重试规则）见
> [`docs/hardware.zh-CN.md`](../../docs/hardware.zh-CN.md)。
> 本节只讲"怎么烧录、怎么接线、怎么调试"。

---

## 1. 硬件清单

| 器件 | 数量 | 备注 |
| --- | --- | --- |
| ESP32 开发板 | 1 | 任意带 Wi-Fi 的型号 |
| LED（5mm） | 1 | 红色最直观 |
| 电阻 220Ω | 1 | **限流电阻，必须串** |
| 面包板 + 杜邦线 | 若干 | |

## 2. 接线

```
ESP32 GPIO 4 ────[220Ω]────┬──── LED 长脚（阳极）
                            │
                           LED
                            │
ESP32 GND ─────────────────┴──── LED 短脚（阴极）
```

**电平与供电（按你的板子核实，不要凭空假设）**：

| 项目 | 值 |
| --- | --- |
| GPIO 输出电压 | 3.3V（ESP32 不是 5V 容忍） |
| 单脚最大电流 | 约 40mA |
| 红色 LED 压降 | 约 2.0V |
| 电阻计算 | `(3.3 - 2.0) / 0.01 = 130Ω` → 取 220Ω 更安全 |
| 供电 | USB 5V，板载 LDO 输出 3.3V |

### 用板载 LED

多数 ESP32 开发板的板载 LED 在 **GPIO 2**。把 `LED_PIN` 改成 `2`，无需外接器件。

### 关于舵机 / 电机

**绝不直接接 GPIO**。舵机工作电流 100-250mA、电机启动电流可达数安，
都会烧坏 GPIO。必须独立电源 + 驱动板 + 共地。详见
[`docs/hardware.zh-CN.md`](../../docs/hardware.zh-CN.md) 第 4.5 节。

## 3. 烧录

### 3.1 安装依赖

Arduino IDE → 首选项 → 附加开发板网址，加入 ESP32 板包 URL，然后：

1. **工具 → 开发板 → 开发板管理器**，安装 `esp32`（Espressif）。
2. **项目 → 加载库 → 库管理器**，安装 `ArduinoJson`（Benoit Blanchon，**v7**；
   v6 的 API 不同，用错会编译失败）。

### 3.2 配置

编辑 `led_controller.ino` 顶部配置区：

```cpp
#define WIFI_SSID "YOUR_WIFI_SSID"          // 改成你的 Wi-Fi 名
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"  // 改成你的 Wi-Fi 密码

const uint16_t HTTP_PORT = 8081;   // 必须与手机端默认端口一致
const int LED_PIN = 4;             // 改成你的接线引脚
const int PROTOCOL_VERSION = 1;    // 必须与手机端一致
```

> **不要把 Wi-Fi 凭据提交到公开仓库。** 建议放到同目录的 `secrets.h`
> （已在 `.gitignore` 中忽略），然后 `#include "secrets.h"`。

### 3.3 上传

1. 选对开发板（如 "ESP32 Dev Module"）与端口。
2. 点上传。
3. 打开串口监视器，波特率 **115200**。

启动日志：

```
[boot] PhoneVision Lab LED controller
[wifi] connecting to YOUR_WIFI_SSID
[wifi] connected, IP = 192.168.x.x
[http] listening on port 8081
[hint] 在手机 App 的硬件联动面板填上面的 IP，端口 8081
```

记住这个 IP，手机端要用。

## 4. 调试

```bash
# 查是否在线（应返回 JSON，不动任何执行器）
curl http://192.168.x.x:8081/status

# 手动开灯（应返回 executed）
curl -X POST http://192.168.x.x:8081/control \
  -H "Content-Type: application/json" \
  -d '{"v":1,"requestId":"test-1","target":"led0","action":"led_on"}'

# 同一个 requestId 再发一次（应返回 received + duplicate ignored，且不重复执行）
curl -X POST http://192.168.x.x:8081/control \
  -H "Content-Type: application/json" \
  -d '{"v":1,"requestId":"test-1","target":"led0","action":"led_on"}'

# 关灯
curl -X POST http://192.168.x.x:8081/control \
  -H "Content-Type: application/json" \
  -d '{"v":1,"requestId":"test-2","target":"led0","action":"led_off"}'
```

串口监视器会打印每条命令与去重情况。

## 5. 固件内置的安全行为

| 行为 | 说明 |
| --- | --- |
| 上电默认灭灯 | `setup()` 里 `setLed(false)`，绝不"上电就亮" |
| 重复命令去重 | 记住最近 16 个 requestId，重复的不再执行 |
| 未知动作明确拒绝 | 返回 `failed` + 原因，不假装成功 |
| `servo_set` 未实现 | 返回 501 + 明确说明，不假装成功 |
| 设备端看门狗 | 10 分钟无命令自动关 LED，不依赖手机断线后还能发命令 |
| `stop` 立即关执行器 | 作为手动版"紧急停止" |

## 6. 常见问题

| 现象 | 原因 |
| --- | --- |
| 串口一直打印 `.` 连不上 | SSID/密码错，或路由器是 5GHz（ESP32 多数只支持 2.4GHz） |
| `curl` 连不上 | IP 不对 / 不在同一网段 / 防火墙挡了 8081 |
| 返回 `protocol version mismatch` | 手机端与固件的 `PROTOCOL_VERSION` 不一致 |
| 灯不亮但返回 executed | 接线问题：检查电阻、LED 极性、引脚号 |
| 灯很暗 | 电阻太大；换 130-150Ω（注意别超过 GPIO 电流上限） |
| 编译报 `deserializeJson` 相关错 | ArduinoJson 版本是 v6；请装 v7 |

## 7. 许可证

本固件源码按仓库根目录的 [MIT](../../LICENSE) 许可发布。
所用第三方库许可：ArduinoJson（MIT）、ESP32 Arduino 核心（LGPL-2.1）。
