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
//   - "Could not find org.nanohttpd" -> 依赖仓库配置错误，检查 settings.gradle.kts 的 repositories。

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
        versionName = "0.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
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

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
}
