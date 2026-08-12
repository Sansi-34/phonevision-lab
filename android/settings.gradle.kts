// PhoneVision Lab — Gradle 构建入口配置
//
// 职责：声明仓库、统一管理插件版本、把 app 模块纳入构建。
// 为什么这样设计：Android Gradle 插件(AGP) 与 Kotlin 插件的版本只要在 settings 里出现一次，
// 根 build.gradle.kts 用 apply false 只声明不应用，避免多模块重复写版本号。
//
// 初学者调试观察点：依赖下载失败时，看这里声明的插件版本与 build.gradle 的仓库是否匹配；
// 升级 AGP / Kotlin 版本时，只需要改这里，不用到处改。
//
// 仓库源（P0-5B 变更）：
//   默认只使用官方仓库 google() / mavenCentral() / gradlePluginPortal()，保证 GitHub 开源后
//   的构建可复现与可校验。国内网络若下载慢，可在 RELEASE.md 中按用户自行配置镜像仓库；
//   此处不作为默认源，也不进 CI。

pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "PhoneVisionLab"

include(":app")
