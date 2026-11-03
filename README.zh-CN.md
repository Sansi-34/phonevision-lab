# PhoneVision Lab

> [English](README.md)

把旧 Android 手机变成视觉传感器，在 Windows 上用 OpenCV 学习机器视觉。通过
WiFi 传输 MJPEG 视频流，五种视觉模式、中英双语界面、完全本地运行、无账号、
无遥测。

同时打通完整学习闭环：在电脑上采集自定义类别图片 → 训练轻量分类模型 →
导出模型包 → **手机本机离线推理** → 按识别结果控制真实硬件（LED）→
导出可复现的性能记录。

**状态：Pre-release / 开发快照，尚未达到 v1.0。**

## 系统架构

```
 ┌─────────────────────┐   MJPEG over HTTP (WiFi)   ┌──────────────────────────┐
 │   Android 手机       │  ───────────────────────►  │   Windows 电脑           │
 │  （传感器）          │   GET /stream             │  （视觉工作台）           │
 │  Camera2 + JPEG      │   GET /ping  (JSON)       │  PySide6 界面 + OpenCV    │
 │  NanoHTTPD 服务器    │                            │  原始 / 灰度 / Canny /   │
 └─────────────────────┘                            │  HSV / 轮廓              │
                                                    └──────────────────────────┘

 模式二（与推流互斥）：
 ┌─────────────────────┐                            ┌──────────────────────────┐
 │  本机 AI 推理        │  TFLite、CPU、离线         │  训练与导出              │
 │  相机 → Bitmap       │ ─────────────────────────► │  数据集 / 划分 / 训练    │
 │  → 预测              │                            │  → .pvlmodel.zip         │
 │  → 规则 → HTTP:8081  │ ───────────┐               └──────────────────────────┘
 └─────────────────────┘            ▼
                          外部控制器 → 真实 LED
```

- **手机 = 传感器**：负责采集画面、JPEG 编码并推送 MJPEG 视频流。
- **电脑 = 大脑**：负责解析视频流、应用五种视觉模式并展示结果供学习。
- **手机 = 边缘设备（模式二）**：本机运行分类模型（推理不需要网络），并可向
  同一局域网内的外部控制器下发命令。

## 已验证可用的能力

- Android Camera2 实时预览与 WiFi MJPEG HTTP 推流
- `GET /ping`（JSON 状态）与 `GET /stream`（multipart MJPEG）接口
- Windows PySide6 视觉工作台（默认客户端）：顶栏 + 实时画面 + 模式检查器 +
  可折叠诊断区，中英双语
- 严格 MJPEG 解析器（boundary + Content-Length + SOI/EOI）
- 五种视觉模式：原始 / 灰度 / Canny / HSV / 轮廓
- Legacy Tkinter 客户端（仅兼容保留）：`python legacy_main.py`
- 完全本地运行——无云端、无账号、无遥测

### 学习闭环（V0-B）

- **数据集管理**：创建/打开数据集、新增与重命名类别、浏览与删除样本、
  从实时画面单张或按间隔连续采集。
- **按批次划分**：训练/验证集按"采集批次"切分，绝不按单张随机划分，
  避免相邻近似帧跨集合导致验证指标虚高；随机种子与比例一并记录。
- **数据体检**：类别缺失、样本不足、图片无法解码、严重失衡都会逐条列出，
  不伪造验证指标。
- **训练**：MobileNetV3Small 迁移学习（默认 CPU；仅在真的检测到 GPU 时才
  提供 GPU 选项）。进度、损失、验证准确率实时可见，取消为协作式。
- **导出**：Keras → TFLite（float16），并用固定样本做导出一致性校验
  （最大绝对误差 + Top-1 一致率）。**校验不通过时明确拒绝导出**。
- **模型包**：自描述 `.pvlmodel.zip`，含模型文件、类别标签、输入尺寸、
  张量布局、颜色顺序、缩放/裁剪/归一化规则、输出解释方式、训练参数与
  预训练权重来源。
- **手机本机推理**：导入模型包后显示预览、预测类别、置信度、实测推理帧率与
  各阶段耗时；导入后推理完全离线。
- **硬件联动**：识别结果 → 规则引擎 → 设备适配器 → 控制器。连续确认、
  滞回与冷却防止频繁抖动；命令按 requestId 去重；只有幂等动作有限重试；
  停止自动控制后不再产生新的自动动作。
- **性能分析**：各阶段 mean/P50/P95、丢弃帧、命令确认耗时，可导出
  CSV / 摘要 / JSON。

### 网页版实验台（web 构建）

同一套学习闭环还有本地网页版，位于 `web/`：

```bash
python web/launcher.py      # 会打印 http://127.0.0.1:<端口>
```

- 数据集采集、训练与导出、硬件、性能四个页面复用 `pc-client` 的**同一套**模块，
  业务逻辑没有第二份实现
