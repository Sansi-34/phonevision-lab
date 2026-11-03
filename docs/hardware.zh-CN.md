# 硬件协议与接线说明

本文定义**手机 → 外部控制器**的通信协议，并给出 ESP32 LED 控制器的接线说明。

> 协议是手机端 `ControlProtocol.kt`、PC 端 `pvl_hardware.py`、控制器固件 `led_controller.ino` 三方的共同契约。改任何一处都必须同步另外两处。

---

## 1. 通信方式选择

| 方式 | 是否采用 | 理由 |
| --- | --- | --- |
| 局域网 HTTP | **采用** | 手机可直连控制器，不依赖公网/云；控制器接同一 Wi-Fi 即可 |
| BLE | 未采用 | 配对与 MTU 复杂度高，首版不必要 |
| USB 串口 | 未采用 | 需要 OTG 线，且手机同时充电与调试会冲突 |

**优先手机直连**：控制器独立连路由器，手机与它在同一局域网即可通信，不需要电脑中转。

**电脑端的作用**：配置与调试。`pvl_hardware.py` 提供同构的规则引擎与设备适配器，可在电脑上验证协议与规则逻辑（模拟验证），但**模拟设备不算真机验收通过**。

---

## 2. 协议格式

### 2.1 命令（手机 → 控制器）

`POST http://<控制器IP>:8081/control`

`Content-Type: application/json; charset=utf-8`

```json
{
  "v": 1,
  "requestId": "req-1a2b3c-1",
  "target": "led0",
  "action": "led_on",
  "params": {}
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `v` | int | 协议版本，必须等于 `1` |
| `requestId` | string | **全局唯一请求编号**。控制器回显同一个值；手机据此做重复命令去重 |
| `target` | string | 目标设备标识。默认 `led0`；多执行器时区分 |
| `action` | string | 动作类型，见下表 |
| `params` | object | 动作参数（可省略） |

#### 动作类型

| action | params | 说明 | 允许自动重试 |
| --- | --- | --- | --- |
| `led_on` | — | LED 开 | 是 |
| `led_off` | — | LED 关 | 是 |
| `set_led` | `brightness` (0-255) | 当前固件未实现调光，明确返回失败 | 否 |
| `servo_set` | `angle` (0-180) | 设置舵机角度（**当前固件未实现**） | **否** |
| `stop` | — | 立即停止所有执行器 | 是 |
| `status` | — | 只读查询 | 是 |

> **为什么只有部分动作允许重试**：LED 开关是幂等的，重复执行结果相同。舵机/电机是运动动作，重复执行会让机构来回运动，必须由用户手动再次触发。

### 2.2 反馈（控制器 → 手机）

```json
{
  "requestId": "req-1a2b3c-1",
  "status": "executed",
  "executedAtMs": 12345,
  "message": ""
}
```

| 字段 | 说明 |
| --- | --- |
| `requestId` | 回显命令编号 |
| `status` | `received` / `executed` / `failed` |
| `executedAtMs` | 控制器侧单调毫秒（仅设备能确认动作完成时有意义） |
| `message` | 人类可读说明（错误原因等） |

#### 状态语义（**必须严格遵守**）

| 状态 | 含义 | 界面显示 |
| --- | --- | --- |
| `received` | 控制器确认**收到**了命令 | "已接收" |
| `executed` | 控制器确认**已执行**（仅设备能确认动作完成时） | "已执行" |
| `failed` | 参数或动作不合法 | "失败" |

> **关键约束**：设备只确认"收到了"时，界面**只能显示"已接收"，绝不能显示"执行成功"**。
> 当前 LED 固件仅能确认 GPIO 命令已处理，没有传感器确认 LED 是否发光，因此回 `received`；实际亮灭须人工确认。
> 对舵机/电机（需要时间才能到目标位置），**必须等机构真正到位后才能回 `executed`**，否则界面会把"已接收"误显示成"执行成功"。

### 2.3 只读查询

`GET http://<控制器IP>:8081/status`

```json
{
  "ledOn": false,
  "uptimeMs": 123456
}
```

连接前用它验证链路，**不动任何执行器**。

---

## 3. 可靠性与安全机制

| 机制 | 实现 |
| --- | --- |
| **命令去重** | 手机端按 `requestId` 缓存已发送命令，重复请求直接返回上次结果，不重复执行 |
| **超时** | 默认 2 秒；超时记为失败 |
| **有限重试** | 仅 `RETRYABLE_ACTIONS` 里的幂等动作；默认最多 2 次 |
| **断连不重放** | 手机端**不缓存待发送队列**；断线期间的命令直接失败，重连后由用户手动再次触发 |
| **设备端看门狗** | 固件 10 分钟无命令自动关 LED，不依赖手机在断线后还能发命令 |
| **上电默认状态** | 固件 `setup()` 里 LED 默认灭，绝不"上电就亮" |

