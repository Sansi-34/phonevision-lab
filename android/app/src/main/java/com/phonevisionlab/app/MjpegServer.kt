package com.phonevisionlab.app

import fi.iki.elonen.NanoHTTPD
import org.json.JSONObject
import java.io.IOException
import java.io.InputStream
import java.util.concurrent.atomic.AtomicBoolean

/**
 * PhoneVision Lab — MJPEG HTTP 服务器（NanoHTTPD）。
 *
 * 职责：提供两个接口——
 *   GET /ping   返回 JSON 状态（设备、分辨率、实际 FPS、帧数）
 *   GET /stream 返回 multipart/x-mixed-replace 的 JPEG 帧流
 * 为什么这样设计：
 *   - NanoHTTPD 是单文件、无依赖的嵌入式服务器，源码可读，适合学习。
 *   - /stream 返回一个“永不完结的 InputStream”：每个 JPEG 帧作为一个 part，
 *     由 Content-Type: image/jpeg + Content-Length 组成，浏览器端 `<img>` 或
 *     VLC 直接播放。接口是标准 MJPEG-over-HTTP，不依赖特定客户端。
 *   - /ping 与 /stream 分离：ping 用于探测和调试，stream 用于真正的视频。
 * 初学者调试观察点：
 *   - curl http://手机IP:8080/ping 拿不到响应 -> 手机和电脑不在同一局域网 / 端口被占。
 *   - /stream 浏览器一片空白 -> 看 serve() 是否报错、store 里是否有帧（见 logcat）。
 */
