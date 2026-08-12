# PhoneVision Lab — Android Release 候选（P0-5B）

本文件面向**需要产出 Android 发布产物的开发者**，说明如何构建可复现的 Release 候选、
如何启用正式签名、以及国内网络的可选镜像配置。日常开发调试看 `android/README.md`。

---

## 1. 版本

版本号唯一事实来源是 `pc-client/qt_client/version.py`：

- `versionName = 0.1.0-alpha.1`
- `versionCode = 1`（保持）

Android 侧 `android/app/build.gradle.kts` 必须与 PC 一致；改版本时**两个位置一起改**。

## 2. 仓库源

默认只使用官方仓库，保证 GitHub 开源后的构建可复现与可校验：

- 插件仓库（`pluginManagement`）：`google()`、`mavenCentral()`、`gradlePluginPortal()`
- 依赖仓库（`dependencyResolutionManagement`）：`google()`、`mavenCentral()`

> 国内网络如果下载慢，可**自行在 `settings.gradle.kts` 增加镜像**（例如腾讯云
> `https://mirrors.cloud.tencent.com/nexus/repository/maven-public/`）。
> 镜像仅作为你本机加速选项，**默认源与 CI 一律走官方仓库**，不要提交到工程里。

## 3. Gradle Wrapper 校验

`gradle/wrapper/gradle-wrapper.properties` 固定 Gradle 8.7，并带官方 `distributionSha256Sum`：

```
distributionSha256Sum=544c35d6bd849ae8a5ed0bcea39ba677dc40f49df7d1835561582da2009b961d
```

校验值来源：<https://services.gradle.org/distributions/gradle-8.7-bin.zip.sha256>。
升级 Gradle 时从该官方源重新获取对应版本校验值。

## 4. 依赖校验（verification-metadata.xml）

`android/gradle/verification-metadata.xml` 由 Gradle 依赖验证机制生成，逐条记录
所有依赖/插件的 SHA-256，**无通配信任**。CI 与本地构建默认即启用该校验
（`--dependency-verification` 为 Gradle 默认行为）。

更新依赖后需要重新生成并提交该文件：

```powershell
cd android
./gradlew --write-verification-metadata sha256 help
git diff --stat gradle/verification-metadata.xml   # 确认新增/变更条目合理
```

> 注意：`--write-verification-metadata` 会按解析到的内容写文件；若网络抖动导致
> 部分依赖未解析，可能漏条目，生成后请用 `git diff` 复查。

## 5. 图标

当前为**临时品牌图标**（深色底 + 靛蓝 `#5B7CFA` 手机与镜头线稿，无文字），
等正式品牌设计确认后再替换。实现：

- API 26+：`mipmap-anydpi-v26/ic_launcher(.round).xml` 自适应图标，
  图层为 `drawable/ic_launcher_foreground.png`（线稿）与
  `drawable/ic_launcher_background.png`（纯色底）。
- API 21-25 回退：`mipmap-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}/ic_launcher(.round).png`。

`AndroidManifest.xml` 的 `android:icon` / `android:roundIcon` 分别指向
`@mipmap/ic_launcher` / `@mipmap/ic_launcher_round`。

## 6. Release 候选构建

脚本：`android/scripts/build_release_candidate.ps1`

```powershell
cd android
powershell -ExecutionPolicy Bypass -File scripts\build_release_candidate.ps1
```

产物输出到 git 忽略的 `artifacts/android/`：

```
PhoneVisionLab-0.1.0-alpha.1-debug.apk            # 测试用，可安装调试
PhoneVisionLab-0.1.0-alpha.1-release-unsigned.apk # 未签名，不可发布
PhoneVisionLab-0.1.0-alpha.1-release-unsigned.aab # 未签名，不可发布
SHA256SUMS.txt
android-build-info.json                            # 含 aapt2/bundletool 核对结果
```

脚本会用 `aapt2 dump` + `bundletool validate` 核对
`applicationId` / `versionCode` / `versionName` / `minSdk` / `targetSdk` /
`debuggable` / 图标 / 权限 / ABI / 签名状态，并写入 `android-build-info.json`；
任何一项与预期不符会在控制台醒目标出。

前置条件：

- `JAVA_HOME` 指向 JDK 17
- Android SDK（`local.properties` 的 `sdk.dir` 或 `ANDROID_HOME`）
- 依赖已下载（首次可先跑一次 `gradlew assembleDebug`）

## 7. 正式签名

本项目**不生成、不提交任何 keystore**，也不拿 debug key 冒充正式签名。
正式签名通过四个环境变量启用，**四项必须齐全**：

```powershell
$env:PVL_ANDROID_KEYSTORE       = "C:\path\to\your-release.keystore"
$env:PVL_ANDROID_KEY_ALIAS      = "your-alias"
$env:PVL_ANDROID_STORE_PASSWORD = "your-store-password"
$env:PVL_ANDROID_KEY_PASSWORD   = "your-key-password"
```

- 四个都设置了 → release APK/AAB 使用正式签名。
- 缺任何一个 → 构建 unsigned 产物并在控制台明确提示，**不静默降级**。

路径与密码只从环境变量读取，不进入源码、Gradle 文件或日志。keystore 文件
（`*.keystore` / `*.jks`）已被 `.gitignore` 忽略，请把密钥保管在仓库外。

生成 keystore（一次性，按你自己的规范）：

```powershell
keytool -genkeypair -v -keystore release.keystore -alias phonevisionlab `
  -keyalg RSA -keysize 2048 -validity 10000
```

## 8. 发布前的检查清单

- [ ] `versionName` 与 `versionCode` 与 PC 一致
- [ ] `gradle/wrapper/gradle-wrapper.properties` 带官方 `distributionSha256Sum`
- [ ] `verification-metadata.xml` 覆盖最新依赖且无通配信任
- [ ] 图标资源齐全（adaptive + 各密度 mipmap）
- [ ] 用**正式签名**重新构建 release APK/AAB（非 unsigned）
- [ ] `aapt2` 核对：package / version / minSdk / targetSdk / debuggable / 图标 / 权限
- [ ] `SHA256SUMS.txt` 与发布页一致
