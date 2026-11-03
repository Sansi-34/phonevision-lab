package com.phonevisionlab.app

import kotlin.math.max

/**
 * PhoneVision Lab — 规则引擎（视觉结果 -> 是否产生硬件动作）。
 *
 * 职责：把"模型每帧输出的类别+置信度"变成"稳定的开关意图"，防止模型输出
 * 波动造成硬件频繁切换。
 *
 * 为什么这样设计：
 *   - 纯逻辑、无 Android 依赖、无网络：可以离线单元测试，也可以在 PC 端
 *     用同一套规则做模拟验证（两边规则一致才可信）。
 *   - 三重稳定机制：
 *       1. 连续确认：目标类别连续 N 帧置信度都超过阈值才认为"真的出现了"，
 *          单帧误识别不会触发。
 *       2. 滞回（hysteresis）：开启用较高阈值，关闭用较低阈值，
 *          避免在阈值附近反复横跳。
 *       3. 冷却：一次动作后至少间隔 cooldownMs 才允许下一次动作，
 *          即使中途抖动也不重新触发。
 *   - 只在"控制状态变化"时输出动作指令，绝不逐帧重复发送。
 *
 * 初学者调试观察点：
 *   - LED 频繁开关：调高 trigger_confidence 或 confirm_count。
 *   - 目标已经不在画面里 LED 还不灭：检查 release_frames 是否太大，
 *     或 exit_confidence 是否低于模型给非目标类的置信度。
 */
class RuleEngine(private val config: RuleConfig) {

    /**
     * 规则配置（界面可调，持久化在 SharedPreferences）。
     *
     * @param targetClass 目标类别名（来自模型标签）
     * @param triggerConfidence 触发阈值：连续确认帧的置信度需 >= 此值
     * @param confirmCount 连续确认帧数
     * @param exitConfidence 退出阈值：置信度低于此值视为"目标消失"（滞回）
     * @param releaseFrames 连续多少帧不满足触发条件才认为目标消失
     * @param cooldownMs 动作冷却时间（毫秒）
     * @param onAction 触发时执行的动作（默认 LED 开）
     * @param offAction 退出时执行的动作（默认 LED 关）
     * @param target 目标设备标识
     */
    data class RuleConfig(
        val targetClass: String,
        val triggerConfidence: Float = 0.75f,
        val confirmCount: Int = 3,
        val exitConfidence: Float = 0.45f,
        val releaseFrames: Int = 5,
        val cooldownMs: Long = 2000L,
        val onAction: String = ControlProtocol.ACTION_LED_ON,
        val offAction: String = ControlProtocol.ACTION_LED_OFF,
        val target: String = "led0",
    ) {
        fun validate(): List<String> {
            val problems = mutableListOf<String>()
            if (targetClass.isBlank()) problems += "目标类别不能为空"
            if (triggerConfidence <= 0f || triggerConfidence > 1f) {
                problems += "触发置信度必须在 (0, 1] 内"
            }
            if (exitConfidence < 0f || exitConfidence >= triggerConfidence) {
                problems += "退出置信度必须小于触发置信度（否则没有滞回效果）"
            }
            if (confirmCount < 1) problems += "连续确认次数至少为 1"
            if (releaseFrames < 1) problems += "退出帧数至少为 1"
            if (cooldownMs < 0) problems += "冷却时间不能为负"
            return problems
        }
    }

    /** 规则引擎的内部状态（可变，随推理结果更新）。 */
    private var state: Boolean = false          // 当前是否处于"已触发"状态
    private var confirmStreak: Int = 0          // 连续满足触发条件的帧数
    private var releaseStreak: Int = 0          // 连续不满足触发条件的帧数
    private var lastActionAtMs: Long? = null    // 上次动作时间（单调时钟）；null=从未动作
    private var lastOutput: RuleOutput = RuleOutput(state = false)

    /** 规则判定结果。 */
    data class RuleOutput(
        /** 当前稳定状态：true=目标已确认出现，false=目标已确认消失 */
        val state: Boolean,
        /** 是否需要发送"开启"动作（仅在状态从 false -> true 时一次） */
        val shouldTurnOn: Boolean = false,
        /** 是否需要发送"关闭"动作（仅在状态从 true -> false 时一次） */
        val shouldTurnOff: Boolean = false,
        /** 连续确认帧数（界面可显示，便于调参） */
        val confirmStreak: Int = 0,
        /** 距上次动作过去的毫秒数 */
        val sinceLastActionMs: Long = 0L,
    )

    /** 当前稳定状态。 */
    fun currentState(): Boolean = state

    /** 最近一次判定输出（界面显示用）。 */
    fun lastOutput(): RuleOutput = lastOutput

    /**
     * 是否已过冷却期。
     *
     * 从未动作过（lastActionAtMs == null）时视为"已冷却"：冷却是用来防止
     * "动作后立刻反复动作"的，不该拦住第一次触发。
     */
    private fun cooledDown(nowMs: Long): Boolean {
        val last = lastActionAtMs ?: return true
        return (nowMs - last) >= config.cooldownMs
    }

    /**
     * 喂入一次推理结果，返回本次判定。
     *
     * @param prediction 推理结果（含 topLabel 与 confidence）
     * @param nowMs 单调时钟毫秒（SystemClock.elapsedRealtime）
     */
    fun update(
        prediction: InferenceEngine.Prediction,
        nowMs: Long,
    ): RuleOutput {
        val isTarget = prediction.topLabel == config.targetClass
        val aboveTrigger = isTarget && prediction.confidence >= config.triggerConfidence
        // 滞回：已触发状态下，只要还没低于 exitConfidence 就继续认为"还在"
        val stillThere = isTarget && prediction.confidence >= config.exitConfidence

        if (!state) {
            // ---- 未触发状态：等待连续确认 ----
            confirmStreak = if (aboveTrigger) confirmStreak + 1 else 0
            releaseStreak = 0
            val ready = confirmStreak >= config.confirmCount
            val cooledDown = cooledDown(nowMs)
            val turnOn = ready && cooledDown
            if (turnOn) {
                state = true
                lastActionAtMs = nowMs
                confirmStreak = 0
            }
            val last = lastActionAtMs
            lastOutput = RuleOutput(
                state = state,
                shouldTurnOn = turnOn,
                confirmStreak = confirmStreak,
                sinceLastActionMs = if (last == null) 0L else max(0L, nowMs - last),
            )
        } else {
            // ---- 已触发状态：等待目标持续消失 ----
            releaseStreak = if (!stillThere) releaseStreak + 1 else 0
            confirmStreak = 0
            val shouldRelease = releaseStreak >= config.releaseFrames
            val cooledDown = cooledDown(nowMs)
            val turnOff = shouldRelease && cooledDown
            if (turnOff) {
                state = false
                lastActionAtMs = nowMs
                releaseStreak = 0
            }
            val last = lastActionAtMs
            lastOutput = RuleOutput(
                state = state,
                shouldTurnOff = turnOff,
                confirmStreak = 0,
                sinceLastActionMs = if (last == null) 0L else max(0L, nowMs - last),
            )
        }
        return lastOutput
    }

    /** 复位规则状态（停止自动控制时调用，避免残留半触发状态）。 */
    fun reset() {
        state = false
        confirmStreak = 0
        releaseStreak = 0
        lastActionAtMs = null
        lastOutput = RuleOutput(state = false)
    }
}
