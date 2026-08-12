# PhoneVision Lab

> [English](README.md)

把旧 Android 手机变成视觉传感器，在 Windows 上用 OpenCV 学习机器视觉。通过
WiFi（未来还有 USB）传输 MJPEG 视频流。

**状态：Pre-release / 开发快照，尚未达到 v1.0。**

## 已验证可用的能力

- Android Camera2 实时预览
- WiFi MJPEG HTTP 推流
- `GET /ping` 和 `GET /stream` 接口
- Windows Tkinter 客户端（画面区 + 模式面板 + 指标栏）
- 严格 MJPEG 解析器（boundary + Content-Length + SOI/EOI）
- 灰度 / Canny / HSV / 轮廓实验
- 完全本地运行，无云端 / 无账号 / 无遥测

## 正在建设、尚未完成

- PySide6 正式 Windows Studio（推荐方向，但尚未与 Tkinter 功能对齐，正式入口也未切换）
- USB 正式连接体验（adb forward 只是可复用的技术方案）
- 自动设备发现
- 安全配对
- 远程开始/停止与相机参数控制
- 学习模式 / 实验模式 / 项目保存 / Python 代码导出
- Windows 安装包
- 双语产品 UI

## 模块

| 路径 | 说明 |
| --- | --- |
| `android/` | Android 传感器 App：Camera2 + ImageReader(JPEG) + NanoHTTPD MJPEG 服务器 |
| `pc-client/` | Windows 客户端：严格 MJPEG 读取、OpenCV 视觉模式、Tkinter GUI、PySide6 GUI（建设中） |

## 重要警告

- **尚未达到 v1.0。**
- 当前 HTTP 流**没有身份认证**，手机推流时同一局域网内的任何人都可以拉流。
- 仅应在**可信的本地网络**中使用。
- **USB 还不是正式产品功能。**
- 自动发现与安全配对**尚未实现**。

## 开源许可证

[MIT](LICENSE)
