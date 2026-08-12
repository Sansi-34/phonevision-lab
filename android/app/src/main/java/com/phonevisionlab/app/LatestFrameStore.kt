package com.phonevisionlab.app

import java.util.concurrent.locks.Condition
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/**
 * PhoneVision Lab — 最新帧缓存。
 *
 * 职责：作为 Camera 线程与 MJPEG 服务之间的共享“视频源”，内部只保留最新一帧 JPEG。
 * 为什么这样设计：
 *   - “只保留最新帧、新帧覆盖旧帧”能保证即使 HTTP 客户端很慢，内存也不会持续增长
 *     （普通队列会堆积）。对于实时预览，丢旧帧比堆积更合理。
 *   - 用一把可重入锁 + 一个 Condition 实现线程安全：写入方通知“有新帧”，
 *     读取方等待“有帧”。条件等待替代忙轮询，避免空转吃 CPU。
 *   - 帧带递增序号与时间戳：序号用于判断“这一帧我还没读过”，时间戳用于计算实际 FPS。
 *   - 设计上不限制多客户端：多个读方各自维护自己的 fromSeq，各自 wait 在同一个 Condition
 *     上；写入方用 signalAll() 一次唤醒全部等待线程，让每个客户端都去读比自身 fromSeq 新的帧。
 *     唯一限制是它们可能读到同一帧快照（对实时预览可接受）。
 *
 * 初学者调试观察点：
 *   - 如果 /stream 一直不出画面，先看 set() 是否被调用（写个 log）。
 *   - 如果 CPU 居高不下，可能是误把读取方写成了轮询，检查是否用了 await() 而不是空循环。
 */
class LatestFrameStore {

    /** 当前最新帧；null 表示还没有任何帧 */
    private var frame: Frame? = null

    /** 序号生成器：每次 set() 递增 */
    private var nextSeq: Long = 0L

    private val lock = ReentrantLock()

    /** 条件：在 lock 上等待“frame 变为非空或更新” */
    private val updated: Condition = lock.newCondition()

    /**
     * 写入一帧。若已有旧帧则直接覆盖（丢弃旧帧）。
     *
     * @param bytes    JPEG 编码后的字节
     * @param takenNs  ImageReader 拿到该 Image 的纳秒时间戳
     */
    fun set(bytes: ByteArray, takenNs: Long) {
        lock.withLock {
            frame = Frame(seq = nextSeq++, jpeg = bytes, timestampNs = takenNs)
            // signalAll() 唤醒所有等待读取方的线程：每个客户端都希望收到“比自身已读序号更新”的帧，
            // 若只 signal() 一个，其余客户端会一直等待直到下一帧。系统级监视锁通常会批量唤醒，
            // 但显式 signalAll() 更稳妥。
            updated.signalAll()
        }
    }

    /**
     * 读取“比 fromSeq 更新的一帧”；若尚未产生更新帧则阻塞等待。
     *
     * @param fromSeq 调用方已读过的最大序号；初次调用传 -1 表示“我什么也没读过”
     * @return 更新的帧；若被中断则返回 null（服务端应在调用处捕获中断并停止发送）
     */
    @Throws(InterruptedException::class)
    fun getAfter(fromSeq: Long): Frame? {
        lock.withLock {
            var f = frame
            // 当最新帧序号仍未超过 fromSeq 时，说明没有“新的”一帧，等待。
            while (f == null || f.seq <= fromSeq) {
                updated.await()
                f = frame
            }
            return f
        }
    }

    /** 当前最新帧序号；未推流时返回 -1 */
    fun latestSeq(): Long = lock.withLock { frame?.seq ?: -1L }

    /**
     * 清空帧缓存。用于停止推流/失败后复位：
     *   - 丢掉旧帧引用（内存可回收）；
     *   - 序号推进一格，即使随后快速重启推流，新帧序号也不会回退，
     *     避免仍在等待的读取方误读旧帧。
     * 说明：等待中的读取方被唤醒后看到 frame 为 null 会继续等待，
     * 但由于调用方会随之停止 HTTP 服务器，这些连接会被关闭，不会一直阻塞。
     */
    fun clear() {
        lock.withLock {
            frame = null
            nextSeq++
            updated.signalAll()
        }
    }

    /**
     * 一帧 JPEG 数据。
     *
     * @param seq        单调递增序号，用于并发读取时区分新旧帧
     * @param jpeg       JPEG 字节（直接交给 MJPEG 响应体）
     * @param timestampNs 帧被取出的相机时钟纳秒时间，用于计算实际 FPS
     */
    data class Frame(
        val seq: Long,
        val jpeg: ByteArray,
        val timestampNs: Long,
    )
}
