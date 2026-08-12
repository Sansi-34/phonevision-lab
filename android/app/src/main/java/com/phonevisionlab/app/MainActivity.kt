package com.phonevisionlab.app

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.util.Log
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import java.net.Inet4Address
import java.net.NetworkInterface

/**
 * PhoneVision Lab — 主界面。
 *
 * 职责：申请摄像头权限、管理相机/服务器生命周期、把状态显示到界面、
 * 绑定“开始推流 / 停止推流”按钮、屏幕常亮。
 * 为什么这样设计：
 *   - 权限与 TextureView 就绪后只“启用开始按钮”，由用户主动点击推流，
 *     不自动开始（V0-A1 行为要求）。
 *   - 屏幕常亮用 FLAG_KEEP_SCREEN_ON：开始推流时设置、停止时清除。
 *     这不是后台推流，不引入 Foreground Service。
 *   - onStop() 进入后台即停止相机和 HTTP Server；onDestroy() 再做幂等清理。
 *   - IP 选择优先“名称含 wlan 的已启用网卡上的私有 IPv4”，再回退到其他私有 IPv4。
 * 初学者调试观察点：
 *   - 界面上不显示 IP -> 遍历逻辑没有命中 wlan 网卡，先看 logcat。
 *   - 切后台回来后推流停止了 -> 这是 onStop() 的预期行为，需用户重新点击开始。
 */
