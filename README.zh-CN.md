# PhoneVision Lab

> [English](README.md)

把旧 Android 手机变成视觉传感器，在 Windows 上用 OpenCV 学习机器视觉。通过
WiFi 传输 MJPEG 视频流，五种视觉模式、中英双语界面、完全本地运行、无账号、
无遥测。

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
```

- **手机 = 传感器**：负责采集画面、JPEG 编码并推送 MJPEG 视频流。
- **电脑 = 大脑**：负责解析视频流、应用五种视觉模式并展示结果供学习。

## 已验证可用的能力

- Android Camera2 实时预览与 WiFi MJPEG HTTP 推流
- `GET /ping`（JSON 状态）与 `GET /stream`（multipart MJPEG）接口
- Windows PySide6 视觉工作台（默认客户端）：顶栏 + 实时画面 + 模式检查器 +
  可折叠诊断区，中英双语
- 严格 MJPEG 解析器（boundary + Content-Length + SOI/EOI）
- 五种视觉模式：原始 / 灰度 / Canny / HSV / 轮廓
- Legacy Tkinter 客户端（仅兼容保留）：`python legacy_main.py`
- 完全本地运行——无云端、无账号、无遥测

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
