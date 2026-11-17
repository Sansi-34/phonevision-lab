// PhoneVision Lab — app 模块构建配置
//
// 职责：声明 Android 应用本身的编译参数、Sdk 版本、依赖、Kotlin/JVM 目标。
// 为什么这样设计：
//   - minSdk 21 覆盖绝大多数旧手机（Android 5.0 起）。
//   - compileSdk 用本机已安装的 SDK 版本；本机当前未装 SDK，构建前需先按 README 安装
//     Android Studio（自带 SDK 35+）。如果你用更高版本的 SDK 安装，本文件里 "34" 可以改大，
//     AGP 8.x 支持到它对应的最新版本。
//   - jvmToolchain(17) 固定编译用 JDK 17，避免不同机器 Java 版本不一致导致编译失败。
// 初学者调试观察点：
//   - "SDK location not found" -> 说明本机没装 Android SDK，见 README 的安装步骤。
//   - "Unsupported class file major version" -> Java/JDK 版本不对，检查是否已设置到 17。
//   - "Could not find org.nanohttpd" -> 依赖下载失败，检查网络或按 RELEASE.md 配置镜像仓库。

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.phonevisionlab.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.phonevisionlab.app"
        minSdk = 21
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0-alpha.1"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    // P0-5B：正式签名接口 —— 密钥一律走环境变量，绝不写进源码 / 日志。
    // 四个环境变量同时存在才启用 release 签名；缺任何一个都构建 unsigned 并明确提示。
    //   PVL_ANDROID_KEYSTORE          keystore 文件路径
    //   PVL_ANDROID_KEY_ALIAS         密钥别名
    //   PVL_ANDROID_STORE_PASSWORD    store 密码
    //   PVL_ANDROID_KEY_PASSWORD      key 密码
    val signEnabled = listOf(
        "PVL_ANDROID_KEYSTORE",
        "PVL_ANDROID_KEY_ALIAS",
        "PVL_ANDROID_STORE_PASSWORD",
        "PVL_ANDROID_KEY_PASSWORD"
    ).all { !System.getenv(it).isNullOrBlank() }

    if (signEnabled) {
        signingConfigs {
            create("release") {
                storeFile = file(System.getenv("PVL_ANDROID_KEYSTORE"))
                storePassword = System.getenv("PVL_ANDROID_STORE_PASSWORD")
                keyAlias = System.getenv("PVL_ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("PVL_ANDROID_KEY_PASSWORD")
            }
        }
        logger.lifecycle("PhoneVisionLab: release signing ENABLED (via PVL_ANDROID_* env vars).")
    } else {
        logger.lifecycle(
            "PhoneVisionLab: release signing DISABLED — build will be UNSIGNED. " +
                "Set all of PVL_ANDROID_KEYSTORE / PVL_ANDROID_KEY_ALIAS / " +
                "PVL_ANDROID_STORE_PASSWORD / PVL_ANDROID_KEY_PASSWORD to enable."
        )
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            if (signEnabled) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")

    // 轻量嵌入式 HTTP 服务器：负责 /ping 与 /stream 两个接口。
    implementation("org.nanohttpd:nanohttpd:2.3.1")

    // TensorFlow Lite：本机 AI 推理（V0-B）。
    // 版本 2.16.1 的 AAR minSdk=19，兼容本项目 minSdk 21（旧手机目标）。
    // 默认只用 CPU（见 Config.USE_NNAPI=false），不依赖 GPU/NPU 加速。
    implementation("org.tensorflow:tensorflow-lite:2.17.0")

    testImplementation("junit:junit:4.13.2")
    // androidTest：真机仪器测试（推理引擎 / 模型导入 / 控制协议 / 预处理一致性）。
    // ActivityScenario 由 androidx.test:core 提供；该依赖已通过
    // androidx.test.ext:junit 与 espresso-core 传递引入，无需再显式声明，
    // 避免为一个传递依赖新增一条需要额外仓库解析的声明。
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
}
