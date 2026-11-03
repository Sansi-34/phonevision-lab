package com.phonevisionlab.app

import android.util.Log
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

/**
 * PhoneVision Lab — 设备适配器（连接、发送、确认、断连）。
 *
 * 职责：把 [ControlProtocol.Command] 通过局域网 HTTP 发给外部控制器，
 * 处理超时、有限重试、重复命令去重，并把结果以结构化事件抛出。
 *
 * 为什么这样设计：
 *   - 硬件通信绝不写在摄像头回调或界面刷新里：本类只认识"命令"与"反馈"，
 *     不认识相机、不认识界面，可独立测试。
 *   - 网络在后台线程执行：调用方（规则引擎所在线程）不被阻塞。
 *   - 去重：requestId 级别缓存最近已发送命令，重复发送直接返回上次结果，
 *     不会让设备重复执行。
 *   - 超时与有限重试：只有 [ControlProtocol.RETRYABLE_ACTIONS] 里的
 *     幂等动作才重试；运动类动作不自动重试。
 *   - 断连后不重放：本类不缓存待发送队列；断线期间的命令直接失败，
 *     重连后由用户手动再次触发，避免"积压动作突然一起执行"。
 *
 * 初学者调试观察点：
 *   - 一直超时：确认控制器 IP/端口、同一局域网、防火墙。
 *   - 显示"已发送"但没反应：控制器没回 ack，看 message 字段。
 *   - 重复触发：确认调用方用了 requestId，且没有自己造重复命令。
 */
