# PhoneVision Lab Web — 网页版学习与实践平台

把旧 Android 手机变成视觉传感器，用浏览器完成「认识视觉 AI → 连接旧手机 →
获取摄像头画面 → 体验图像处理 → 采集数据 → 训练分类模型 → 部署到手机 →
尝试硬件联动 → 查看性能结果」的完整学习闭环。

本目录是新增的**网页客户端**，不替代也不修改 `pc-client`（PySide6 桌面客户端）
与 `android`（手机端）。所有训练、数据集、硬件、性能逻辑都直接调用
`pc-client` 里已验证的 Python 模块，避免出现两套行为不一致的实现。

## 为什么需要本地服务

| 需求 | 为什么不能只靠前端 |
| --- | --- |
| 看手机画面 | 手机推送的是 `multipart/x-mixed-replace` MJPEG 流，`<img>` 标签只认单张 JPEG，且手机没有 CORS 头。因此由本服务解析流，提供 `/api/vision/frame` 单帧接口。 |
| 训练模型 | 浏览器无法运行现有 Python/TensorFlow 训练代码。训练在本服务后台线程执行，页面只轮询进度。 |
| 数据集文件 | 图片在本地磁盘，通过 `/api/datasets/samples/image` 提供缩略图。 |
| 硬件控制 | ESP32 控制器在局域网内，浏览器直连有跨域与网络边界问题，由本服务代理命令并记录四态回执。 |

## 目录结构

```
web/
├── launcher.py         # 便携版入口：起服务 + 开浏览器 + 状态窗口
├── server/
│   ├── app.py         # HTTP 路由与请求分发（标准库 http.server）
│   ├── device.py      # 设备会话：连接状态机 + 视觉模式 + 取帧
│   ├── dataset.py     # 数据集：创建/类别/采集/体检/划分/样本
│   ├── training.py    # 训练任务：后台运行、进度、取消、导出
│   ├── hardware.py    # 硬件联动：真实控制器 + 模拟设备、命令四态
│   ├── performance.py # 性能采样：只记录真实数据
│   └── util.py        # JSON 响应、错误码、路径校验
├── packaging/
│   ├── PhoneVisionLabWeb.spec      # PyInstaller onedir spec
│   ├── requirements-web-build.txt  # 构建依赖（不含 PySide6 / TensorFlow）
│   └── assets/                     # 应用图标
├── scripts/
│   └── build_windows.ps1           # 便携包构建：venv + 测试 + 打包 + ZIP + SHA-256
├── static/            # 前端（原生 HTML/CSS/JS，无构建步骤）
│   ├── index.html
│   ├── styles.css     # 设计系统（令牌 + 组件）
│   ├── pages.css      # 页面级补充样式
│   ├── app.js         # 路由 + API 客户端 + 全局状态
│   ├── courses.js     # 学习中心课程内容（简体中文）
│   └── pages/*.js
└── tests/             # 后端单元 + HTTP 集成 + 前端契约测试
```

## 启动

```powershell
# 在仓库根目录（依赖与 pc-client 相同：requirements.txt）
python -m web.server --host 127.0.0.1 --port 8088
```

然后浏览器打开 <http://127.0.0.1:8088>。

局域网访问（同一 Wi-Fi 下的其他电脑/手机浏览器）**当前版本不支持**：服务会校验
`Host` 与 `Origin`，只接受 `127.0.0.1` / `localhost` / `[::1]` 加实际端口，跨站请求
一律 403。即使监听 `0.0.0.0`，用局域网 IP 打开也会被拒绝——要共享需先实现来源白名单
或一次性 token。

**安全说明**：手机推流没有身份认证，同一局域网内任何人都能拉流；网页服务默认只监听
127.0.0.1，并拒绝跨站请求（响应带 `X-Frame-Options: DENY`、CSP `frame-ancestors
'none'`、`nosniff`）。没有账号体系，按"单用户本机工具"使用。

## 训练环境

训练需要额外依赖（TensorFlow，约 500 MB），与基础依赖分离：

```powershell
pip install -r requirements.txt -r requirements-train.txt
```

未安装时，「模型训练」页会明确显示缺少什么、如何安装，而不是把按钮灰掉。

## 测试

```powershell
cd pc-client
python -m unittest discover -s ../web/tests -t ../web/tests
```

详细说明见 `docs/web-platform.zh-CN.md`。

## Windows 便携版（无需安装 Python）

```powershell
.\web\scripts\build_windows.ps1
```

产物：`artifacts\web\PhoneVisionLabWeb-<version>-win-x64.zip`，解压后双击
`PhoneVisionLabWeb.exe` 即自动启动本地服务并打开浏览器；关闭「服务正在运行」
窗口即停止服务。

**便携版刻意不做的事**：

- 不提供 `--host 0.0.0.0`——学生双击运行时不应无意把无认证接口暴露到公共 Wi-Fi；
- 不内置 TensorFlow（约 500 MB）——需要训练的用户按「模型训练」页提示安装后，
  用源码模式 `python -m web.server` 启动即可。

实测体积：目录 175 MB / ZIP 70 MB，比桌面端（268 MB）小 34.7%，
因为网页后端只需要 `opencv + numpy + requests`，不打包 Qt。
