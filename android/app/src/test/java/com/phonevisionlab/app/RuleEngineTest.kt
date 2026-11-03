package com.phonevisionlab.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * RuleEngine 的 JVM 单元测试（无 Android 依赖，直接跑在 testDebugUnitTest）。
 *
 * 覆盖的是"会不会误触发硬件动作"这条线：
 *   1. 连续确认：不足 confirmCount 帧不得触发；
 *   2. 目标消失：非目标类别必须打断连续计数；
 *   3. 滞回：已触发状态下，置信度落在 exit..trigger 之间不得关闭；
 *   4. 释放：连续 releaseFrames 帧不满足才关闭，且只关闭一次；
 *   5. 冷却：冷却期内不得再次触发（但"从未动作"不能拦第一次）；
 *   6. reset：停止自动控制后不残留半触发状态。
 */
class RuleEngineTest {

    private fun prediction(
        label: String = "target",
        confidence: Float = 0.9f,
    ) = InferenceEngine.Prediction(
        topIndex = 0,
        topLabel = label,
        topDisplayLabel = label,
        confidence = confidence,
        preprocessMs = 1f,
        modelMs = 2f,
        postprocessMs = 1f,
        totalMs = 4f,
        timestampNs = 0L,
    )

    private fun engine(
        confirmCount: Int = 3,
        trigger: Float = 0.75f,
        exit: Float = 0.45f,
        releaseFrames: Int = 2,
        cooldownMs: Long = 1000L,
    ) = RuleEngine(
        RuleEngine.RuleConfig(
            targetClass = "target",
            triggerConfidence = trigger,
            confirmCount = confirmCount,
            exitConfidence = exit,
            releaseFrames = releaseFrames,
            cooldownMs = cooldownMs,
        )
    )

    @Test
    fun `needs confirmCount consecutive hits before turning on`() {
        val engine = engine(confirmCount = 3)
        assertFalse(engine.update(prediction(), nowMs = 0).shouldTurnOn)
        assertFalse(engine.update(prediction(), nowMs = 10).shouldTurnOn)
        val third = engine.update(prediction(), nowMs = 20)
        assertTrue("第 3 帧应触发", third.shouldTurnOn)
        assertTrue(third.state)
    }

    @Test
    fun `non-target frame resets the confirm streak`() {
        val engine = engine(confirmCount = 3)
        engine.update(prediction(), nowMs = 0)
        engine.update(prediction(), nowMs = 10)
        engine.update(prediction(label = "other", confidence = 0.99f), nowMs = 20)
        assertFalse(
            "中间出现其它类别后必须重新累计",
            engine.update(prediction(), nowMs = 30).shouldTurnOn
        )
    }

    @Test
    fun `low confidence does not confirm`() {
        val engine = engine(confirmCount = 2, trigger = 0.75f)
        engine.update(prediction(confidence = 0.74f), nowMs = 0)
        assertFalse(engine.update(prediction(confidence = 0.74f), nowMs = 10).shouldTurnOn)
    }

    @Test
    fun `hysteresis keeps state on while confidence stays above exit threshold`() {
        val engine = engine(confirmCount = 1, trigger = 0.75f, exit = 0.45f)
        assertTrue(engine.update(prediction(), nowMs = 0).shouldTurnOn)
        // 0.6 低于触发阈值但高于退出阈值：滞回区间，不能关
        repeat(5) { i ->
            val out = engine.update(prediction(confidence = 0.6f), nowMs = 100L + i)
            assertFalse("滞回区间不应关闭", out.shouldTurnOff)
            assertTrue(out.state)
        }
    }

    @Test
    fun `release needs releaseFrames consecutive misses and fires only once`() {
        // cooldownMs = 0：本用例只验证"连续 N 帧"的计数，不叠加冷却因素
        val engine = engine(confirmCount = 1, releaseFrames = 3, cooldownMs = 0L)
        assertTrue(engine.update(prediction(), nowMs = 0).shouldTurnOn)
        assertFalse(engine.update(prediction(label = "other"), nowMs = 10).shouldTurnOff)
        assertFalse(engine.update(prediction(label = "other"), nowMs = 20).shouldTurnOff)
        assertTrue(
            "第 3 帧不满足才关闭",
            engine.update(prediction(label = "other"), nowMs = 30).shouldTurnOff
        )
        assertFalse(
            "关闭后不应重复发关闭指令",
            engine.update(prediction(label = "other"), nowMs = 40).shouldTurnOff
        )
    }

    @Test
    fun `cooldown blocks a second action but never the first`() {
        val engine = engine(confirmCount = 1, releaseFrames = 1, cooldownMs = 1000L)
        // 第一次动作不受冷却限制（lastActionAtMs 为 null）
        assertTrue(engine.update(prediction(), nowMs = 0).shouldTurnOn)
        // 立刻关闭：仍在冷却期，不允许
        assertFalse(engine.update(prediction(label = "other"), nowMs = 100).shouldTurnOff)
        // 冷却期过后允许关闭
        assertTrue(engine.update(prediction(label = "other"), nowMs = 1000).shouldTurnOff)
    }

    @Test
    fun `reset clears a half-confirmed streak`() {
        val engine = engine(confirmCount = 3)
        engine.update(prediction(), nowMs = 0)
        engine.update(prediction(), nowMs = 10)
        engine.reset()
        assertFalse(engine.currentState())
        assertFalse(
            "reset 后不得带着旧计数触发",
            engine.update(prediction(), nowMs = 20).shouldTurnOn
        )
    }

    @Test
    fun `config validation rejects exit threshold above trigger`() {
        val problems = RuleEngine.RuleConfig(
            targetClass = "target",
            triggerConfidence = 0.5f,
            exitConfidence = 0.6f,
        ).validate()
        assertTrue(problems.any { it.contains("退出置信度") })
    }

    @Test
    fun `config validation rejects blank target class`() {
        val problems = RuleEngine.RuleConfig(targetClass = "   ").validate()
        assertTrue(problems.any { it.contains("目标类别") })
    }

    @Test
    fun `default config is valid`() {
        assertEquals(emptyList<String>(), RuleEngine.RuleConfig(targetClass = "target").validate())
    }
}
