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

    // =====================================================================
    // 本机 AI 推理（V0-B 新增）
    // =====================================================================

    /**
     * 是否启用 NNAPI 委派。
     *
     * 默认 false：NNAPI 在不同厂商 ROM 上行为差异很大，未在本项目目标机型上
     * 逐台验证前不启用。开启前必须先在真机上确认"帧率确实提升且结果正确"，
     * 否则宁可慢一点也要结果可复现。
     */
    const val USE_NNAPI = false

    /** 推理线程数：旧手机多为 4-8 核，2 线程是稳妥默认（不抢满导致掉帧）。 */
    const val INFERENCE_THREADS = 2

    /**
     * 推理频率上限（Hz）。相机可能 30fps，但模型每次执行有固定耗时，
     * 无意义地跑满每一帧只会发热。这里限制为 10Hz，与推流默认帧率一致。
     * 说明：这是"最多多快跑一次推理"，不是"保证达到"；实际帧率由
     * InferenceEngine.measuredFps 实测给出。
     */
    const val INFERENCE_MAX_HZ = 10

    /** 两次推理之间的最小间隔（毫秒），由 INFERENCE_MAX_HZ 推导。 */
    const val INFERENCE_MIN_INTERVAL_MS = 1000 / INFERENCE_MAX_HZ

    /** 推理用画面宽度：与推流预览一致，减少一次额外缩放。 */
    const val INFERENCE_WIDTH = 640

    /** 推理用画面高度。 */
    const val INFERENCE_HEIGHT = 480
}
