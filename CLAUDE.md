# PhoneVision Lab 开发指令

## 自主工作

- 收到开发任务后直接读取项目、检查 Git 状态和相关代码，然后修改、构建、测试和修复；不要让用户代为运行你能够运行的命令。
- 能自行读取的文件、日志和命令输出必须自己读取。不要要求用户复制终端输出。
- 修改后主动运行相关测试；失败时分析错误、修复并重试。不要因为普通报错或一次测试失败就停止。
- 对实现细节和可逆的小决定自行做合理选择。只有产品方向、重大架构、不可逆数据操作、远端发布或确实缺少关键信息时才询问用户。
- 保留现有架构和用户已有改动，不要无故重写、回滚或删除不属于当前任务的内容。

## 项目命令

- Android 构建前设置 `JAVA_HOME`（JDK 17，如 Temurin/Adoptium 17）与
  `ANDROID_HOME`（Android SDK）。具体路径由 `.local/environment.ps1` 提供
  （该文件只在本机存在，不进入版本控制）；不要在本文件写死本机绝对路径。
- Android Debug 构建：进入 `android/` 后运行 `cmd //c gradlew.bat assembleDebug`。
- Python 语法检查：进入 `pc-client/` 后运行 `python -m py_compile` 并列出本次涉及的 Python 文件。
- Python 测试：进入 `pc-client/` 后运行 `python -m unittest` 加相关测试模块；Qt 无界面测试设置 `QT_QPA_PLATFORM=offscreen`。
- 优先运行与改动最相关的测试，再按风险扩大验证范围。完成前检查 `git diff --check`、`git status --short` 和相关 diff。

## 安全边界

- 不读取、打印、提交或上传 Token、API Key、密码、`.env`、SSH/AWS/Claude 凭据。
- 未经用户明确要求，不执行 `git push`、强制推送、硬重置、`git clean`、生产部署或发布。
- 不修改 Windows 核心目录、注册表、安全软件、磁盘和启动配置，不大范围删除用户文件。
- 可以在项目范围内自行创建、修改和删除任务所需文件；删除既有文件前确认它确实属于当前任务且可由 Git 恢复。

## 完成标准

- 功能实现、相关测试和构建均完成后再结束。若某项验证确实无法运行，准确说明原因并完成其余可验证内容。
- 最终只需简洁报告改动、验证结果和仍存在的真实限制。