---

## 4. ESP32 接线说明

### 4.1 器件清单

| 器件 | 数量 | 备注 |
| --- | --- | --- |
| ESP32 开发板 | 1 | 固件尚未经具体型号实机验证，先确认引脚与板卡兼容 |
| LED（5mm） | 1 | 红色最直观 |
| 电阻 220Ω | 1 | **限流电阻，必须串** |
| 面包板 + 杜邦线 | 若干 | |

### 4.2 接线图

```
ESP32 GPIO 4 ────[220Ω]────┬──── LED 长脚（阳极）
                            │
                           LED
                            │
ESP32 GND ─────────────────┴──── LED 短脚（阴极）
```

### 4.3 电平与供电（不要凭空假设）

| 项目 | 值 | 说明 |
| --- | --- | --- |
| GPIO 输出电压 | 3.3V | ESP32 不是 5V 容忍，不要直接接 5V 器件 |
| 引脚电流 | 按具体芯片和板卡数据手册 | 不假设所有 ESP32 型号有相同限值 |
| 红色 LED 压降 | 约 2.0V | 计算电阻用 |
| 电阻计算 | `(3.3 - 2.0) / 0.01 = 130Ω` | 取 220Ω 更安全（亮度略低，寿命更长） |
| 供电 | USB 5V | 开发板自带 LDO 输出 3.3V |

### 4.4 如果用板载 LED

板载 LED 的引脚、极性及是否存在因板卡而异；先查具体型号原理图，再配置 `LED_PIN`。

### 4.5 舵机/电机（后续扩展，先看这里）

**绝不直接接 GPIO**：

- 舵机（如 SG90）工作电流 100-250mA，超过 GPIO 的 40mA 上限。
- 电机启动电流可达数百 mA 到数 A，还会反灌电动势损坏 GPIO。

必须：

- 独立电源（舵机 5V / 电机按额定电压），**与 ESP32 共地**。
- 驱动板（舵机可直接用 ESP32 的 LEDC PWM；电机用 H 桥如 L298N/DRV8833）。
- 信号线串限流电阻，电源加退耦电容。
- 固件实现 `servo_set` 时，必须**等机构到位后才回 `executed`**，并保留 `stop` 立即断电。

---

## 5. 固件配置

`controller-firmware/led_controller/led_controller.ino` 顶部配置区：

```cpp
#define WIFI_SSID "YOUR_WIFI_SSID"        // 改成你的 Wi-Fi 名
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD" // 改成你的 WiFi 密码

const uint16_t HTTP_PORT = 8081;   // 必须与手机端 DEFAULT_PORT 一致
const int LED_PIN = 4;             // 改成你的接线引脚
const int PROTOCOL_VERSION = 1;    // 必须与手机端一致
```

> Wi-Fi 凭据不要提交到公开仓库。建议放在单独的 `secrets.h` 并加入 `.gitignore`。

### 依赖

Arduino IDE → 库管理器安装：

- ESP32 板包（`esp32` by Espressif）
- `ArduinoJson` by Benoit Blanchon（**v7**，v6 API 不同）

---

## 6. 调试

```powershell
# 查控制器是否在线（应返回 JSON）
curl http://192.168.x.x:8081/status

# 手动开灯（应返回 executed）
curl -X POST http://192.168.x.x:8081/control `
  -H "Content-Type: application/json" `
  -d '{\"v\":1,\"requestId\":\"test-1\",\"target\":\"led0\",\"action\":\"led_on\"}'

# 同一个 requestId 再发一次（应返回 received + duplicate ignored，且不重复执行）
curl -X POST http://192.168.x.x:8081/control `
  -H "Content-Type: application/json" `
  -d '{\"v\":1,\"requestId\":\"test-1\",\"target\":\"led0\",\"action\":\"led_on\"}'
```

串口监视器（115200）会打印每条命令与去重情况。

---

## 7. 未验证事项（诚实声明）

| 项 | 状态 |
| --- | --- |
| 协议格式 | 三端代码一致，PC 侧单测覆盖序列化/去重/重试规则 |
| 模拟设备链路 | 已验证（`tests/test_pvl_hardware.py`，46 项断言） |
| **真实 ESP32 + LED** | **未验证**：需要真机与硬件 |
| **手机直连控制器** | **未验证**：需要真机与硬件 |
| 舵机/电机 | 未实现（`servo_set` 明确返回未实现，不假装成功） |