class DeviceAdapter(
    private val host: String,
    private val port: Int = ControlProtocol.DEFAULT_PORT,
    private val timeoutMs: Int = 2000,
    private val maxRetries: Int = 2,
) {
    private class NonRetryableHttpException(message: String) : java.io.IOException(message)
    companion object {
        private const val TAG = "DeviceAdapter"
        private const val MAX_DEDUP_CACHE = 64
    }

    /** requestId 生成器（进程内单调递增，保证唯一）。 */
    private val requestCounter = AtomicLong(0)

    /** 已发送命令缓存：requestId -> 命令，用于去重。 */
    private val sentCommands = ConcurrentHashMap<String, ControlProtocol.Command>()
    private val generation = AtomicLong(0)
    private val activeConnections = ConcurrentHashMap.newKeySet<HttpURLConnection>()
    private val executor = ThreadPoolExecutor(
        1, 1, 0, TimeUnit.MILLISECONDS, ArrayBlockingQueue<Runnable>(16),
        { task -> Thread(task, "device-adapter").apply { isDaemon = true } },
    )
    @Volatile private var disconnected = false

    /** 连接状态变化监听（界面据此更新设备灯）。 */
    var onLinkStateChanged: ((ControlProtocol.LinkState, String) -> Unit)? = null

    /** 命令生命周期事件监听（界面事件记录用）。 */
    var onCommandEvent: ((CommandEvent) -> Unit)? = null

    /** 一条命令的完整生命周期事件。 */
    data class CommandEvent(
        val command: ControlProtocol.Command,
        val status: ControlProtocol.CommandStatus,
        /** 手机侧单调时钟：命令发出的时刻 */
        val sentAtMs: Long,
        /** 手机侧单调时钟：收到确认的时刻（未确认为 null） */
        val confirmedAtMs: Long? = null,
        /** 控制器回报的执行时刻（仅设备支持时有） */
        val deviceExecutedAtMs: Long? = null,
        val message: String = "",
    )

    @Volatile
    private var linkState: ControlProtocol.LinkState =
        ControlProtocol.LinkState.DISCONNECTED

    /** 当前连接状态。 */
    fun linkState(): ControlProtocol.LinkState = linkState

    private fun setLinkState(state: ControlProtocol.LinkState, message: String = "") {
        if (linkState != state) {
            linkState = state
            onLinkStateChanged?.invoke(state, message)
        }
    }

    /** 下一个 requestId。 */
    fun nextRequestId(): String = "req-${System.currentTimeMillis().toString(16)}-" +
        requestCounter.incrementAndGet().toString(16)

    /**
     * 同步发送一条命令（在后台线程调用）。
     *
     * @param action 动作类型
     * @param target 目标设备
     * @param params 动作参数
     * @param requestId 显式指定编号（用于重试同一个逻辑命令）；空则自动生成
     * @return 结构化事件；网络异常时 status=FAILED
     */
    fun send(
        action: String,
        target: String,
        params: Map<String, Any> = emptyMap(),
        requestId: String = nextRequestId(),
        requestGeneration: Long = generation.get(),
    ): CommandEvent {
        val command = ControlProtocol.Command(
            requestId = requestId, target = target, action = action, params = params)

        fun cancelled() = CommandEvent(command, ControlProtocol.CommandStatus.FAILED,
            System.nanoTime() / 1_000_000, message = "命令已取消或设备已断开")
        if (disconnected || requestGeneration != generation.get()) return cancelled()

        // 去重：同一个 requestId 已经发过，直接返回缓存结果，不让设备重复执行
        val previous = sentCommands.putIfAbsent(command.requestId, command)
        if (previous != null) {
            Log.d(TAG, "重复命令已去重: ${command.requestId}")
            return CommandEvent(
                command = command,
                status = ControlProtocol.CommandStatus.SENT,
                sentAtMs = System.nanoTime() / 1_000_000,
                message = "重复请求（已去重）",
            )
        }

        val retryable = action in ControlProtocol.RETRYABLE_ACTIONS
        var attempts = 0
        var lastError = ""
        val sentAtMs = System.nanoTime() / 1_000_000

        while (attempts <= maxRetries) {
            if (disconnected || requestGeneration != generation.get()) return cancelled()
            attempts++
            try {
                setLinkState(ControlProtocol.LinkState.CONNECTING)
                val feedback = post(command, requestGeneration)
                if (disconnected || requestGeneration != generation.get()) return cancelled()
                if (feedback == null) {
                    lastError = "控制器未返回有效反馈"
                } else if (feedback.requestId != command.requestId) {
                    lastError = "控制器反馈的请求编号不匹配"
                } else {
                    val confirmedAtMs = System.nanoTime() / 1_000_000
                    setLinkState(ControlProtocol.LinkState.CONNECTED)
                    val event = CommandEvent(
                        command = command,
                        status = feedback.status,
                        sentAtMs = sentAtMs,
                        confirmedAtMs = confirmedAtMs,
                        deviceExecutedAtMs = feedback.executedAtMs,
                        message = feedback.message,
                    )
                    onCommandEvent?.invoke(event)
                    return event
                }
            } catch (e: Exception) {
                lastError = e.message ?: e.javaClass.simpleName
                Log.w(TAG, "命令发送失败(第 $attempts 次): $lastError")
                if (e is NonRetryableHttpException) break
            }

            // 只有幂等动作才重试；运动动作失败即停
            if (!retryable) break
            if (attempts > maxRetries) break
        }

        if (disconnected || requestGeneration != generation.get()) return cancelled()
        setLinkState(ControlProtocol.LinkState.ERROR, lastError)
        val event = CommandEvent(
            command = command,
            status = ControlProtocol.CommandStatus.FAILED,
            sentAtMs = sentAtMs,
            message = if (lastError.isBlank()) "命令失败" else "命令失败: $lastError",
        )
        onCommandEvent?.invoke(event)
        return event
    }

    /** 异步发送（内部起线程，调用方立即返回）。 */
    fun sendAsync(
        action: String,
        target: String,
        params: Map<String, Any> = emptyMap(),
        requestId: String = nextRequestId(),
        onResult: (CommandEvent) -> Unit,
    ) {
        val requestGeneration = generation.get()
        try {
            executor.execute {
                onResult(send(action, target, params, requestId, requestGeneration))
            }
        } catch (e: RejectedExecutionException) {
            val command = ControlProtocol.Command(requestId, target, action, params)
            onResult(CommandEvent(command, ControlProtocol.CommandStatus.FAILED,
                System.nanoTime() / 1_000_000, message = "设备已断开或命令队列已满"))
        }
    }

    /** Cancel queued work and interrupt in-flight connections; sent requests may already have reached the device. */
    fun cancelPending() {
        generation.incrementAndGet()
        val connections = activeConnections.toList()
        if (connections.isNotEmpty()) {
            Thread({ connections.forEach { it.disconnect() } }, "device-cancel").apply {
                isDaemon = true
                start()
            }
        }
    }

    /**
     * 断开连接：清理去重缓存与连接状态。
     *
     * 注意：不缓存任何"待发送"命令，因此断连期间不会重放过期控制命令。
     */
    fun disconnect() {
        disconnected = true
        cancelPending()
        executor.shutdownNow()
        sentCommands.clear()
        setLinkState(ControlProtocol.LinkState.DISCONNECTED)
    }

    // ---- 内部 ----

    private fun post(command: ControlProtocol.Command, requestGeneration: Long): ControlProtocol.Feedback? {
        if (disconnected || requestGeneration != generation.get()) throw java.io.IOException("命令已取消")
        val url = URL("http://$host:$port/control")
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = timeoutMs
            readTimeout = timeoutMs
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Accept", "application/json")
        }
        activeConnections.add(conn)
        try {
            if (disconnected || requestGeneration != generation.get()) throw java.io.IOException("命令已取消")
            val body = command.toJson()
            conn.outputStream.use { out: OutputStream ->
                out.write(body.toByteArray(Charsets.UTF_8))
                out.flush()
            }
            val code = conn.responseCode
            if (code !in 200..299) {
                if (code in 400..499 || code == 501) throw NonRetryableHttpException("HTTP $code")
                throw java.io.IOException("HTTP $code")
            }
            val text = BufferedReader(
                InputStreamReader(conn.inputStream, Charsets.UTF_8)).use { it.readText() }
            return ControlProtocol.Feedback.fromJson(text)
        } finally {
            activeConnections.remove(conn)
            conn.disconnect()
        }
    }
}
