# PhoneVision Lab Web · 网页版学习与实践平台

> 适用范围：`web/` 目录（新增的网页客户端）。
> 本文件说明它做什么、怎么启动、与现有项目怎么对接、哪些能力已验证、哪些没有。

---

## 1. 这是什么

把旧 Android 手机变成边缘 AI 视觉设备，并用**浏览器**完成整条学习闭环：

```
认识视觉 AI → 连接旧手机 → 获取摄像头画面 → 体验图像处理 →
采集数据 → 训练分类模型 → 部署到手机 → 尝试硬件联动 → 查看性能结果
```

网页版是 PhoneVision Lab 的**新客户端**，与 PySide6 桌面客户端（`pc-client/qt_client`）、
Android App（`android/`）并列。它不替代、不修改这两者，只复用它们的 Python 逻辑模块。

两种使用方式：

| 模式 | 需要什么 | 能做什么 |
| --- | --- | --- |
| 学习模式 | 一台能上网的电脑 | 读 8 课课程、看示意说明、理解全流程；进度存在本机浏览器 |
| 实践模式 | 旧手机（或 ESP32） | 连接设备、看真实画面、采集数据、训练模型、硬件手动测试、性能采样 |

---

## 2. 启动

### 2.1 安装依赖

网页服务复用 `pc-client` 的依赖（不新增任何第三方包）：

```powershell
pip install -r pc-client\requirements.txt
```

训练需要额外依赖（TensorFlow，约 500 MB）。**不装也能用学习模式和大部分实践功能**，
只是「模型训练」页会明确提示缺少什么、怎么装：

```powershell
pip install -r pc-client\requirements.txt -r pc-client\requirements-train.txt
```

### 2.2 启动服务

```powershell
# 在仓库根目录
python -m web.server
# 默认 http://127.0.0.1:8088 （仅本机可访问）
```

浏览器打开 <http://127.0.0.1:8088>。

常用参数：

```powershell
python -m web.server --port 9000        # 换端口（只监听 127.0.0.1）
```

> **当前版本只支持本机访问。** 服务会校验 `Host` 与 `Origin`，只接受
> `127.0.0.1:<port>`、`localhost:<port>`、`[::1]:<port>`；外网站点、`null` Origin
> 与其他主机名一律 403。即便显式 `--host 0.0.0.0` 监听，用局域网 IP 打开也会被
> Host 白名单拒绝——局域网共享需要显式的来源白名单或一次性 token 设计，尚未实现。

### 2.4 便携版（Windows，无需安装 Python）

打包产物：`artifacts\web\PhoneVisionLabWeb-<version>-win-x64.zip`

```powershell
# 解压后双击
PhoneVisionLabWeb.exe
```

行为：自动启动本地服务（`http://127.0.0.1:8088`）→ 自动打开系统默认浏览器 →
显示「服务正在运行」窗口；关闭该窗口即停止服务。日志写在
`%LOCALAPPDATA%\PhoneVisionLab\logs\phonevision-web.log`。

**便携版刻意不做的事**：不提供 `--host 0.0.0.0` 选项。学生双击运行时不应无意中
把接口暴露到公共 Wi-Fi 上。

**便携版未内置 TensorFlow**（约 500 MB，且多数用户只做学习与预览）。需要训练时：
在电脑上安装 `pc-client\requirements.txt` + `pc-client\requirements-train.txt`，
然后用源码模式 `python -m web.server` 启动即可，「模型训练」页会识别到环境可用。

重新打包：

```powershell
.\web\scripts\build_windows.ps1              # 完整构建（建 venv + 测试 + 打包 + ZIP + SHA-256）
.\web\scripts\build_windows.ps1 -SkipTests   # 跳过测试
```

构建依赖见 `web\packaging\requirements-web-build.txt`（**不含 PySide6 与 TensorFlow**）。
spec 见 `web\packaging\PhoneVisionLabWeb.spec`。

### 2.5 与桌面端的体积对比（实测）

