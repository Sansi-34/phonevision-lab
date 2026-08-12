# PhoneVision Lab

> [English](README.md)

把旧 Android 手机变成视觉传感器，在 Windows 上用 OpenCV 学习机器视觉。通过
WiFi（未来还有 USB）传输 MJPEG 视频流。

**状态：Pre-release / 开发快照，尚未达到 v1.0。**

## 已验证可用的能力

- Android Camera2 实时预览
- WiFi MJPEG HTTP 推流
- `GET /ping` 和 `GET /stream` 接口
- Windows PySide6 视觉工作台（默认客户端）：顶栏 + 最大画面区 + 模式检查器 + 可折叠诊断区，中英双语
- Legacy Tkinter 客户端（兼容保留）：`python legacy_main.py`
- 严格 MJPEG 解析器（boundary + Content-Length + SOI/EOI）
- 灰度 / Canny / HSV / 轮廓实验
- 完全本地运行，无云端 / 无账号 / 无遥测

## 快速开始

```bash
# 正式默认客户端（PySide6 视觉工作台），中文或英文界面
python main.py --host 192.168.x.x
python main.py --host 192.168.x.x --lang en

# Legacy Tkinter 客户端（兼容保留）
python legacy_main.py --host 192.168.x.x
```

把 `192.168.x.x` 换成手机 App 界面显示的 IP。先在手机上点击"开始推流"。
参数按当前视觉模式显示；诊断区默认收起；快捷键：S 保存、R 重连、1-5 切模式、
Ctrl+Q 退出。语言选择保存在本机；项目无遥测。

## 正在建设、尚未完成

- USB 正式连接体验（adb forward 只是可复用的技术方案）
- 自动设备发现
- 安全配对
- 远程开始/停止与相机参数控制
- 学习模式 / 实验模式 / 项目保存 / Python 代码导出
- Windows 安装包

## 模块

| 路径 | 说明 |
| --- | --- |
| `android/` | Android 传感器 App：Camera2 + ImageReader(JPEG) + NanoHTTPD MJPEG 服务器 |
| `pc-client/` | Windows 客户端：严格 MJPEG 读取、OpenCV 视觉模式、PySide6 视觉工作台（默认）、Legacy Tkinter 客户端 |

## 重要警告

- **尚未达到 v1.0。**
- 当前 HTTP 流**没有身份认证**，手机推流时同一局域网内的任何人都可以拉流。
- 仅应在**可信的本地网络**中使用。
- **USB 还不是正式产品功能。**
- 自动发现与安全配对**尚未实现**。

## 开源许可证

[MIT](LICENSE)
