# 参与贡献 PhoneVision Lab

感谢你对本项目的兴趣。这是一个面向学习的、MIT 许可的项目：把旧 Android 手机变成
视觉传感器，在 Windows 上用 OpenCV 学习机器视觉。

> English: [CONTRIBUTING.md](CONTRIBUTING.md)

## 1. 基本规则

- **对初学者友好**：代码以可读、可学为目标，请保持这一点。优先清晰命名与短函数，
  不要炫技式单行。
- **MVP 优先**：改动变大就拆分。小而合入的 PR 胜过大的草稿。
- **保持本地运行**：无遥测、无云端账号、无统计。不要添加与推流/学习无关的网络调用。
- **尊重现有架构**：除非任务明确要求，不要重写已经能工作的模块。

## 2. 开发环境

前置条件：

- **Python 3.12+**
- 仅在改动 Android 时需要的 Android 工具链：
  - JDK 17（如 Adoptium Temurin 17）
  - Android SDK（compileSdk / targetSdk / minSdk 以
    `android/app/build.gradle.kts` 为准）
  - Gradle 由 Wrapper 固定为 8.7（见
    `android/gradle/wrapper/gradle-wrapper.properties`）

配置 PC 端：

```bash
cd pc-client
python -m venv .venv
.venv\Scripts\activate          # Windows；macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Python 测试

运行 PC 端全量测试（offscreen，无需显示器）：

```bash
cd pc-client
export QT_QPA_PLATFORM=offscreen   # Windows PowerShell: $env:QT_QPA_PLATFORM="offscreen"
python -m unittest discover -s tests -t tests
```

迭代时只跑单个模块：

```bash
python -m unittest tests.test_mjpeg_reader -v
```

- Qt 界面测试通过 `QT_QPA_PLATFORM=offscreen` 无界面运行，不需要显示器或手机。
- 完成前检查：`git diff --check` 与 `git status --short`。

## 4. Android 构建

仅在改动 `android/` 时需要。Windows（Git Bash / cmd）：

```bash
cd android
# 确保 JDK 17 与 Android SDK 在 PATH 上 / 设置好 JAVA_HOME、ANDROID_HOME
cmd //c gradlew.bat assembleDebug
```

APK 输出在 `android/app/build/outputs/apk/debug/`。只改 PC 端不必构建 Android。

## 5. 提交规范

- 使用 Conventional Commits 风格，如 `feat(pc): ...`、`fix(android): ...`、
  `docs: ...`、`test(...): ...`、`build(...): ...`。
- 每个提交保持聚焦；标题写清楚**为什么**改。
- 遵循现有提交风格——先读 `git log --oneline`。

## 6. 分支建议

- 从 `main` 开短小主题分支，如 `feat/pc-window-resize`。
- 开 PR，并保持小到一次能审完。

## 7. PR 清单

开 PR 前逐项确认：

- [ ] 测试通过：`python -m unittest discover -s tests -t tests`（offscreen）
- [ ] `git diff --check` 无告警（无行尾空白 / 冲突标记）
- [ ] 已考虑 Android 影响：若改过 `android/`，`gradlew assembleDebug` 能构建；
      否则注明"PC-only"。
- [ ] 仅当 UI 变更时添加截图，且为合成画面 / 不含个人数据。
- [ ] 行为变更时更新文档（README、docs/、发布清单）。
- [ ] 隐私：不提交真实 IP、用户名、路径、序列号或日志转储；不新增密钥文件
      （`*.key`、`.env`）。
- [ ] 许可：若新增依赖，更新第三方声明
      （`pc-client/packaging/THIRD_PARTY_NOTICES.md` 与 `licenses/`），并在 PR
      中注明该依赖的许可。

## 8. 真机验证

推流相关代码最好用真实手机验证：

1. 手机打开 App，点击"开始推流"。
2. PC 端运行 `python main.py --host <手机IP> --port 8080`。
3. 确认五种模式（原始 / 灰度 / Canny / HSV / 轮廓）能正常显示。

无法真机测试时请在 PR 里说明；基于 mock 的测试已覆盖解析与界面逻辑。

## 9. 不要提交的内容

- 本地日志（`*.log`、`*logcat*.txt`）、真机截图、captures 与转储。
- 机器相关路径（`C:\Users\...`、`D:\...`）与用户名。
- 密钥：`.env`、`*.keystore`、`*.jks`、API Key、Token。
- 大体积二进制/压缩包（`.zip`、`.apk`、`.mjpeg`）。

## 10. 初学者任务

初次参与开源？可以找标了 `good first issue` 的 issue。建议起步方向：文档修正、
测试补充、小 UX 打磨。编码前先在 issue 里提问——维护者与伙伴都乐于指导。

## 11. 双语文档

面向用户的文档与本文件均以简体中文和英文双语维护。改其一，必须同步另一个
（关键章节保持一致——见 `tests/test_repository_health.py`）。