| 客户端 | 目录体积 | 文件数 |
| --- | --- | --- |
| 桌面端 `PhoneVisionLab.exe`（含 PySide6） | 268 MB | 305 |
| 网页端 `PhoneVisionLabWeb.exe`（无 Qt） | 175 MB | 150 |
| 网页端 ZIP | 70 MB | — |

网页端小 34.7%，因为它只需要 `opencv + numpy + requests`，不打包 Qt。

### 2.6 网络边界（务必理解）

- 服务**默认只监听 127.0.0.1**：同一台电脑上的浏览器能访问，其他设备不能。
- 服务在入口处校验 `Host` / `Origin` / `Sec-Fetch-Site`：只放行本机回环来源，
  跨站请求 403 且不返回任何 CORS 放行头；响应带 `X-Frame-Options: DENY` 与
  `Content-Security-Policy: frame-ancestors 'none'`，外部页面无法内嵌本机界面。
- 因此**当前版本没有"同一 Wi-Fi 下其他设备访问"这种用法**：即使监听 `0.0.0.0`，
  用局域网 IP 打开也会被 Host 白名单拒绝。
- 仍然没有身份认证：能开这台电脑上浏览器的人就能操作设备连接与数据集；
  手机推流本身也没有身份认证（见 `docs/protocol.md`）。

---

## 3. 为什么需要一个本地服务

| 需求 | 为什么不能只靠前端 |
| --- | --- |
| 看手机画面 | 手机推的是 `multipart/x-mixed-replace` MJPEG 流，`<img>` 只认单张 JPEG，且手机没有 CORS 头。服务负责解析流，提供 `/api/vision/frame` 单帧接口 |
| 训练模型 | 浏览器跑不了现有 Python/TensorFlow 训练代码。训练在服务后台线程执行，页面只轮询进度，不阻塞 |
| 数据集文件 | 图片在本地磁盘，通过 `/api/datasets/samples/image` 提供缩略图 |
| 硬件控制 | ESP32 在局域网内，浏览器直连有跨域与网络边界问题；服务代理命令并记录四态回执 |

---

## 4. 目录结构

```
web/
├── server/
│   ├── __main__.py      # python -m web.server 入口
│   ├── app.py           # HTTP 路由与请求分发（标准库 http.server）
│   ├── device.py        # 设备会话：连接状态机 + 视觉模式 + 取帧
│   ├── dataset.py       # 数据集：创建/类别/采集/体检/划分/样本
│   ├── training.py      # 训练任务：后台运行、进度、取消、导出
│   ├── hardware.py      # 硬件联动：真实控制器 + 模拟设备、命令四态
│   ├── performance.py   # 性能采样：只记录真实数据
│   └── util.py          # JSON 响应、错误码、路径校验
├── static/              # 前端（纯 HTML/CSS/JS，无构建步骤）
│   ├── index.html
│   ├── styles.css       # 设计系统（令牌 + 组件）
│   ├── pages.css        # 页面级补充样式
│   ├── app.js           # 路由 + API 客户端 + 全局状态
│   ├── courses.js       # 8 课课程内容
│   └── pages/*.js       # 各页面模块
└── tests/               # 测试（后端 + 前端契约）
```

---

## 5. 与现有项目的对接方式

**核心原则：网页端不复制任何业务逻辑，全部调用 `pc-client` 里已验证的模块。**

| 能力 | 复用的 pc-client 模块 | 网页端职责 |
| --- | --- | --- |
| URL 构造、`/ping` 预检 | `connection.py` | 接收 host/port，转交 |
| MJPEG 流解析 | `mjpeg_reader.py` | 只取最新帧 |
| 连接状态机、帧率统计、丢帧估算 | `app_model.py` | 序列化成 JSON |
| 五种视觉模式 | `vision_modes.py` | 传 mode/params，取处理后的帧 |
| 数据集存储、batch 划分 | `pvl_dataset.py` | 提供 HTTP 接口 |
| 数据体检、按批次划分 | `pvl_split.py` | 透传 problems/warnings |
| 训练、取消 | `pvl_train.py` | 后台线程驱动 + 轮询 |
| TFLite 导出、一致性校验 | `pvl_export.py` | 透传结果，不包装成败 |
| 硬件协议、规则引擎、模拟设备 | `pvl_hardware.py` | 代理命令、记录事件 |
| 性能统计、导出 | `pvl_perf.py` | 采样窗口 + 落盘 |