class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "MainActivity"
    }

    // ---- 界面 ----
    private lateinit var preview: android.view.TextureView
    private lateinit var statusText: TextView
    private lateinit var startButton: android.widget.Button
    private lateinit var stopButton: android.widget.Button

    // ---- 核心对象 ----
    private val frameStore = LatestFrameStore()
    private val cameraInfo = CameraInfo()
    private var cameraController: CameraController? = null
    private var mjpegServer: MjpegServer? = null

    /** 当前推流状态文案 */
    private var currentStateText: String = "空闲"

    /** 最近一次错误信息；无错误时为 null */
    private var lastError: String? = null

    /** 每秒刷新一次状态区，让 FPS 等实时数据动起来 */
    private val refreshHandler = android.os.Handler(android.os.Looper.getMainLooper())
    private val refreshRunnable = object : Runnable {
        override fun run() {
            refreshStatus()
            refreshHandler.postDelayed(this, 1000L)
        }
    }

    // ---- 权限申请 ----
    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            currentStateText = "就绪"
            lastError = null
        } else {
            currentStateText = "错误"
            lastError = "未获得摄像头权限，无法推流"
        }
        // 无论授予与否，都按“权限 + Surface + 未运行”统一计算按钮状态
        updateStartButtonState()
        refreshStatus()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        preview = findViewById(R.id.previewTexture)
        statusText = findViewById(R.id.statusText)
        startButton = findViewById(R.id.startButton)
        stopButton = findViewById(R.id.stopButton)

        startButton.setOnClickListener { startStreaming() }
        stopButton.setOnClickListener { stopStreaming() }

        preview.surfaceTextureListener = object : android.view.TextureView.SurfaceTextureListener {
            override fun onSurfaceTextureAvailable(
                surface: android.graphics.SurfaceTexture,
                width: Int,
                height: Int,
            ) {
                // Surface 就绪：统一按门控条件计算按钮状态，由用户主动点击开始
                updateStartButtonState()
            }

            override fun onSurfaceTextureSizeChanged(
                surface: android.graphics.SurfaceTexture,
                width: Int,
                height: Int,
            ) = Unit

            override fun onSurfaceTextureDestroyed(surface: android.graphics.SurfaceTexture): Boolean {
                return true
            }

            override fun onSurfaceTextureUpdated(surface: android.graphics.SurfaceTexture) = Unit
        }

        // 初始化相机能力信息
        cameraInfo.deviceName = android.os.Build.MODEL
        cameraController = CameraController(this, preview, frameStore, cameraInfo)
        cameraController?.chooseSizeAndCapabilities()

        requestCameraPermissionIfNeeded()

        // 启动状态区定时刷新
        refreshHandler.post(refreshRunnable)
        refreshStatus()
    }

    override fun onStop() {
        super.onStop()
        // 进入后台：停止推流，释放相机与服务器资源
        stopStreaming()
    }

    override fun onDestroy() {
        // 先清理资源，再做父类清理（幂等，onStop 已停止过也没关系）
        refreshHandler.removeCallbacks(refreshRunnable)
        stopStreaming()
        super.onDestroy()
    }

    // =====================================================================
    // 权限
    // =====================================================================

    private fun requestCameraPermissionIfNeeded() {
        // ContextCompat 在 API 21 上安全；直接调 checkSelfPermission 需要 API 23+
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            currentStateText = "就绪"
            lastError = null
            updateStartButtonState()
            refreshStatus()
        } else {
            permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    private fun hasPermission(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED

    /**
     * 统一计算“开始推流”按钮可用性：
     * 未运行 + 预览 Surface 就绪 + 摄像头权限已授予，三者同时满足才可点。
     */
    private fun updateStartButtonState() {
        startButton.isEnabled =
            mjpegServer == null &&
                preview.isAvailable &&
                hasPermission()
    }

    // =====================================================================
    // 推流
    // =====================================================================

    private fun startStreaming() {
        // 门控：权限、预览 Surface、控制器就绪、未运行，任一不满足都不启动
        if (!hasPermission()) {
            currentStateText = "错误"
            lastError = "缺少摄像头权限"
            refreshStatus()
            return
        }
        if (!preview.isAvailable) {
            currentStateText = "错误"
            lastError = "预览 Surface 未就绪"
            refreshStatus()
            return
        }
        val controller = cameraController
        if (controller == null) {
            currentStateText = "错误"
            lastError = "相机控制器未初始化"
            refreshStatus()
            return
        }
        if (mjpegServer != null) {
            currentStateText = "错误"
            lastError = "推流已在运行"
            refreshStatus()
            return
        }

        currentStateText = "正在启动推流…"
        lastError = null
        refreshStatus()

        // 屏幕常亮：推流期间保持点亮
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        // 启动 HTTP 服务器
        mjpegServer = MjpegServer(Config.PORT, frameStore, cameraInfo).also { server ->
            try {
                server.start()
            } catch (e: java.io.IOException) {
                Log.e(TAG, "server start failed", e)
                currentStateText = "错误"
                lastError = "HTTP 服务启动失败：${e.message}"
                refreshStatus()
                mjpegServer = null
                // 服务器启动失败：不进入推流，恢复按钮，清除常亮
                window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                updateStartButtonState()
                stopButton.isEnabled = false
                return
            }
        }

        startButton.isEnabled = false
        stopButton.isEnabled = true

        // 启动相机；状态变化时更新文案，不阻塞主线程
        cameraController?.onStateChanged = { state, message ->
            runOnUiThread {
                when (state) {
                    CameraController.State.STREAMING -> {
                        currentStateText = "推流中"
                    }
                    CameraController.State.ERROR -> {
                        // 相机出错：停止服务器、恢复按钮、显示真实错误，
                        // 不留“服务器正常但没有相机帧”的假运行状态
                        currentStateText = "错误"
                        lastError = message
                        handleCameraError()
                    }
                    else -> {}
                }
                refreshStatus()
            }
        }
        controller.start {}
    }

    private fun stopStreaming() {
        mjpegServer?.stop()
        mjpegServer = null
        cameraController?.stop()
        cameraController?.onStateChanged = null
        // 停止推流：清除屏幕常亮
        window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        updateStartButtonState()
        stopButton.isEnabled = false
        currentStateText = "空闲"
        refreshStatus()
    }

    /** 相机出错后的统一处理：停服务器、恢复按钮、提示错误 */
    private fun handleCameraError() {
        mjpegServer?.stop()
        mjpegServer = null
        window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        updateStartButtonState()
        stopButton.isEnabled = false
    }

    // =====================================================================
    // UI 辅助
    // =====================================================================

    /** 重新渲染状态区：状态 + IP + 地址 + FPS + 错误信息 */
    private fun refreshStatus() {
        val fpsInfo = if (cameraInfo.actualFps > 0) {
            "%.1f".format(cameraInfo.actualFps)
        } else {
            "—"
        }
        val errorLine = if (lastError != null) "\n错误: $lastError" else ""
        statusText.text = listOf(
            "状态: $currentStateText",
            "IP: ${wifiIpAddress() ?: "未知"}",
            "地址: ${streamUrl()}",
            "分辨率: ${cameraInfo.width}x${cameraInfo.height}" +
                (if (cameraInfo.resolutionNote.isNotEmpty()) " (${cameraInfo.resolutionNote})" else ""),
            "请求FPS: ${cameraInfo.requestedFps}  实测FPS: $fpsInfo",
            "帧数: ${cameraInfo.frameCount}",
            "minFrame: ${"%.1f".format(cameraInfo.minFrameMs)}ms  stall: ${"%.1f".format(cameraInfo.stallMs)}ms",
            "AE FPS Range: ${cameraInfo.supportedFpsRanges}  选用: ${cameraInfo.fpsRangeLo}-${cameraInfo.fpsRangeHi}",
        ).joinToString("\n") + errorLine
    }

    /**
     * 选择局域网 IP：优先“名称含 wlan 的已启用网卡”上的私有 IPv4；
     * 找不到再回退到其他非回环私有 IPv4（排除 APIPA 169.254.x）。
     */
    private fun wifiIpAddress(): String? {
        return try {
            val candidates = NetworkInterface.getNetworkInterfaces().toList()
                .filter { it.isUp && !it.isLoopback }

            // 第一遍：名称含 wlan 的网卡
            val wlanAddr = candidates.asSequence()
                .filter { it.name.contains(Config.IP_IGNORED_PREFIX, ignoreCase = true) }
                .mapNotNull { privateIpv4(it) }
                .firstOrNull()
            wlanAddr ?: candidates.asSequence()
                .mapNotNull { privateIpv4(it) }
                .firstOrNull()
        } catch (e: Exception) {
            Log.w(TAG, "read IP failed", e)
            null
        }
    }

    /** 取该网卡上第一个私有 IPv4 地址 */
    private fun privateIpv4(nic: NetworkInterface): String? {
        return nic.inetAddresses.toList()
            .asSequence()
            .filterIsInstance<Inet4Address>()
            .map { it.hostAddress }
            .filter { addr ->
                addr != null &&
                    !addr.startsWith("169.254.") && // APIPA
                    !addr.startsWith("0.") &&
                    isPrivateIpv4(addr)
            }
            .firstOrNull()
    }

    /** 判断是否私网 IPv4（10/8、172.16/12、192.168/16） */
    private fun isPrivateIpv4(ip: String): Boolean {
        val parts = ip.split(".")
        if (parts.size != 4) return false
        val first = parts[0].toIntOrNull() ?: return false
        val second = parts[1].toIntOrNull() ?: return false
        return first == 10 ||
            (first == 172 && second in 16..31) ||
            (first == 192 && second == 168)
    }

    private fun streamUrl(): String {
        val ip = wifiIpAddress() ?: return "http://<未取到IP>:${Config.PORT}/stream"
        return "http://$ip:${Config.PORT}/stream"
    }
}
