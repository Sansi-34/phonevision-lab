package com.phonevisionlab.app

/**
 * PhoneVision Lab — 全局配置。
 *
 * 职责：集中管理默认分辨率、目标 FPS、JPEG 质量和 HTTP 端口，其他地方统一读取。
 * 为什么这样设计：V0-A 没有远程参数控制，把可调参数放在一个文件里，
 * 改数值不用翻遍 CameraController / MjpegServer / MainActivity。
 *
 * 初学者调试观察点：
 *   - 想改推流画质/帧率/端口，只改这里即可。
 *   - 观察实际输出 FPS 与 TARGET_FPS 的差距，判断瓶颈是相机还是网络。
 */
object Config {

    /** 目标预览宽度（会向设备支持的 JPEG 分辨率取最接近值） */
    const val WIDTH = 640

    /** 目标预览高度 */
    const val HEIGHT = 480

    /** 请求的帧率；取设备支持的 AE FPS Range 中最近的值 */
    const val TARGET_FPS = 10

    /** JPEG 编码质量 0..100；70 是预览/网络带宽的折中 */
    const val JPEG_QUALITY = 70

    /** MJPEG 服务端口 */
    const val PORT = 8080

    /** 设备支持的 JPEG 分辨率与目标差异超过该比例时，视为没有合适档位 */
    const val MAX_SIZE_DEVIATION_RATIO = 0.35f

    /** 目标地址中不能包含该子串，用来过滤热点/虚拟网卡等伪局域网地址 */
    const val IP_IGNORED_PREFIX = "wlan"
}