数据目录沿用 `pvl_paths.py` 的约定：`%LOCALAPPDATA%\PhoneVisionLab\`
（可被 `PVL_DATA_DIR` 覆盖）。**网页端与桌面客户端看到的是同一批数据集、训练产物与模型包。**

---

## 6. 功能实现清单

### 6.1 已实现并经过自动化测试

| 功能 | 状态 | 测试覆盖 |
| --- | --- | --- |
| 首页（介绍、流程、学习路径、设备状态、能力清单） | 现有 | 前端契约测试 |
| 学习中心 8 课 + 课程详情 | 现有 | 课程字段契约测试 |
| 学习进度（localStorage） | 现有 | 前端契约测试 |
| 设备连接（连接/断开/重连、五态状态机） | 现有 | 单元 + HTTP 集成测试 |
| 实时画面（服务解析 MJPEG，单帧接口） | 现有 | 单元 + HTTP 集成测试 |
| 五种视觉模式 + 参数（范围校验、钳制） | 现有 | 单元 + HTTP 集成测试 |
| 截图（原始画面，高质量 JPEG） | 现有 | 单元测试 |
| 采集/接收/显示帧率、丢帧、带宽、无效帧 | 现有 | 单元 + HTTP 集成测试 |
| 数据集创建/打开/类别管理 | 现有 | 单元 + HTTP 集成测试 |
| 采集（单张/连续，帧号去重） | 现有 | 单元测试（假设备帧） |
| 样本浏览、缩略图、删除（路径校验） | 现有 | 单元 + HTTP 集成测试 |
| 数据体检、按批次划分 | 现有 | 单元测试 |
| 训练环境检测（TensorFlow/GPU） | 现有 | 单元 + HTTP 集成测试 |
| 训练启动/进度/取消/导出 | 现有（门禁测试） | 单元 + HTTP 集成测试 |
| 硬件连接（真实 + 模拟）、命令四态、事件记录 | 现有 | 单元 + HTTP 集成测试 |
| 性能采样（预热/时长/导出 CSV/JSON/摘要） | 现有 | 单元 + HTTP 集成测试 |

### 6.2 实现但**未**在真实设备上验证

以下功能代码路径完整、有测试覆盖，但**没有在真实手机或 ESP32 上端到端验收**：

- 手机推流连接与实时画面（需要旧手机 + App）
- 数据集采集（需要真实画面）
- 模型训练全流程（需要真实数据集；合成数据冒烟见 `pc-client/scripts/smoke_train.py`）
- 模型导出与模型包生成（依赖训练产物）
- 手机导入模型包并本机推理（需要手动操作，见部署页指南）
- ESP32 控制器连接与 LED 命令（需要真实固件）

### 6.3 明确**不**实现 / 未接入

| 项目 | 界面表现 |
| --- | --- |
| 手机推理帧率、各阶段耗时 | 性能页显示「— 未采集」 |
| 硬件命令耗时、执行计数 | 性能页显示「— 未采集」 |
| 手机功耗 | 性能页固定「不支持」 |
| 网页端自动控制硬件 | 不提供开关，只说明原因与手机端步骤 |
| 网页端自动推送模型到手机 | 不提供按钮，只提供手动导入指南 |
| 舵机、电机等动作 | 服务端直接拒绝，不出现在可用列表 |
| 目标检测、图像分割 | 未实现（当前只做图像分类） |
| 账号、云同步、班级管理 | 第一版不做 |

---

## 7. 测试

```powershell
# 全部网页测试（后端单元 + HTTP 集成 + 前端契约）
python -m unittest discover -s web\tests -t web\tests
```

当前结果：**134 项全部通过。**

| 测试文件 | 覆盖 |
| --- | --- |
| `test_util.py` | JSON 响应、错误结构、路径穿越防护 |
| `test_device.py` | 连接状态机、视觉模式、帧管线（假 reader） |
| `test_dataset.py` | 数据集全流程（真实 DatasetStore + 临时目录） |
| `test_training.py` | 训练门禁、环境检测、导出前置条件 |
| `test_hardware.py` | 命令四态、模拟设备、动作白名单 |
| `test_performance.py` | 未采集语义、采样窗口、导出 |
| `test_http_api.py` | 真实 HTTP 服务器 + urllib 请求（约 30 个接口） |
| `test_frontend_contract.py` | Node 桩驱动 14 个路由渲染、课程契约、零构建约束 |

测试不连接手机、不启动真实训练、不访问外网。设备相关测试用假 reader / 假设备帧。

### 便携版验证（已实际运行）

在 Windows 上执行了以下验证，均通过：

| 验证项 | 结果 |
| --- | --- |
| `PhoneVisionLabWeb.exe` 启动 | 进程正常，「服务正在运行」窗口出现 |
| 自动打开浏览器 | `webbrowser.open` 调用成功 |
| 服务就绪检测 | `wait_ready()` 轮询 `/api/health` 成功 |
| 首页与静态资源 | `index.html` / `styles.css` / `app.js` / `courses.js` / `pages/*.js` 全部 200 |
| 业务接口 | `device/status`、`vision/state`、`datasets`、`train/status`、`hardware/status`、`perf/status` 等 8 项返回正常 JSON |
| 无数据集时的体检 | 返回 400 + `no_dataset` 错误码（符合契约，不是崩溃） |
| 关闭窗口停止服务 | 进程退出，日志记录 `service started` / `service stopped` |
| 日志落盘 | `%LOCALAPPDATA%\PhoneVisionLab\logs\phonevision-web.log` |

**仍未验证**：便携版内的真实手机连接、真实训练（便携版未内置 TensorFlow，
训练需用源码模式）、真实 ESP32 命令。

### 未覆盖的部分（需要人工在浏览器验证）

- 真实浏览器渲染效果与响应式布局
- 真实手机连接后的画面与帧率
- 真实训练/导出的完整流程
- 真实 ESP32 的 LED 命令

---

## 8. 已知限制

1. **完整流程未在真实手机和 ESP32 上全面验收。** 所有设备相关功能都停在"代码路径完整 + 自动化测试通过"。
2. **训练环境依赖本机安装。** 未装 TensorFlow 时无法训练，页面会给出安装命令，不会假装能训。
3. **一次只连接一部手机、一个控制器。** 多设备不在第一版范围。
4. **网页服务默认只监听 127.0.0.1。** 局域网访问需显式 `--host 0.0.0.0`，且要知道这带来的安全含义。
5. **学习进度只存在本机浏览器。** 清除浏览器数据会丢失；换设备不同步。
6. **前端是纯静态文件，没有构建与打包步骤。** 这是有意的（学生机解压即用），但也意味着没有压缩、tree-shaking、类型检查。

---

## 9. 后续开发建议

按价值/成本排序：

1. **真机验收清单**：找一台旧手机 + ESP32，按 `docs/user-guide.zh-CN.md` 走一遍，
   把结果回写到本文档 §6.2。这是把"代码完成"变成"产品可用"的唯一途径。
2. **手机端上报推理指标**：Android 端已有 `InferenceEngine` 实测数据，
   通过 `/ping` 或独立接口上报后，性能页的手机推理区块就能从「未采集」变成真实数据。
3. **USB 传输（adb forward）**：`docs/protocol.md` 已提及设计意图。
   落地后手机连接不再依赖 Wi-Fi 同网段，教室场景会好很多。
4. **模型包推送**：若做了 USB 通道，可以加"推送到手机"按钮（仍需用户在手机上点导入）。
5. **英文界面**：课程内容与前端文案已按 key/字段组织，加一层 i18n 字典即可，
   不需要改页面结构。
6. **教师视图**：需要后端与账号体系，与"完全本地"定位冲突，建议做成可选的教学服务器组件，
   不要塞进第一版的本地服务里。