- 只绑定 `127.0.0.1`，并校验 `Host`/`Origin`，外网站点无法驱动本机接口；但仍无
  账号体系，请按"单用户本机工具"使用
- 平台说明：[docs/web-platform.zh-CN.md](docs/web-platform.zh-CN.md)；
  界面规格：[docs/ui-ux-web.zh-CN.md](docs/ui-ux-web.zh-CN.md)

## 快速开始

```bash
# 正式默认客户端（PySide6 视觉工作台），中文或英文界面
python main.py --host 192.168.x.x
python main.py --host 192.168.x.x --lang en

# Legacy Tkinter 客户端（仅兼容保留）
python legacy_main.py --host 192.168.x.x
```

1. 先在手机 App 上点击**开始推流**。
2. 把 `192.168.x.x` 换成手机 App 界面显示的 IP（不是示例 IP），端口默认 8080。
3. 用按钮或数字键 1-5 切换视觉模式；`S` 保存截图、`R` 重连、`Ctrl+Q` 退出。
4. 诊断区默认收起；语言选择保存在本机。

需要 Python 3.12+：`pip install -r requirements.txt`。

训练需要额外一组可选依赖（TensorFlow，约 500 MB），与基础依赖分离，
保证普通预览/采集装得轻、跑得快：

```bash
pip install -r requirements.txt -r requirements-train.txt
```

完整操作指南（数据集 → 训练 → 导出 → 手机推理 → LED → 性能）：
[docs/user-guide.zh-CN.md](docs/user-guide.zh-CN.md)。
模型、权重与许可证说明：[docs/training.zh-CN.md](docs/training.zh-CN.md)。
硬件协议与接线说明：[docs/hardware.zh-CN.md](docs/hardware.zh-CN.md)。

## 运行时兼容性（已核实，非假设）

| 组件 | 要求 | 说明 |
| --- | --- | --- |
| TFLite AAR 2.16.1 | `minSdk 19` | 兼容本项目 `minSdk 21`（Android 5.0） |
| 覆盖 ABI | arm64-v8a、armeabi-v7a、x86、x86_64 | 覆盖绝大多数存量手机 |
| 加速 | **默认仅 CPU** | NNAPI/GPU 委派在不同厂商 ROM 行为差异大，未逐台验证前不启用 |

ONNX Runtime Android 已评估但**未采用**：其 AAR 要求 `minSdk 24`，
会把最低系统版本提到 Android 7.0，与"旧手机"目标冲突。

## Windows 便携包（无需安装 Python）

发布时提供 `PhoneVisionLab-0.1.0-alpha.1-windows-x64.zip`（PyInstaller onedir）。
**尚未正式发布**，仅为本地构建产物。

1. 解压 ZIP，双击 `PhoneVisionLab.exe`。
2. 启动页输入手机 App 界面显示的 IP（不是示例 IP），端口默认 8080；手机必须先
   点击"开始推流"。
3. 最近成功地址只保存在本机（QSettings），可随时编辑。
4. 日志位置：`%LOCALAPPDATA%\PhoneVisionLab\logs\phonevision.log`（本机轮转，
   不记录图像内容，无遥测）。
5. 顶栏可切换简体中文 / English，选择保存在本机。
6. 未签名：Windows SmartScreen 可能提示"未知发布者"，属正常；选择"仍要运行"即可。

校验 ZIP 完整性（`certutil` 或 `sha256sum`）：

```powershell
certutil -hashfile PhoneVisionLab-0.1.0-alpha.1-windows-x64.zip SHA256
```

源码运行仍是官方方式（见上方"快速开始"）。第三方许可与 Qt/PySide6 的
LGPL-3.0 合规细节随包附带（`THIRD_PARTY_NOTICES.md` + `licenses/`），并记录在
[docs/qt-lgpl-compliance.md](docs/qt-lgpl-compliance.md)。

## 隐私

- 完全本地运行：无遥测、无统计、无云端、无账号。
- 本地日志只记录版本/启动/连接状态/错误文本——绝不记录画面内容、截图、参数值
  或密钥。
- **注意**：HTTP 流**没有身份认证**，手机推流时同一局域网内任何人都可以拉流。
  仅应在可信的本地网络中使用。

## Roadmap

USB 传输、自动设备发现、安全配对、学习/实验模式、项目保存与签名发布都在计划中，
不承诺日期。详见 [ROADMAP.md](ROADMAP.md)。

## 故障排查

见 [docs/troubleshooting.md](docs/troubleshooting.md)——涵盖 SmartScreen 提示、
连接失败、画面质量问题与日志位置。

## 参与贡献

见 [CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md) 与 [SUPPORT.md](SUPPORT.md)。
安全问题见 [SECURITY.md](SECURITY.md)。

## 开源许可证

[MIT](LICENSE)。Qt / PySide6 以 **LGPL-3.0**（Community Edition）条款使用——
见 [docs/qt-lgpl-compliance.md](docs/qt-lgpl-compliance.md)。
