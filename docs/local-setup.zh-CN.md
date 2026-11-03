# 本机迁移与开发环境

项目根目录：`D:\lab\PhoneVision Lab`。

## 启动与开发

- 双击根目录 `start.cmd`：启动当前源码工作台，输入手机 App 显示的 IP。
- 双击 `start-portable.cmd`：打开现有 Windows 便携版。
- 双击 `develop.cmd`：打开已配置的开发终端。
- 双击 `check.cmd`：检查 Python 依赖、JDK、ADB 和 Git diff。
- 双击 `test.cmd`：运行现有 Python 测试（Qt 使用 offscreen）。
- 双击 `build-android.cmd`：构建 Debug APK 并运行 Android 单元测试。
- 双击 `build-windows.cmd`：使用现有锁定环境运行测试并重新打包 Windows 程序。

也可在 PowerShell 中运行：

```powershell
Set-Location -LiteralPath 'D:\lab\PhoneVision Lab'
.\scripts\local_tasks.ps1 -Task Run
.\scripts\local_tasks.ps1 -Task Run --host 192.168.x.x
.\scripts\local_tasks.ps1 -Task Check
.\scripts\local_tasks.ps1 -Task Test
.\scripts\local_tasks.ps1 -Task BuildAndroid
```

IP 示例需要替换；先在同一局域网内启动手机 App 并点击开始推流。
没有手机连接时，可以打开连接界面，但不能验证真实视频链路。

## 工具链

- Python 3.12：现有 `pc-client\.venv-build`，迁移时重新生成激活脚本和命令入口。
- JDK 17：`C:\Users\22917\Adoptium\jdk-17.0.20+8`。
- Android SDK：`C:\Users\22917\Android\Sdk`。
- 本机配置：`.local\environment.ps1`（Git 忽略）。
- Android SDK 路径：`android\local.properties`（Git 忽略）。

启动脚本只为当前进程设置 PATH、JAVA_HOME、ANDROID_HOME 等环境变量，
不修改系统 Java 默认版本、注册表或全局执行策略。
共享 Python、JDK、SDK 保留在原安装位置。
启用代理模式时，Android 构建会将当前进程已有的无认证 HTTP(S)_PROXY 转为该次
Gradle 的网络参数，解决 Java 不自动使用代理环境变量的问题；不写入系统或全局配置。
本机可选仓库配置在 `.local\repositories.init.gradle`：优先使用阿里云 Maven 镜像，
保留官方回退源，不改变仓库或 CI 的默认源，也不关闭依赖校验。
本机已验证镜像可直连，因此 `.local\environment.ps1` 默认设置
`PVL_GRADLE_USE_PROXY=0`；需要使用代理时，在开发终端设为 `1` 再构建。
直连模式会在该次构建 JVM 内清除继承的 HTTP/HTTPS/SOCKS 代理属性，
避免全局 Gradle 旧代理干扰；不读取或修改全局 Gradle 配置文件。

重新安装本机开发依赖时，在开发终端执行：

```powershell
python -m pip install -r pc-client\requirements-dev.txt
```

此文件复用仓库原有 Windows 锁定依赖，并补充工作流静态测试需要的 PyYAML。

## 资料与产物

- `materials\roadshow\`：本聊天制作的路演海报和海报生成提示词。
- `materials\previous-roadshow\`：找到的既往路演资料目录，保留原有子目录。
- `docs\development-prompt.zh-CN.md`：整合 AI 与硬件联动目标的完整开发提示词，使用新路径。
- `pc-client\dist\PhoneVisionLab\PhoneVisionLab.exe`：现有 Windows 程序。
- `artifacts\windows\`：Windows 便携压缩包。
- `artifacts\android\`：既有 Android 候选安装包。
- `android\app\build\outputs\apk\debug\app-debug.apk`：本地 Debug 构建输出。
- `.local\migration-manifest.json`：迁移核对记录。
- `.local\validation\`：迁移后的本机检查日志和报告。

迁移后已验证：环境依赖检查、源码启动器、现有 Windows 程序启动、
Python 全量测试（259 项，3 项跳过）、额外 20 项 Android 发布配置检查，以及 Debug APK 构建。
当前工程的 Android 单元测试任务为 NO-SOURCE，未进行手机或外部硬件实机联调。

原项目目录 `D:\PhoneVision Lab` 已整体移动到本目录；Git 历史和原有未提交修改保留。
最初桌面参考图 `7a875726cb506b54bcc1025aed618318.jpg` 在本次检查时已不在原路径，
因此没有将它记为已迁移；项目原有 `docs\images` 和 captures 截图目录均随源码保留。

开发提示词描述的是下一阶段目标，不代表当前已有模型训练、手机 AI 推理或硬件控制功能。
