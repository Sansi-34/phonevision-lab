package com.phonevisionlab.app

import android.content.Context
import android.graphics.Bitmap
import android.graphics.ImageFormat
import android.hardware.camera2.CameraAccessException
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.params.StreamConfigurationMap
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import android.util.Range
import android.util.Size
import android.view.Surface
import android.view.TextureView
import kotlin.math.abs

/**
 * PhoneVision Lab — 相机控制器（Camera2 封装）。
 *
 * 职责：打开后置相机，配置“预览 Surface + ImageReader(JPEG)”的双路输出，
 * 从 ImageReader 拿到的 JPEG 帧写入 LatestFrameStore，并维护 CameraInfo 里的运行状态。
 * 为什么这样设计：
 *   - 预览由 TextureView 显示（同一 CaptureSession 输出预览 + 编码两条 Surface）。
 *   - ImageReader(ImageFormat.JPEG) 让硬件直接产出 JPEG 字节，省去 YUV->JPEG 的软件编码。
 *   - 每帧从 ImageReader 取出后立即 close()，这是避免内存泄漏的关键（Image 持有原生缓冲）。
 *   - 所有相机操作都在专用 HandlerThread 上执行，避免阻塞主线程，也避免回调跨线程抖动。
 *   - FPS 用两重手段保障：aeFpsRange 锁帧率 + 实际输出按 onImageAvailable 测帧间隔。
 * 初学者调试观察点：
 *   - preview 黑屏但日志无异常 -> 检查 TextureView 的 SurfaceTexture 是否在 onSurfaceTextureAvailable
 *     之后才创建会话（顺序问题）。
 *   - actualFps 明显低于 target -> 看 minFrameMs 与 stallMs：stall 大说明 JPEG 编码慢。
 *   - 内存缓慢增长 -> 先怀疑 ImageReader 的 Image 没 close（每次都 close 即可）。
 */
