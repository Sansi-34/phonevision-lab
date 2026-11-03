package com.phonevisionlab.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.view.TextureView
import android.widget.Button
import android.widget.EditText
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import android.widget.Spinner
import android.widget.ArrayAdapter
import android.widget.AdapterView
import android.view.View
import androidx.appcompat.app.AlertDialog
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

/**
 * PhoneVision Lab — 本机 AI 推理界面（V0-B）。
 *
 * 职责：导入模型、跑本机离线推理、显示预测与性能数据，并把视觉结果交给
 * 规则引擎驱动硬件。
 *
 * 为什么这样设计：
 *   - 推理绝不在主线程：相机回调（相机线程）只把最新帧放进一个有界槽位，
 *     推理线程按 INFERENCE_MIN_INTERVAL_MS 的节奏取最新帧执行。
 *     用"只保留最新帧"而不是无界队列，避免帧堆积导致延迟持续增大。
 *   - 摄像头与模型资源在 onStop/onDestroy 明确释放，前后台切换不留泄漏。
 *   - 硬件联动与推流解耦：没有连接控制器时，本界面的采集与推理完全可用。
 *   - 自动控制默认关闭，且停止控制后不再产生新的自动动作（规则引擎 reset）。
 *
 * 初学者调试观察点：
 *   - 预测不更新：看"推理帧率"是否为 0；是 0 说明推理线程没起来或模型没加载。
 *   - 延迟越来越大：确认用的是"最新帧"槽位而非累积队列。
 *   - LED 反复跳：调规则引擎的 confirmCount / 滞回阈值。
 */
class InferenceActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "InferenceActivity"

        /** 启动本界面时传入的 Extra key：设备 IP（可选，从主界面带过来） */
        const val EXTRA_DEVICE_HOST = "device_host"
    }

    // ---- 界面 ----
    private lateinit var preview: TextureView
    private lateinit var statusText: TextView
    private lateinit var eventLog: TextView
    private lateinit var importButton: Button
    private lateinit var importProgress: ProgressBar
    private lateinit var startButton: Button
    private lateinit var stopButton: Button
    private lateinit var deviceHostInput: EditText
    private lateinit var connectDeviceButton: Button
    private lateinit var testLedOnButton: Button
    private lateinit var testLedOffButton: Button
    private lateinit var autoControlButton: Button
    private lateinit var stopControlButton: Button
    private lateinit var targetClassSpinner: Spinner

    // ---- 相机与模型 ----
    private val frameStore = LatestFrameStore()
    private val cameraInfo = CameraInfo()
    private var cameraController: CameraController? = null
    private var engine: InferenceEngine? = null
    private var loadedModel: ModelPackage.LoadedModel? = null

    /**
     * 后台 IO 单线程：模型包解压/校验/落盘、已导入模型读取、TFLite Interpreter 构造
     * 全部放这里跑。
     *
     * 为什么必须移到后台：模型包最大 80 MB，解压 + 校验 + 构造 Interpreter 在 UI 线程做，
     * 大包一定会触发 ANR（输入事件 5 秒无响应）。单线程 executor 顺带把这几种操作串行化，
     * 不会出现"导入还在跑，用户又点了开始推理"的交错执行。
     * 为什么用 Executor 而不是协程：本项目没有协程依赖，不为这个改动引入新依赖。
     */
    private val ioExecutor = Executors.newSingleThreadExecutor { r ->
        Thread(r, "pvl-model-io").apply { isDaemon = true }
    }

    /**
     * 启动代次：每次 startInference()/stopInference() 自增。
     * 引擎构造是异步的，构造完成回到 UI 线程时用代次判断"这次启动是否还作数"，
     * 否则用户已经点了停止、页面已经销毁，却还会被旧任务启动一次推理。
     */
    private val startToken = AtomicLong(0L)

    /** 引擎正在后台构造：期间禁止重复点开始。 */
    @Volatile
    private var engineLoading = false

    /** 导入/加载模型包期间置位：期间禁用按钮，避免与后台 IO 交错。 */
    @Volatile
    private var importBusy = false

    // ---- 最新帧槽位（有界：只保留一帧，绝不堆积）----
    @Volatile
    private var pendingFrame: Bitmap? = null
    private val frameLock = Any()

    // ---- 推理线程 ----
    private val inferenceStop = AtomicBoolean(false)
    private var inferenceThread: Thread? = null
    private val lastInferenceAtMs = AtomicLong(0L)

    // ---- 硬件联动 ----
    @Volatile private var deviceAdapter: DeviceAdapter? = null
    @Volatile private var ruleEngine: RuleEngine? = null
    private val controlLock = Any()
    private var manualCommandSucceeded = false
    private var manualVerificationConfirmed = false

    /** 自动控制开关：默认关闭。 */
    @Volatile
    private var autoControlEnabled = false

    /** 规则配置（从 SharedPreferences 读，界面暂用默认值，后续可加设置页）。 */
    private val ruleConfig = RuleEngine.RuleConfig(
        targetClass = "",
        triggerConfidence = 0.75f,
        confirmCount = 3,
        exitConfidence = 0.45f,
        releaseFrames = 5,
        cooldownMs = 2000L,
    )

    // ---- 统计 ----
    @Volatile
    private var lastPrediction: InferenceEngine.Prediction? = null
    private val eventLines = ArrayDeque<String>(40)

    // ---- 权限 ----
    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            updateStartButtonState()
        } else {
            appendEvent("未获得摄像头权限，无法推理")
        }
    }

    private val modelPicker = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode != RESULT_OK) return@registerForActivityResult
        val uri = result.data?.data ?: return@registerForActivityResult
        importModel(uri)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_inference)

        preview = findViewById(R.id.inferPreview)
        statusText = findViewById(R.id.inferStatus)
        eventLog = findViewById(R.id.eventLog)
        importButton = findViewById(R.id.importModelButton)
        importProgress = findViewById(R.id.importProgress)
        startButton = findViewById(R.id.startInferButton)
        stopButton = findViewById(R.id.stopInferButton)
        deviceHostInput = findViewById(R.id.deviceHostInput)
        connectDeviceButton = findViewById(R.id.connectDeviceButton)
        testLedOnButton = findViewById(R.id.testLedOnButton)
        testLedOffButton = findViewById(R.id.testLedOffButton)
        autoControlButton = findViewById(R.id.autoControlButton)
        stopControlButton = findViewById(R.id.stopControlButton)
        targetClassSpinner = findViewById(R.id.targetClassSpinner)

        // 从主界面带过来的 IP 预填
        intent.getStringExtra(EXTRA_DEVICE_HOST)?.let {
            if (it.isNotBlank()) deviceHostInput.setText(it)
        }

        importButton.setOnClickListener { pickModelFile() }
        startButton.setOnClickListener { startInference() }
        stopButton.setOnClickListener { stopInference() }
        connectDeviceButton.setOnClickListener { connectDevice() }
        testLedOnButton.setOnClickListener { manualLed(true) }
        testLedOffButton.setOnClickListener { manualLed(false) }
        autoControlButton.setOnClickListener { setAutoControl(true) }
        stopControlButton.setOnClickListener { stopControl() }
        targetClassSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onNothingSelected(parent: AdapterView<*>?) = Unit
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                val label = loadedModel?.labels?.getOrNull(position) ?: return
                if (label == ruleConfigRef.targetClass) return
                if (autoControlEnabled) stopControl()
                synchronized(controlLock) {
                    ruleConfigRef = ruleConfigRef.copy(targetClass = label)
                    ruleEngine = RuleEngine(ruleConfigRef)
                }
                appendEvent("自动控制目标类别: $label")
            }
        }

        preview.surfaceTextureListener = object : TextureView.SurfaceTextureListener {
            override fun onSurfaceTextureAvailable(
                surface: android.graphics.SurfaceTexture, width: Int, height: Int,
            ) {
                updateStartButtonState()
            }

            override fun onSurfaceTextureSizeChanged(
                surface: android.graphics.SurfaceTexture, width: Int, height: Int,
            ) = Unit

            override fun onSurfaceTextureDestroyed(
                surface: android.graphics.SurfaceTexture,
            ): Boolean = true

            override fun onSurfaceTextureUpdated(
                surface: android.graphics.SurfaceTexture,
            ) = Unit
        }

        cameraController = CameraController(this, preview, frameStore, cameraInfo)
        cameraController?.chooseSizeAndCapabilities()

        requestCameraPermissionIfNeeded()

        // 列出已导入模型（重启 App 后仍可选择）
        val imported = ModelPackage.listImported(this)
        if (imported.isEmpty()) {
            statusText.text = "尚未导入模型。请点\"导入模型包\"选择 .pvlmodel.zip"
        } else {
            statusText.text = "已导入 ${imported.size} 个模型，选择其中一个开始推理"
            // 默认加载最近导入的一个
            loadImportedModel(imported.last().id)
        }
    }

    // =====================================================================
    // 模型导入
    // =====================================================================

    private fun pickModelFile() {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "application/zip"
        }
        // 部分文件管理器不认 application/zip，退化为 */*
        try {
            modelPicker.launch(intent)
        } catch (e: Exception) {
            Log.w(TAG, "open document failed, fallback to */*", e)
            modelPicker.launch(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "*/*"
            })
        }
    }

    private fun importModel(uri: android.net.Uri) {
        if (importBusy) {
            appendEvent("模型导入/加载仍在进行，请稍候")
            return
        }
        // 复制 + 解压 + manifest 校验 + TFLite 张量验证 + 落盘 全是阻塞 IO，
        // 整体丢给 ioExecutor：UI 线程只做"禁用按钮 / 显示进度 / 回写结果"。
        // 之前这段全在主线程，几十 MB 的模型包必然 ANR。
        setImportBusy(true, "正在导入模型包…")
        ioExecutor.execute {
            val cacheFile = java.io.File(cacheDir, "import-model.zip")
            var success: ModelPackage.ImportResult.Success? = null
            var failure: String? = null
            try {
                // 先把用户选的文件复制到 cacheDir：系统返回的 Uri 可能只在回调期间有效
                try {
                    contentResolver.openInputStream(uri)?.use { input ->
                        cacheFile.outputStream().use { output ->
                            val buffer = ByteArray(8192)
                            var total = 0L
                            while (true) {
                                val count = input.read(buffer)
                                if (count < 0) break
                                total += count
                                if (total > ModelPackage.MAX_ARCHIVE_BYTES) {
                                    throw java.io.IOException("模型包超过 80 MB")
                                }
                                output.write(buffer, 0, count)
                            }
                        }
                    } ?: throw java.io.IOException("无法读取所选文件")
                    when (val result = ModelPackage.importFromZip(this, cacheFile.absolutePath)) {
                        is ModelPackage.ImportResult.Success -> success = result
                        is ModelPackage.ImportResult.Failure -> failure = result.error
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "copy/import model failed", e)
                    failure = "复制模型文件失败: ${e.message}"
                }
            } finally {
                cacheFile.delete()
            }

            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                setImportBusy(false, null)
                val ok = success
                if (ok != null) {
                    appendEvent("模型导入成功: ${ok.model.displayName}")
                    // loadImportedModel 自己会再切一次后台线程（读 model.tflite 与元数据）
                    loadImportedModel(ok.model.id)
                } else {
                    val error = failure ?: "导入失败"
                    Log.w(TAG, "import rejected: $error")
                    appendEvent("导入失败: $error")
                    statusText.text = "导入失败: $error"
                    Toast.makeText(this, "导入失败: $error", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    /**
     * 导入/加载期间切换界面状态：禁用导入与开始按钮、显示进度条。
     * 只在 UI 线程调用。
     */
    private fun setImportBusy(busy: Boolean, message: String?) {
        importBusy = busy
        importButton.isEnabled = !busy
        importProgress.visibility = if (busy) View.VISIBLE else View.GONE
        if (busy) {
            startButton.isEnabled = false
        } else {
            updateStartButtonState()
        }
        if (message != null) statusText.text = message
    }

    private fun loadImportedModel(id: String) {
        // 先停掉正在进行的推理，避免旧引擎被释放后仍被使用
        stopInference()
        if (importBusy) {
            appendEvent("模型导入仍在进行，请稍候再切换模型")
            return
        }
        // 读 manifest / labels / consistency 也是磁盘 IO，业务上必须和导入串行（同一个 executor）
        setImportBusy(true, "正在加载模型…")
        ioExecutor.execute {
            val loaded = ModelPackage.load(this, id)
            val reason = if (loaded == null) ModelPackage.lastLoadError else null
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                setImportBusy(false, null)
                if (loaded == null) {
                    appendEvent("模型加载失败: $reason")
                    statusText.text = "模型加载失败: $reason"
                    return@runOnUiThread
                }
                applyLoadedModel(loaded)
            }
        }
    }

    /** 模型加载成功后的界面回写（UI 线程） */
    private fun applyLoadedModel(loaded: ModelPackage.LoadedModel) {
        loadedModel = loaded
        val consistency = loaded.consistencyTop1Agreement
        val consistencyText = if (consistency != null) {
            " 一致性Top1=${"%.1f".format(consistency * 100)}%"
        } else {
            ""
        }
        statusText.text = buildString {
            append("模型: ${loaded.displayName}\n")
            append("输入: ${loaded.spec.inputSize}px ${loaded.spec.colorOrder} ")
            append("${loaded.spec.layout} ${loaded.spec.normalization}\n")
            append("类别(${loaded.labels.size}): ${loaded.labels.joinToString(", ")}\n")
            append(consistencyText)
        }
        // 规则引擎目标类别：默认第一个类别（用户后续可改）
        val cfg = ruleConfig.copy(targetClass = loaded.labels.firstOrNull() ?: "")
        ruleConfigRef = cfg
        ruleEngine = RuleEngine(cfg)
        targetClassSpinner.adapter = ArrayAdapter(
            this, android.R.layout.simple_spinner_dropdown_item, loaded.displayLabels)
        appendEvent("模型已加载: ${loaded.displayName}")
        updateStartButtonState()
    }

    /** 保存可变规则配置的引用（ruleConfig 是 val，用这个引用持有最新值）。 */
    private var ruleConfigRef: RuleEngine.RuleConfig = ruleConfig

    // =====================================================================
    // 推理启停
    // =====================================================================

    private fun startInference() {
        if (engine != null || inferenceThread?.isAlive == true || engineLoading || importBusy) {
            appendEvent("上一次推理正在停止，请稍候")
            return
        }
        if (!hasCameraPermission()) {
            requestCameraPermissionIfNeeded()
            return
        }
        if (!preview.isAvailable) {
            appendEvent("预览 Surface 未就绪")
            return
        }
        val controller = cameraController
        if (controller == null) {
            appendEvent("相机控制器未初始化")
            return
        }
        val model = loadedModel
        if (model == null) {
            appendEvent("尚未加载模型")
            return
        }

        // 构造 TFLite Interpreter 要读几十 MB 模型并做张量分配，耗时随包体增长，
        // 必须离开 UI 线程（大包在 UI 线程构造会直接 ANR）。构造完成后回 UI 线程继续。
        val token = startToken.incrementAndGet()
        engineLoading = true
        startButton.isEnabled = false
        statusText.text = "正在初始化推理引擎…"
        ioExecutor.execute {
            var failure: String? = null
            val created = try {
                InferenceEngine(
                    modelPath = model.tflitePath,
                    spec = model.spec,
                    labels = model.labels,
                    displayLabels = model.displayLabels,
                )
            } catch (e: Exception) {
                Log.e(TAG, "engine init failed", e)
                failure = e.message
                null
            }
            runOnUiThread {
                engineLoading = false
                // 构造期间用户已点停止、页面已销毁，或又发起了新的启动：这次结果作废
                if (isFinishing || isDestroyed || token != startToken.get()) {
                    created?.close()
                    if (!isDestroyed) updateStartButtonState()
                    return@runOnUiThread
                }
                if (created == null) {
                    appendEvent("推理引擎初始化失败: $failure")
                    statusText.text = "推理引擎初始化失败: $failure"
                    updateStartButtonState()
                    return@runOnUiThread
                }
                beginInference(created)
            }
        }
    }

    /**
     * 引擎已就绪，接上相机与推理线程（UI 线程）。
     */
    private fun beginInference(created: InferenceEngine) {
        val controller = cameraController
        if (controller == null) {
            // 拿不到控制器就别留着 native 解释器
            created.close()
            appendEvent("相机控制器未初始化")
            updateStartButtonState()
            return
        }
        engine = created
        created.resetStats()

        // 相机帧 -> 最新帧槽位（相机线程，只留最新一帧）
        // 显式写出参数类型：Kotlin 对 SAM/函数类型属性赋值推断不出 Bitmap 类型。
        controller.onFrameBitmap = { bitmap: Bitmap ->
            synchronized(frameLock) {
                if (inferenceStop.get()) {
                    bitmap.recycle()
                } else {
                    val old = pendingFrame
                    pendingFrame = bitmap
                    old?.recycle()
                }
            }
        }

        inferenceStop.set(false)
        lastInferenceAtMs.set(0L)
        lastPrediction = null
        inferenceThread = Thread({
            try {
                inferenceLoop(created)
            } catch (e: Exception) {
                Log.e(TAG, "inference thread failed", e)
                runOnUiThread { if (!isDestroyed) appendEvent("推理线程异常: ${e.message}") }
            } finally {
                created.close()
                runOnUiThread {
                    if (engine === created) {
                        engine = null
                        inferenceThread = null
                        if (!isDestroyed) updateStartButtonState()
                    }
                }
            }
        }, "pvl-inference").also {
            it.start()
        }

        controller.onStateChanged = { state, message ->
            runOnUiThread {
                if (state == CameraController.State.ERROR) {
                    appendEvent("相机错误: $message")
                    stopInference()
                }
            }
        }
        controller.start {}

        startButton.isEnabled = false
        stopButton.isEnabled = true
        appendEvent("推理已启动")
    }

    private fun stopInference() {
        // 让还在后台构造引擎的那次启动作废：构造完成后会看到代次不匹配并自行关闭引擎
        startToken.incrementAndGet()
        engineLoading = false
        inferenceStop.set(true)
        if (autoControlEnabled) stopControl()
        cameraController?.onFrameBitmap = null
        cameraController?.stop()
        synchronized(frameLock) {
            pendingFrame?.recycle()
            pendingFrame = null
        }
        // The inference thread owns and closes its interpreter after any current
        // invocation returns. Do not close the native interpreter on the UI thread.
        updateStartButtonState()
        stopButton.isEnabled = false
        appendEvent("推理已停止")
    }

    /**
     * 推理循环：按固定节奏取"最新帧"执行，不在主线程。
     *
     * 关键点：
     *   - 只取最新帧并清空槽位，绝不累积：慢一帧就丢一帧，延迟不会越积越大。
     *   - 两次推理之间至少间隔 Config.INFERENCE_MIN_INTERVAL_MS，避免无意义跑满。
     */
    private fun inferenceLoop(engine: InferenceEngine) {
        while (!inferenceStop.get()) {
            val frame = synchronized(frameLock) {
                val f = pendingFrame
                pendingFrame = null
                f
            }
            if (frame == null) {
                Thread.sleep(10)
                continue
            }

            val now = SystemClock.elapsedRealtime()
            val sinceLast = now - lastInferenceAtMs.get()
            if (sinceLast < Config.INFERENCE_MIN_INTERVAL_MS) {
                // 还没到下一次推理的时间点：丢弃这一帧（主动限频，不算失败）
                engine.markFrameSkipped()
                frame.recycle()
                continue
            }
            lastInferenceAtMs.set(now)

            val prediction = try {
                engine.run(frame)
            } finally {
                frame.recycle()
            }

            if (inferenceStop.get()) break
            if (prediction == null) {
                continue
            }
            lastPrediction = prediction

            // 规则引擎 -> 硬件（仅自动控制开启时）
            maybeDriveHardware(prediction, now)

            runOnUiThread { refreshStatus() }
        }
    }

    // =====================================================================
    // 硬件联动
    // =====================================================================

    private fun connectDevice() {
        val host = deviceHostInput.text.toString().trim()
        if (host.isBlank()) {
            appendEvent("请填写控制器 IP")
            return
        }
        // 连接前先停掉可能残留的旧连接
        if (autoControlEnabled) stopControl()
        deviceAdapter?.disconnect()
        manualCommandSucceeded = false
        manualVerificationConfirmed = false
        val adapter = DeviceAdapter(host = host)
        adapter.onCommandEvent = { event -> onCommandEvent(event) }
        adapter.onLinkStateChanged = { state, message ->
            runOnUiThread {
                if (deviceAdapter !== adapter || isDestroyed) return@runOnUiThread
                when (state) {
                    ControlProtocol.LinkState.CONNECTED -> {
                        testLedOnButton.isEnabled = true
                        testLedOffButton.isEnabled = true
                        autoControlButton.isEnabled = true
                        appendEvent("设备已连接")
                    }
                    ControlProtocol.LinkState.ERROR -> {
                        testLedOnButton.isEnabled = false
                        testLedOffButton.isEnabled = false
                        autoControlButton.isEnabled = false
                        manualCommandSucceeded = false
                        manualVerificationConfirmed = false
                        if (autoControlEnabled) stopControl()
                        appendEvent("设备连接异常: $message")
                    }
                    else -> {}
                }
            }
        }
        deviceAdapter = adapter

        // 用一次只读查询验证链路（不动作任何执行器）
        adapter.sendAsync(
            action = ControlProtocol.ACTION_STATUS,
            target = "led0",
        ) { event ->
            runOnUiThread {
                if (deviceAdapter !== adapter || isDestroyed) return@runOnUiThread
                if (event.status == ControlProtocol.CommandStatus.FAILED) {
                    appendEvent("连接失败: ${event.message}")
                } else {
                    appendEvent("设备在线（${event.status}）")
                }
            }
        }
    }

    private fun manualLed(on: Boolean) {
        if (autoControlEnabled) {
            appendEvent("请先停止自动控制，再手动测试")
            return
        }
        val adapter = deviceAdapter ?: run {
            appendEvent("尚未连接设备")
            return
        }
        val action = if (on) ControlProtocol.ACTION_LED_ON
        else ControlProtocol.ACTION_LED_OFF
        adapter.sendAsync(action, ruleConfigRef.target) { event ->
            runOnUiThread {
                if (deviceAdapter !== adapter || isDestroyed) return@runOnUiThread
                if (event.status == ControlProtocol.CommandStatus.EXECUTED ||
                    event.status == ControlProtocol.CommandStatus.RECEIVED) {
                    manualCommandSucceeded = true
                }
                appendEvent(formatEvent(event))
            }
        }
    }

    private fun setAutoControl(enabled: Boolean) {
        if (enabled && (deviceAdapter?.linkState() != ControlProtocol.LinkState.CONNECTED ||
                engine == null || ruleConfigRef.targetClass.isBlank())) {
            appendEvent("请先加载模型、启动推理并连接设备")
            return
        }
        if (enabled && !manualCommandSucceeded) {
            appendEvent("请先连接设备并完成手动验证，再开启自动控制")
            return
        }
        if (enabled && !manualVerificationConfirmed) {
            AlertDialog.Builder(this)
                .setMessage("请确认手动开关时 LED 实际按预期动作，再开启自动控制。")
                .setPositiveButton("已确认") { _, _ ->
                    manualVerificationConfirmed = true
                    setAutoControl(true)
                }
                .setNegativeButton("取消", null)
                .show()
            return
        }
        synchronized(controlLock) {
            autoControlEnabled = enabled
            ruleEngine?.reset()
        }
        autoControlButton.text = if (enabled) "自动控制：已开启" else "开启自动控制（默认关）"
        autoControlButton.isEnabled = true
        stopControlButton.isEnabled = enabled
        testLedOnButton.isEnabled = !enabled
        testLedOffButton.isEnabled = !enabled
        appendEvent(if (enabled) "自动控制已开启" else "自动控制已关闭")
    }

    private fun stopControl() {
        synchronized(controlLock) {
            autoControlEnabled = false
            ruleEngine?.reset()
            deviceAdapter?.cancelPending()
        }
        stopControlButton.isEnabled = false
        autoControlButton.text = "开启自动控制（默认关）"
        val connected = deviceAdapter?.linkState() == ControlProtocol.LinkState.CONNECTED
        testLedOnButton.isEnabled = connected
        testLedOffButton.isEnabled = connected
        appendEvent("已停止自动控制；已发送的命令可能仍由设备执行")
    }

    /**
     * 把推理结果交给规则引擎；只有状态变化时才发命令。
     *
     * 这一层绝不直接调用 DeviceAdapter：规则引擎是纯逻辑，
     * 硬件适配是独立一层，两者通过这里的编排连接。
     */
    private fun maybeDriveHardware(
        prediction: InferenceEngine.Prediction,
        nowMs: Long,
    ) {
        synchronized(controlLock) {
            if (!autoControlEnabled) return
            val adapter = deviceAdapter ?: return
            val engine = ruleEngine ?: return
            val output = engine.update(prediction, nowMs)
            if (output.shouldTurnOn || output.shouldTurnOff) {
                val cfg = ruleConfigRef
                val action = if (output.shouldTurnOn) cfg.onAction else cfg.offAction
                adapter.sendAsync(action, cfg.target) { event ->
                    runOnUiThread { if (!isDestroyed) appendEvent(formatEvent(event)) }
                }
            }
        }
    }

    private fun onCommandEvent(event: DeviceAdapter.CommandEvent) {
        // 事件已在回调线程；这里只记录，不碰 UI（调用方会 runOnUiThread）
        Log.i(TAG, "command event: ${formatEvent(event)}")
    }

    private fun formatEvent(event: DeviceAdapter.CommandEvent): String {
        val statusText = when (event.status) {
            ControlProtocol.CommandStatus.SENT -> "已发送"
            ControlProtocol.CommandStatus.RECEIVED -> "已接收"
            ControlProtocol.CommandStatus.EXECUTED -> "已执行"
            ControlProtocol.CommandStatus.FAILED -> "失败"
        }
        val rtt = event.confirmedAtMs?.let { (it - event.sentAtMs).toString() + "ms" } ?: "-"
        return "[${SystemClock.elapsedRealtime() / 1000}] ${event.command.action} " +
            "${event.command.target} -> $statusText (rtt=$rtt) ${event.message}".trim()
    }

    // =====================================================================
    // 状态显示
    // =====================================================================

    private val refreshHandler = android.os.Handler(android.os.Looper.getMainLooper())
    private val refreshRunnable = object : Runnable {
        override fun run() {
            refreshStatus()
            refreshHandler.postDelayed(this, 500)
        }
    }

    private fun refreshStatus() {
        val engine = engine ?: return
        val prediction = lastPrediction
        val sb = StringBuilder()
        sb.append("模型: ${loadedModel?.displayName ?: "-"}\n")
        if (prediction != null) {
            sb.append("预测: ${prediction.topDisplayLabel} ")
            sb.append("(${"%.1f".format(prediction.confidence * 100)}%)\n")
        } else {
            sb.append("预测: 等待首帧…\n")
        }
        sb.append("推理帧率: ${"%.1f".format(engine.measuredFps)} fps")
        sb.append("  完成帧: ${engine.completedFrames()}")
        sb.append("  丢弃: ${engine.droppedFrames()}\n")
        sb.append("预处理: ${"%.1f".format(engine.averagePreprocessMs())}ms  ")
        sb.append("模型: ${"%.1f".format(engine.averageModelMs())}ms  ")
        sb.append("后处理: ${"%.1f".format(engine.averagePostprocessMs())}ms\n")
        sb.append("最近帧间隔: ${engine.lastFrameIntervalMs()}ms\n")
        val rule = ruleEngine
        if (rule != null) {
            sb.append("规则: 目标=${ruleConfigRef.targetClass} ")
            sb.append("状态=${if (rule.currentState()) "已触发" else "未触发"} ")
            sb.append("连续确认=${rule.lastOutput().confirmStreak}/")
            sb.append("${ruleConfigRef.confirmCount} ")
            sb.append("自动控制=${if (autoControlEnabled) "开" else "关"}")
        }
        statusText.text = sb.toString()
    }

    private fun appendEvent(line: String) {
        eventLines.addLast(line)
        while (eventLines.size > 40) eventLines.removeFirst()
        eventLog.text = eventLines.joinToString("\n")
    }

    // =====================================================================
    // 生命周期
    // =====================================================================

    private fun hasCameraPermission(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED

    private fun requestCameraPermissionIfNeeded() {
        if (hasCameraPermission()) {
            updateStartButtonState()
        } else {
            permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    private fun updateStartButtonState() {
        startButton.isEnabled = loadedModel != null &&
            preview.isAvailable &&
            hasCameraPermission() &&
            engine == null &&
            !engineLoading &&
            !importBusy
    }

    override fun onStart() {
        super.onStart()
        refreshHandler.post(refreshRunnable)
    }

    override fun onStop() {
        super.onStop()
        // 进入后台：停止推理，释放相机资源（与主界面推流行为一致）
        stopInference()
        deviceAdapter?.disconnect()
        deviceAdapter = null
        manualCommandSucceeded = false
        manualVerificationConfirmed = false
        testLedOnButton.isEnabled = false
        testLedOffButton.isEnabled = false
        autoControlButton.isEnabled = false
        refreshHandler.removeCallbacks(refreshRunnable)
    }

    override fun onDestroy() {
        refreshHandler.removeCallbacks(refreshRunnable)
        stopInference()
        deviceAdapter?.disconnect()
        deviceAdapter = null
        // 停掉后台 IO 线程：排队中的导入/加载直接丢弃，正在执行的那个跑完就结束
        //（它的 UI 回写会因 isDestroyed 提前返回；已构造好的引擎由它自己负责 close）
        ioExecutor.shutdownNow()
        super.onDestroy()
    }
}
