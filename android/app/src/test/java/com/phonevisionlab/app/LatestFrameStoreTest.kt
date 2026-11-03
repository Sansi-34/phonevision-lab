package com.phonevisionlab.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * LatestFrameStore 的 JVM 单元测试（纯 java.util.concurrent，无 Android 依赖）。
 *
 * 重点是"读线程会不会永久阻塞"这条线——它是 /stream 停止时线程泄漏的根因：
 *   1. getAfter 必须能返回比 fromSeq 更新的帧；
 *   2. 没有新帧时必须按超时返回 null，而不是无限等待；
 *   3. wakeAll() 必须能立刻叫醒等待中的读方（服务停止用）；
 *   4. clear() 丢帧并推进序号，避免重启后读方读到旧帧。
 */
class LatestFrameStoreTest {

    @Test
    fun `set then getAfter returns the frame with its sequence`() {
        val store = LatestFrameStore()
        store.set(byteArrayOf(1, 2, 3), takenNs = 100L)

        val frame = store.getAfter(fromSeq = -1L, timeoutMs = 0L)
        assertEquals(0L, frame?.seq)
        assertEquals(3, frame?.jpeg?.size)
        assertEquals(100L, frame?.timestampNs)
    }

    @Test
    fun `getAfter with zero timeout is non-blocking when no new frame`() {
        val store = LatestFrameStore()
        store.set(byteArrayOf(1), takenNs = 0L)

        val started = System.nanoTime()
        val frame = store.getAfter(fromSeq = 0L, timeoutMs = 0L)
        val elapsedMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started)

        assertNull("序号未前进时不应返回旧帧", frame)
        assertTrue("timeout<=0 必须立即返回，实耗 ${elapsedMs}ms", elapsedMs < 200)
    }

    @Test
    fun `getAfter waits up to the timeout then returns null`() {
        val store = LatestFrameStore()
        val started = System.nanoTime()
        val frame = store.getAfter(fromSeq = -1L, timeoutMs = 120L)
        val elapsedMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started)

        assertNull(frame)
        assertTrue("应等满超时，实耗 ${elapsedMs}ms", elapsedMs >= 100)
        assertTrue("不应远超超时，实耗 ${elapsedMs}ms", elapsedMs < 1500)
    }

    @Test
    fun `wakeAll unblocks a waiting reader immediately`() {
        val store = LatestFrameStore()
        val returned = CountDownLatch(1)

        val reader = Thread {
            store.getAfter(fromSeq = -1L, timeoutMs = 5000L)
            returned.countDown()
        }
        reader.isDaemon = true
        reader.start()

        // 等读线程真正进入 awaitNanos（TIMED_WAITING）再唤醒，
        // 否则 signal 可能早于等待，测试会因"丢失唤醒"而假失败。
        val deadline = System.currentTimeMillis() + 2000
        while (reader.state != Thread.State.TIMED_WAITING &&
            System.currentTimeMillis() < deadline
        ) {
            Thread.sleep(10)
        }
        assertEquals(
            "读线程应已阻塞在 Condition 上",
            Thread.State.TIMED_WAITING, reader.state
        )

        val started = System.nanoTime()
        store.wakeAll()

        assertTrue(
            "wakeAll() 后读线程必须立刻返回，而不是等满 5s",
            returned.await(2, TimeUnit.SECONDS)
        )
        val elapsedMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started)
        assertTrue("唤醒延迟应远小于超时，实耗 ${elapsedMs}ms", elapsedMs < 1500)
        reader.join(1000)
    }

    @Test
    fun `set wakes a waiting reader`() {
        val store = LatestFrameStore()
        val result = arrayOfNulls<LatestFrameStore.Frame>(1)
        val done = CountDownLatch(1)

        val reader = Thread {
            result[0] = store.getAfter(fromSeq = -1L, timeoutMs = 5000L)
            done.countDown()
        }
        reader.isDaemon = true
        reader.start()

        Thread.sleep(80)
        store.set(byteArrayOf(9), takenNs = 7L)

        assertTrue("新帧应唤醒读方", done.await(2, TimeUnit.SECONDS))
        assertEquals(0L, result[0]?.seq)
        reader.join(1000)
    }

    @Test
    fun `clear drops the frame and advances the sequence`() {
        val store = LatestFrameStore()
        store.set(byteArrayOf(1), takenNs = 0L)
        val first = store.getAfter(-1L, 0L)
        store.clear()

        assertEquals("清空后无帧", -1L, store.latestSeq())
        assertNull(
            "旧 fromSeq 不得读到已清掉的帧",
            store.getAfter(fromSeq = first!!.seq, timeoutMs = 0L)
        )

        store.set(byteArrayOf(2), takenNs = 1L)
        val next = store.getAfter(fromSeq = first.seq, timeoutMs = 0L)
        assertTrue("重启后序号必须继续前进，不能回退", next != null && next.seq > first.seq)
    }

    @Test
    fun `latest frame wins when several are published`() {
        val store = LatestFrameStore()
        // 三个不同长度的字节数组：断言"最新那帧"时可以用长度区分
        store.set(byteArrayOf(1), takenNs = 1L)
        store.set(byteArrayOf(2, 2), takenNs = 2L)
        store.set(byteArrayOf(3, 3, 3), takenNs = 3L)

        val frame = store.getAfter(fromSeq = -1L, timeoutMs = 0L)
        assertEquals("只保留最新帧", 3, frame?.jpeg?.size)
        assertEquals(2L, frame?.seq)
        assertSame(frame, store.getAfter(fromSeq = 0L, timeoutMs = 0L))
    }
}
