// PhoneVision Lab — 工程构建配置文件（root）

// 构建脚本用 Kotlin DSL，注释一律使用 //（Kotlin DSL 不支持 #）。
// 插件版本统一定义在这里并显式声明，子模块（app）无需重复写版本。

plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
}