class CameraController(
    private val context: Context,
    private val preview: TextureView,
    private val store: LatestFrameStore,
    private val info: CameraInfo,
) {
    companion object {
        private const val TAG = "CameraController"

        /** JPEG 缓冲区大小：640x480@quality70 约 30-80KB，给足余量避免 Image 溢出 */
        private const val MAX_IMAGES = 4

        /** 帧间隔统计窗口：用于平滑实际 FPS */
        private const val SMOOTHING_FPS_WINDOW = 30
    }

    /** 状态接口：UI 层据此切换按钮与文案 */
    enum class State { IDLE, STARTING, STREAMING, ERROR }

    /** 通知 UI 状态变化；来自相机线程，UI 线程随时可能读/写这个引用 -> @Volatile */
    @Volatile
    var onStateChanged: ((State, String?) -> Unit)? = null

    /**
     * 帧回调（V0-B 本机推理用）。
     *
     * 为什么加这个：推理需要"当前这一帧的 Bitmap"，而 MJPEG 推流拿的是 JPEG
     * 字节。让 CameraController 在同一帧上额外提供一个 Bitmap 回调，
     * 推理与推流就能共用同一次采集，不用开第二路相机（旧手机开两路相机
     * 往往直接失败）。
     *
     * 回调在相机线程执行，实现方必须自己切线程，且不得做耗时操作
     * （否则会拖慢采集帧率）。
     *
     * UI 线程在 start/stop 时读写这个引用，相机线程在读，所以必须 @Volatile，
     * 否则停止后相机线程可能仍看到旧的非空回调（或反之）。
     */
    @Volatile
    var onFrameBitmap: ((Bitmap) -> Unit)? = null

    // ---- 相机资源 ----
    private var cameraManager: CameraManager? = null
    private var cameraDevice: CameraDevice? = null
    private var captureSession: CameraCaptureSession? = null
    private var imageReader: ImageReader? = null

    /**
     * 预览用 Surface（包住 TextureView 的 SurfaceTexture）。
     *
     * 为什么存字段：每次 start() 都会新建一个 Surface，而 Surface 持有原生缓冲，
     * 不 release() 就是每次启停泄漏一个。存下来才能由 [stopCamera] 统一 release 并置空。
     */
    @Volatile
    private var previewSurface: Surface? = null

    // ---- 线程 ----
    private var cameraThread: HandlerThread? = null
    private var cameraHandler: Handler? = null

    // ---- 运行状态 ----

    /**
     * 启动代次：每次 start() / stop() / fail() 自增。
     *
     * 为什么需要：Camera2 的 openCamera / createCaptureSession 回调是异步的，
     * stop() 之后仍可能有迟到的回调到达。回调闭包捕获启动时的代次，执行时与
     * 当前代次比对；不一致说明"这次启动已经作废"，只能关掉自己拿到的资源，
     * 绝不写 captureSession / info.isStreaming / 状态回调这些共享状态，
     * 否则会把下一次 start() 的会话覆盖掉（UI 显示推流中但没有任何帧）。
     *
     * 只在 UI 线程（start/stop）自增，相机线程只读，@Volatile 保证可见性。
     */
    @Volatile
    private var generation = 0

    /** 是否已启动；UI 线程会读，相机线程会写 -> @Volatile */
    @Volatile
    private var isStreaming = false

    /** 记录上一帧到达时间，用于测真实帧率 */
    private var lastFrameNs: Long = 0L

    /** 帧到达间隔的滑动平均，用于输出 actualFps */
    private var emaIntervalNs: Long = 0L
    private var intervalSamples = 0

    // =====================================================================
    // 公开 API
    // =====================================================================

    /** 从设备支持的 JPEG 尺寸里挑选与目标最接近的尺寸，写入 info */
    fun chooseSizeAndCapabilities() {
        try {
            val cm = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
            val id = firstBackCamera(cm) ?: return
            val chars = cm.getCameraCharacteristics(id)
            val map = chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) ?: return

            val target = Size(Config.WIDTH, Config.HEIGHT)
            val jpegSizes = map.getOutputSizes(ImageFormat.JPEG) ?: return

            info.resolutionNote = ""
            var best: Size? = null
            var bestDeviation = Float.MAX_VALUE

            for (s in jpegSizes) {
                val dev = abs(s.width.toFloat() / target.width - 1f) + abs(s.height.toFloat() / target.height - 1f)
                if (dev < bestDeviation) {
                    bestDeviation = dev
                    best = s
                }
            }

            val chosen = best
            if (chosen != null) {
                info.width = chosen.width
                info.height = chosen.height
                info.minFrameDurationNs = map.getOutputMinFrameDuration(ImageFormat.JPEG, chosen) ?: 0L
                info.stallDurationNs = map.getOutputStallDuration(ImageFormat.JPEG, chosen) ?: 0L
            } else {
                info.width = 0
                info.height = 0
                info.minFrameDurationNs = 0L
                info.stallDurationNs = 0L
            }

            // 记录支持的 AE FPS Range
            // 说明：Camera2 从 API 21 起的正式字段名就是 CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES。
            // 之前使用 CONTROL_AE_AVAILABLE_FPS_RANGES 是本代码命名错误，不是 Android SDK 后来改名。
            val ranges: Array<Range<Int>>? = chars.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES)
            info.supportedFpsRanges = if (ranges != null && ranges.isNotEmpty()) {
                ranges.joinToString(",") { "${it.lower}-${it.upper}" }
            } else {
                "unknown"
            }

            // 选择与 Config.TARGET_FPS 最接近的 AE FPS Range 并记录
            info.fpsRangeLo = Config.TARGET_FPS
            info.fpsRangeHi = Config.TARGET_FPS
            if (ranges != null && ranges.isNotEmpty()) {
                var best: Range<Int>? = null
                var bestDiff = Int.MAX_VALUE
                for (r in ranges) {
                    val diff = abs(r.upper - Config.TARGET_FPS) + abs(r.lower - Config.TARGET_FPS)
                    if (diff < bestDiff) {
                        bestDiff = diff
                        best = r
                    }
                }
                best?.let {
                    info.fpsRangeLo = it.lower
                    info.fpsRangeHi = it.upper
                }
            }

            // 若选了非精确目标档位，记录原因（用于判断设备能力与降级逻辑）
            if (chosen != null && (chosen.width != target.width || chosen.height != target.height)) {
                info.resolutionNote = "设备无 ${target.width}x${target.height} JPEG 档位，已选最接近的 ${chosen.width}x${chosen.height}"
            }
        } catch (e: CameraAccessException) {
            Log.e(TAG, "chooseSizeAndCapabilities failed", e)
            info.resolutionNote = "读取相机能力失败：$e"
        }
    }

    /** 启动：初始化线程，打开相机并创建会话 */
    fun start(onReady: () -> Unit) {
        if (isStreaming) return
        isStreaming = true
        // 先推进代次：此后所有旧回调都失效
        val gen = ++generation
        postState(State.STARTING, null)

        cameraThread = HandlerThread("CameraThread").also { it.start() }
        cameraHandler = Handler(cameraThread!!.looper)
        cameraHandler!!.post {
            val handler = cameraHandler
            // 排队期间已经 stop()（或被下一次 start() 取代）：本次启动作废，
            // 不创建任何资源，也不碰共享状态。
            if (gen != generation || handler == null) return@post
            try {
                val cm = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
                cameraManager = cm
                val id = firstBackCamera(cm)
                if (id == null) {
                    fail("未找到后置摄像头")
                    return@post
                }

                // ImageReader 尺寸必须有效；否则直接进入明确错误状态，不能传 0
                if (info.width <= 0 || info.height <= 0) {
                    fail("相机尺寸无效：${info.width}x${info.height}")
                    return@post
                }

                val surfaceTexture = preview.surfaceTexture
                if (surfaceTexture == null) {
                    fail("预览 Surface 未就绪")
                    return@post
                }
                surfaceTexture.setDefaultBufferSize(info.width, info.height)
                // 存字段：stopCamera() 负责 release，避免每次启停泄漏一个 Surface
                val surface = Surface(surfaceTexture)
                previewSurface = surface

                // ImageReader：JPEG 输出，配合内容尺寸
                val reader = ImageReader.newInstance(info.width, info.height, ImageFormat.JPEG, MAX_IMAGES)
                // 帧回调带上本次代次：停止后才到达的帧直接丢弃，不写入 store / 不回调 UI
                reader.setOnImageAvailableListener({ r -> onImageAvailable(r, gen) }, handler)
                imageReader = reader

                // 请求权限已由 MainActivity 申请，这里直接 open
                cm.openCamera(id, object : CameraDevice.StateCallback() {
                    override fun onOpened(camera: CameraDevice) {
                        // 迟到的回调：本次启动已被 stop() 取代。
                        // 只关掉自己打开的相机，绝不写 captureSession / info / 状态回调，
                        // 否则会覆盖下一次 start() 的会话（UI 显示推流中但没有帧）。
                        if (gen != generation) {
                            Log.w(TAG, "stale onOpened (gen=$gen, current=$generation), closing camera")
                            closeCameraQuietly(camera)
                            return
                        }
                        cameraDevice = camera
                        try {
                            createSession(camera, listOf(surface, reader.surface), gen, onReady)
                        } catch (e: Exception) {
                            Log.e(TAG, "createSession failed", e)
                            fail("会话创建失败：$e")
                        }
                    }

                    override fun onDisconnected(camera: CameraDevice) {
                        if (gen != generation) {
                            closeCameraQuietly(camera)
                            return
                        }
                        Log.w(TAG, "camera disconnected")
                        fail("相机已断开")
                    }

                    override fun onError(camera: CameraDevice, error: Int) {
                        if (gen != generation) {
                            closeCameraQuietly(camera)
                            return
                        }
                        Log.e(TAG, "camera error: $error")
                        fail("相机错误：$error")
                    }
                }, handler)
            } catch (e: CameraAccessException) {
                Log.e(TAG, "open camera failed", e)
                fail("打开相机失败：$e")
            } catch (e: SecurityException) {
                Log.e(TAG, "camera permission missing", e)
                fail("缺少摄像头权限：$e")
            }
        }
    }

    /** 停止：关闭会话、相机、ImageReader，并结束线程（幂等） */
    fun stop() {
        // 无论当前是否在跑都推进代次：这样 stop() 之后迟到的启动回调一律作废
        generation++
        if (!isStreaming) return
        isStreaming = false
        // 先摘掉帧回调，避免 stop 过程中还有新帧进来触碰正在关闭的资源
        onFrameBitmap = null
        stopCamera()
        resetRuntimeState()
        info.isStreaming = false
        postState(State.IDLE, null)
    }

    // =====================================================================
    // 内部实现
    // =====================================================================

    private fun firstBackCamera(cm: CameraManager): String? {
        return try {
            val ids = cm.cameraIdList
            for (id in ids) {
                val chars = cm.getCameraCharacteristics(id)
                val facing = chars.get(CameraCharacteristics.LENS_FACING)
                if (facing != null && facing == CameraCharacteristics.LENS_FACING_BACK) return id
            }
            null
        } catch (e: CameraAccessException) {
            Log.e(TAG, "list cameras failed", e)
            null
        }
    }

    /** 创建 CaptureSession：预览 + JPEG 双路输出 */
    private fun createSession(
        camera: CameraDevice,
        surfaces: List<Surface>,
        gen: Int,
        onReady: () -> Unit,
    ) {
        val builder = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW)
        for (s in surfaces) builder.addTarget(s)

        // JPEG 质量真正应用到 CaptureRequest
        builder.set(CaptureRequest.JPEG_QUALITY, Config.JPEG_QUALITY.toByte())

        // 锁帧率：设置选中的 AE FPS Range（不直接改 SENSOR_FRAME_DURATION）
        builder.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, Range(info.fpsRangeLo, info.fpsRangeHi))

        camera.createCaptureSession(
            surfaces,
            object : CameraCaptureSession.StateCallback() {
                override fun onConfigured(session: CameraCaptureSession) {
                    // 迟到回调：stop() 之后才配置好的会话属于"作废的那次启动"。
                    // 直接关掉它，绝不写 captureSession / info.isStreaming / 状态回调。
                    if (gen != generation) {
                        Log.w(TAG, "stale onConfigured (gen=$gen, current=$generation), closing session")
                        closeSessionQuietly(session)
                        return
                    }
                    captureSession = session
                    try {
                        session.setRepeatingRequest(builder.build(), null, cameraHandler)
                        lastFrameNs = 0L
                        emaIntervalNs = 0L
                        intervalSamples = 0
                        info.isStreaming = true
                        postState(State.STREAMING, null)
                        onReady()
                    } catch (e: CameraAccessException) {
                        Log.e(TAG, "start repeating request failed", e)
                        fail("启动推流失败：$e")
                    }
                }

                override fun onConfigureFailed(session: CameraCaptureSession) {
                    if (gen != generation) {
                        closeSessionQuietly(session)
                        return
                    }
                    Log.e(TAG, "session configure failed")
                    fail("会话配置失败")
                }
            },
            cameraHandler
        )
    }

    /**
     * ImageReader 回调：取 JPEG 帧写入 LatestFrameStore。
     *
     * @param gen 注册监听时捕获的启动代次；与当前代次不一致说明这次启动已结束，
     *            这一帧属于上一代，直接丢弃
     */
    private fun onImageAvailable(reader: ImageReader, gen: Int) {
        val image = try {
            reader.acquireLatestImage()
        } catch (e: Exception) {
            Log.e(TAG, "acquire image failed", e)
            null
        }

        if (image == null) return

        try {
            if (gen != generation) return
            // 直接读取 JPEG 缓冲
            val buffer = image.planes[0].buffer
            val jpeg = ByteArray(buffer.remaining())
            buffer.get(jpeg)

            val takenNs = image.timestamp
            store.set(jpeg, takenNs)

            // V0-B：本机推理需要 Bitmap 形态的同一帧。
            // 复用 ImageReader 尺寸的解码：JPEG 解码成 Bitmap 只在有回调时进行，
            // 推流模式（无回调）不付这个开销。
            val frameCallback = onFrameBitmap
            if (frameCallback != null) {
                try {
                    val bitmap = android.graphics.BitmapFactory.decodeByteArray(
                        jpeg, 0, jpeg.size)
                    if (bitmap != null) {
                        frameCallback(bitmap)
                    }
                } catch (e: Exception) {
                    Log.w(TAG, "decode frame bitmap failed", e)
                }
            }

            // 更新状态
            info.frameCount++
            updateActualFps(System.nanoTime())
        } finally {
            // 关键：每次取到 Image 都必须 close，否则底层缓冲不被回收，内存会缓慢增长
            image.close()
        }
    }

    /**
     * 用帧到达间隔的指数滑动平均估算实际 FPS。
     * 用“间隔均值”而不是“每秒计数”，是为了在低帧率时也能快速反映变化。
     */
    private fun updateActualFps(nowNs: Long) {
        if (lastFrameNs != 0L) {
            val interval = nowNs - lastFrameNs
            if (interval > 0) {
                if (intervalSamples == 0) {
                    emaIntervalNs = interval
                } else {
                    val alpha = 0.2f
                    emaIntervalNs = (emaIntervalNs * (1 - alpha) + interval * alpha).toLong()
                }
                intervalSamples++
                if (intervalSamples >= SMOOTHING_FPS_WINDOW) {
                    info.actualFps = 1e9f / emaIntervalNs
                }
            }
        }
        lastFrameNs = nowNs
    }

    /**
     * 失败统一出口：释放全部相机资源、把 isStreaming 复位为 false、向 UI 报告 ERROR。
     * 调用方必须返回（或提前 return），不要再继续使用已关闭的资源。
     */
    private fun fail(message: String) {
        // 这次启动已经失败：推进代次，让同一批启动里随后到达的回调全部作废，
        // 避免它们再往已经清理过的资源上写状态。
        generation++
        isStreaming = false
        stopCamera()
        resetRuntimeState()
        info.isStreaming = false
        postState(State.ERROR, message)
    }

    /** 复位运行态（FPS、帧数、缓存） */
    private fun resetRuntimeState() {
        info.actualFps = 0f
        info.frameCount = 0L
        store.clear()
        lastFrameNs = 0L
        emaIntervalNs = 0L
        intervalSamples = 0
    }

    /** 关闭并置空全部相机资源；幂等，可安全重复调用 */
    private fun stopCamera() {
        try {
            captureSession?.close()
        } catch (e: Exception) {
            Log.w(TAG, "close session failed", e)
        }
        captureSession = null

        try {
            cameraDevice?.close()
        } catch (e: Exception) {
            Log.w(TAG, "close device failed", e)
        }
        cameraDevice = null

        try {
            imageReader?.close()
        } catch (e: Exception) {
            Log.w(TAG, "close reader failed", e)
        }
        imageReader = null

        // 预览 Surface 必须 release：它持有原生缓冲，不释放就是每次启停泄漏一个
        try {
            previewSurface?.release()
        } catch (e: Exception) {
            Log.w(TAG, "release preview surface failed", e)
        }
        previewSurface = null

        cameraThread?.quitSafely()
        cameraThread = null
        cameraHandler = null

        cameraManager = null
    }

    /** 关闭一个"还没登记到字段"的会话（迟到的回调里用），异常一律吞掉 */
    private fun closeSessionQuietly(session: CameraCaptureSession) {
        try {
            session.close()
        } catch (e: Exception) {
            Log.w(TAG, "close stale session failed", e)
        }
    }

    /** 关闭一个"还没登记到字段"的相机设备（迟到的回调里用），异常一律吞掉 */
    private fun closeCameraQuietly(camera: CameraDevice) {
        try {
            camera.close()
        } catch (e: Exception) {
            Log.w(TAG, "close stale camera failed", e)
        }
    }

    private fun postState(state: State, message: String?) {
        onStateChanged?.invoke(state, message)
    }
}