class MjpegServer(
    private val port: Int,
    private val store: LatestFrameStore,
    private val camInfo: CameraInfo,
) : NanoHTTPD(port) {

    /** /stream 的响应流：每帧一个 part，multipart boundary */
    companion object {
        private const val TAG = "MjpegServer"
        private const val BOUNDARY = "phonevision-boundary"
        private const val CT_MULTIPART =
            "multipart/x-mixed-replace;boundary=" + BOUNDARY
        private const val CT_JPEG = "image/jpeg"

        /**
         * 读循环等待新帧的最长时间（毫秒）。
         *
         * 为什么不干脆无限等：读线程阻塞在 Conditional 上时，NanoHTTPD.stop() 只能关 socket，
         * 唤不醒等待；带超时后读线程每 [STREAM_WAIT_TIMEOUT_MS] 回来一次，
         * 检查下面的 [closed] 标志并自己退出，线程不会被永久挂着。
         * 取值略大于一帧间隔（10fps≈100ms），既不增加延迟也不空转。
         */
        private const val STREAM_WAIT_TIMEOUT_MS = 250L
    }

    /**
     * 服务关闭标志：stop() 第一件事就是把它置 true 并唤醒等待者。
     * 读循环用它区分“暂时没有新帧”和“服务已停止”这两种 null 返回。
     */
    private val closed = AtomicBoolean(false)

    override fun serve(session: IHTTPSession): Response {
        return when (session.uri) {
            "/ping" -> servePing()
            "/stream" -> serveStream()
            else -> newFixedLengthResponse(
                Response.Status.NOT_FOUND,
                MIME_PLAINTEXT,
                "404 not found"
            )
        }
    }

    /** /ping：返回实时状态 JSON；status 读明确的 isStreaming，不依赖是否保存过一帧 */
    private fun servePing(): Response {
        val json = JSONObject()
            .put("status", if (camInfo.isStreaming) "streaming" else "idle")
            .put("device", camInfo.deviceName)
            .put("width", camInfo.width)
            .put("height", camInfo.height)
            .put("requestedFps", camInfo.requestedFps)
            .put("actualFps", camInfo.actualFps)
            .put("frameCount", camInfo.frameCount)
        return newFixedLengthResponse(
            Response.Status.OK,
            "application/json",
            json.toString()
        )
    }

    /**
     * /stream：返回 MJPEG 帧流。
     *
     * 关键：返回的 InputStream 不会结束，只要连接还开着就持续发送每个 JPEG 帧。
     * 发送时带上标准 MJPEG part 头（boundary、Content-Type、Content-Length），
     * 帧之间用 CRLF 分隔。帧从 store 中通过序号获取，保证并发安全。
     *
     * 未推流时直接回 503：以前这里无条件 200，客户端会拿到“连接成功但永远没有帧”的
     * 挂起连接（相机没起来/还没配置好时尤其明显）。明确拒绝对客户端更友好，
     * 客户端可以据此重试并显示真实原因。
     */
    private fun serveStream(): Response {
        if (closed.get() || !camInfo.isStreaming) {
            return newFixedLengthResponse(
                Response.Status.SERVICE_UNAVAILABLE,
                MIME_PLAINTEXT,
                "503 stream not ready: camera is not streaming\n"
            ).apply {
                addHeader("Cache-Control", "no-store")
                addHeader("Retry-After", "1")
            }
        }
        val input = FrameInputStream(store, closed)
        // 字节数传 -1：让 NanoHTTPD 使用 chunked 编码，配合无限流持续推送
        val response = newChunkedResponse(Response.Status.OK, CT_MULTIPART, input)
        // 客户端断开后立即关闭流，避免泄漏
        response.closeConnection(true)
        response.addHeader("Cache-Control", "no-store")
        return response
    }

    /**
     * 停止服务。
     *
     * 顺序很重要：先置 [closed] 并 wakeAll() 唤醒阻塞在 LatestFrameStore 里的读线程，
     * 再交给 NanoHTTPD 去关 socket。反过来（只关 socket）读线程会永远停在
     * Condition.await() 上，每次停止推流都泄漏一条线程。
     */
    override fun stop() {
        // compareAndSet：stop() 可能被反复调用（onStop + onDestroy + 相机错误），只做一次
        if (closed.compareAndSet(false, true)) {
            store.wakeAll()
        }
        super.stop()
    }

    /**
     * 从 LatestFrameStore 里拉取帧并输出为 MJPEG 流字节。
     *
     * 内部维护自身已读序号：每次等一帧新帧，写一个 part 到输出流。
     * 输出流的关闭由 NanoHTTPD 在连接结束时处理。
     */
    private class FrameInputStream(
        private val store: LatestFrameStore,
        private val closed: AtomicBoolean,
    ) : InputStream() {

        /** 当前 part 尚未写出的字节（一个 JPEG part 的完整字节） */
        private var pending: ByteArray? = null
        private var pendingPos: Int = 0

        /** 本连接已读到的最大序号 */
        private var lastSeq: Long = -1L

        /** 在同一个时间点只允许一个读方（NanoHTTPD 对单连接串行读取） */
        private val readLock = Any()

        /**
         * 批量读取：把下一个 part 的连续字节拷进 buffer。
         * 覆盖默认逐字节实现，避免整张 JPEG 一次一个字节的低效拷贝。
         *
         * 退出条件（三条都必须由本线程自己判断，没有人会来中断它）：
         *   1) [closed] 为 true —— 服务已停止，返回 -1 结束流；
         *   2) 线程被中断 —— 返回 -1；
         *   3) 读 store 抛异常 —— 转成 IOException 结束流。
         */
        override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
            if (length == 0) return 0
            synchronized(readLock) {
                while (true) {
                    val p = pending
                    if (p != null) {
                        val available = p.size - pendingPos
                        val n = minOf(available, length)
                        System.arraycopy(p, pendingPos, buffer, offset, n)
                        pendingPos += n
                        if (pendingPos >= p.size) {
                            pending = null
                            pendingPos = 0
                        }
                        return n
                    }
                    // 服务已停止：结束流，让 NanoHTTPD 收尾并关闭连接
                    if (closed.get()) return -1
                    // 带超时地等一帧：超时（null）后回到循环顶部重新检查 closed
                    val frame = try {
                        store.getAfter(lastSeq, STREAM_WAIT_TIMEOUT_MS)
                    } catch (ie: InterruptedException) {
                        // 服务停止时中断当前发送线程
                        Thread.currentThread().interrupt()
                        return -1
                    } catch (e: Exception) {
                        throw IOException("stream read failed: $e", e)
                    }
                    if (frame == null) continue
                    lastSeq = frame.seq
                    pending = buildPart(frame)
                    pendingPos = 0
                }
            }
        }

        /** 返回一个字节；没有数据时返回 -1。连接存活期间依赖批量读取，单字节用于兜底 */
        override fun read(): Int {
            val b = ByteArray(1)
            val n = read(b, 0, 1)
            return if (n == -1) -1 else b[0].toInt() and 0xff
        }

        /** 按 MJPEG-over-HTTP 标准拼一个 part：boundary + 头部 + CRLF + JPEG 数据 + CRLF */
        private fun buildPart(frame: LatestFrameStore.Frame): ByteArray {
            val header = (
                "--" + BOUNDARY + "\r\n" +
                    "Content-Type: " + CT_JPEG + "\r\n" +
                    "Content-Length: " + frame.jpeg.size + "\r\n" +
                    "\r\n"
                ).toByteArray(Charsets.ISO_8859_1)
            return header + frame.jpeg + CRLF
        }

        companion object {
            private val CRLF = byteArrayOf('\r'.code.toByte(), '\n'.code.toByte())
        }
    }
}
