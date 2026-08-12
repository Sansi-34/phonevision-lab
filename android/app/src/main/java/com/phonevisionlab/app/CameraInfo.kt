package com.phonevisionlab.app

import android.os.Build

/**
 * PhoneVision Lab — 相机与推流的运行状态信息。
 *
 * 职责：聚合 /ping 接口和 UI 需要的全部状态（设备名、分辨率、请求/实际 FPS、帧数、
 * 相机能力数据等）。CameraController 在工作线程更新这些字段，MjpegServer 和 MainActivity
 * 在各自线程读取。
 * 为什么这样设计：
 *   - 所有字段用 @Volatile：保证跨线程读写可见，且实现最简（不需要锁）。
 *   - 把“状态”与“行为”分开：CameraController 管行为，CameraInfo 只承载可观察状态，
 *     也让 /ping 与 UI 共用同一份数据，避免两处重复计算。
 * 初学者调试观察点：
 *   - actualFps 一直为 0 -> 说明还没收到帧，问题在相机配置或 ImageReader。
 *   - resolutionNote 非空 -> 说明设备没有精确的 640x480 JPEG 档位，自动选了最接近的。
 */
class CameraInfo {

    /** 设备型号（用于 /ping 的 device 字段） */
    @Volatile var deviceName: String = Build.MODEL

    /** 实际选用的 JPEG 输出宽度（可能不等于 Config.WIDTH） */
    @Volatile var width: Int = 0

    /** 实际选用的 JPEG 输出高度 */
    @Volatile var height: Int = 0

    /** 请求的目标 FPS（即 Config.TARGET_FPS） */
    @Volatile var requestedFps: Int = Config.TARGET_FPS

    /**
     * 是否正在推流。由 CameraController 在会话成功后置 true、停止/失败时置 false。
     * 这是 /ping 判断 status 的实时运行状态，不再依赖“是否曾保存过一帧”。
     */
    @Volatile var isStreaming: Boolean = false

    /** 实测帧率（EMA 平滑后的近似值） */
    @Volatile var actualFps: Float = 0f

    /** 已编码并写入 LatestFrameStore 的帧总数 */
    @Volatile var frameCount: Long = 0L

    /** getOutputMinFrameDuration(JPEG, 选用尺寸) 的纳秒值，用于评估理论最高 FPS */
    @Volatile var minFrameDurationNs: Long = 0L

    /** getOutputStallDuration(JPEG, 选用尺寸) 的纳秒值，JPEG 编码停顿时间 */
    @Volatile var stallDurationNs: Long = 0L

    /** 实际选中的 AE FPS Range 下限 */
    @Volatile var fpsRangeLo: Int = 10

    /** 实际选中的 AE FPS Range 上限 */
    @Volatile var fpsRangeHi: Int = 10

    /** 设备支持的 AE FPS Range 列表（展示用，形如 "15-30,30-30"） */
    @Volatile var supportedFpsRanges: String = ""

    /** 分辨率降级说明；为空表示精确命中 Config.WIDTH x Config.HEIGHT */
    @Volatile var resolutionNote: String = ""

    /** minFrame 折算为毫秒，便于 UI 展示 */
    val minFrameMs: Double get() = minFrameDurationNs / 1e6

    /** stall 折算为毫秒，便于 UI 展示 */
    val stallMs: Double get() = stallDurationNs / 1e6
}
