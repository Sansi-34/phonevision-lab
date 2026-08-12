# PhoneVision Lab — Android 端（V0-A）

用一台旧 Android 手机做摄像头源，通过 WiFi 输出标准 MJPEG-over-HTTP 视频流，
供 Windows 电脑（后续阶段）用 OpenCV 实时读取。

当前版本 **V0-A**：仅 WiFi、仅前台运行（屏幕常亮），不包含 USB、后台服务、PC 端代码。

---

## 一、功能

- 后置摄像头实时预览（TextureView）
- 运行时申请摄像头权限；**权限与预览就绪后只启用“开始推流”按钮，由用户主动点击**
- “开始推流 / 停止推流”按钮；推流期间屏幕常亮（FLAG_KEEP_SCREEN_ON）
- 界面显示：局域网 IP、完整访问地址、实测 FPS、帧数、相机能力信息、错误信息
- HTTP 接口：
  - `GET /ping` → JSON 状态（status / device / width / height / requestedFps / actualFps / frameCount）
  - `GET /stream` → `multipart/x-mixed-replace` MJPEG 帧流
- 默认参数：640×480、目标 10 FPS、JPEG 质量 70（都在 `Config.kt` 可改）
- 停止推流后完整释放相机、服务器与线程；进入后台（onStop）自动停止并释放

## 二、目录结构

```
android/
├─ settings.gradle.kts         # 仓库、插件版本、模块
├─ build.gradle.kts            # 根构建脚本（apply false）
├─ gradlew / gradlew.bat       # Gradle Wrapper（固定 8.7）
├─ gradle/wrapper/             # Wrapper 配置与 jar
└─ app/
   ├─ build.gradle.kts         # 模块构建：Sdk 版本、依赖（NanoHTTPD 等）
   ├─ proguard-rules.pro
   └─ src/main/
      ├─ AndroidManifest.xml
      ├─ res/layout/activity_main.xml
      └─ java/com/phonevisionlab/app/
         ├─ MainActivity.kt        # 主界面：权限/按钮/状态/IP 显示
         ├─ CameraController.kt    # Camera2 封装：预览 + JPEG 双路输出、FPS 统计
         ├─ CameraInfo.kt          # 运行状态聚合（/ping 与 UI 共用）
         ├─ LatestFrameStore.kt    # 线程安全的最新帧缓存（锁 + Condition）
         ├─ MjpegServer.kt         # NanoHTTPD：/ping + /stream
         └─ Config.kt              # 全局配置
```

## 三、如何构建

### 3.1 首次环境准备（一次性）

需要三样东西，缺一不可：

1. **JDK 17**（本项目编译目标；本机若只有 JDK 8 会构建失败）
   - 下载安装：<https://adoptium.net/temurin/releases/?version=17>
   - 安装后设置环境变量 `JAVA_HOME` 指向 JDK 17 目录。
2. **Android SDK**
   - 最简单：安装 Android Studio（自带 SDK），首次启动会自动下载最新 SDK。
   - 或命令行安装 platform-tools 与 `platforms;android-34`、`build-tools`。
   - 设置环境变量 `ANDROID_HOME` 指向 SDK 目录。
3. **（可选）手机**：开启“开发者选项-USB 调试”，用于安装运行。

### 3.2 构建命令

```bash
# 在 android/ 目录下（Windows：使用 gradlew.bat）
./gradlew assembleDebug
# 产物路径：android/app/build/outputs/apk/debug/app-debug.apk
```

> 首次运行会自动下载 Gradle 8.7 发行版与全部依赖，需要联网，可能较慢。
> 如果 `./gradlew` 直接报错找不到，检查 JAVA_HOME 是否已设为 JDK 17。

### 3.3 安装到手机

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## 四、使用与验证

1. 手机和电脑连到**同一局域网**（同一路由器，或手机开热点电脑连它）。
2. 打开 App，允许摄像头权限，点击“开始推流”。
3. 手机界面会显示 IP 与访问地址。
4. 电脑端验证：
   ```bash
   # 状态探测（应返回 JSON）
   curl http://手机IP:8080/ping

   # 视频流（浏览器打开或 curl 看二进制）
   curl http://手机IP:8080/stream
   ```
   浏览器直接打开 `http://手机IP:8080/stream` 应看到实时画面。

## 五、常见问题

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 构建报 "SDK location not found" | 未装 Android SDK / ANDROID_HOME 未设 | 装 SDK，见 3.1 |
| 构建报 "Unsupported class file major version" | 不是 JDK 17 | 设 JAVA_HOME 为 JDK 17 |
| 手机上 IP 显示未知 | 未连 WiFi 或网卡过滤逻辑没命中 | 检查是否连了 WiFi；看 logcat 的 MainActivity |
| curl /ping 不通 | 电脑和手机不在同一网段 / 端口被占 | 确认同一局域网；换端口改 Config.PORT |
| 预览黑屏 | Surface 未就绪就建会话 | 确认走了 onSurfaceTextureAvailable → maybeStart |
| 内存缓慢增长 | Image 未 close | 检查 onImageAvailable 是否每次都 close |

## 六、已知限制（V0-A）

- 只支持 WiFi；USB 通路在 V2 阶段。
- 手机必须保持前台且屏幕常亮；无后台保活（后续阶段加 Foreground Service）。
- 无远程参数控制（改分辨率/FPS 需改 `Config.kt` 重新编译）。
- 单 Activity 锁定竖屏，横屏场景暂不支持。
- 实测 FPS 依赖设备能力：若低于目标值，会如实显示并给出 stall/minFrame 等诊断信息。
