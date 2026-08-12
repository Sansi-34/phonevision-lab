// PhoneVision Lab — Gradle 构建入口配置
//
// 职责：声明仓库、统一管理插件版本、把 app 模块纳入构建。
// 为什么这样设计：Android Gradle 插件(AGP) 与 Kotlin 插件的版本只要在 settings 里出现一次，
// 根 build.gradle.kts 用 apply false 只声明不应用，避免多模块重复写版本号。
//
// 初学者调试观察点：依赖下载失败时，看这里声明的插件版本与 build.gradle 的 jcenter() 是否匹配；
// 升级 AGP / Kotlin 版本时，只需要改这里，不用到处改。

pluginManagement {
    repositories {
        // 腾讯云 maven-public 镜像：聚合 google + central，国内访问快
        maven(url = "https://mirrors.cloud.tencent.com/nexus/repository/maven-public/")
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        // 腾讯云 maven-public 镜像优先，加速依赖下载
        maven(url = "https://mirrors.cloud.tencent.com/nexus/repository/maven-public/")
        google()
        mavenCentral()
    }
}

rootProject.name = "PhoneVisionLab"

include(":app")
