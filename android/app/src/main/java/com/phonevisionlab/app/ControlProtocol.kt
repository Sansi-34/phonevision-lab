package com.phonevisionlab.app

/**
 * PhoneVision Lab — 视觉与硬件交互的共享协议定义（手机端 / 控制器固件共用）。
 *
 * 职责：定义"手机 -> 控制器"的命令格式与"控制器 -> 手机"的反馈格式，
 * 以及连接状态、重试规则。两侧实现必须严格遵守，否则无法互操作。
 *
 * 为什么这样设计：
 *   - 通信走局域网 HTTP（不依赖公网/云）：控制器接入同一 Wi-Fi 后暴露
 *     HTTP 接口，手机直接 POST 命令。这是"手机直连控制器"的最小真实闭环。
 *   - 命令带 requestId：控制器回显同一个 requestId，手机才能把
 *     "已发送"和"已确认"对应起来，也才能做重复命令去重。
 *   - 明确区分四态：已发送 / 已接收 / 已执行 / 超时失败。
 *     设备只确认"收到了"时，界面只能显示"已接收"，绝不能显示"执行成功"。
 *   - 重连后不重放过期命令：手机不缓存"待发送"的命令队列，
 *     重连意味着重新开始，由用户手动再次触发（避免断线期间积压的动作突然执行）。
 *
 * 初学者调试观察点：
 *   - LED 不动但显示"已发送"：看控制器是否回了 ack，没有就是超时。
 *   - 动作重复执行：确认手机端在 send 时按 requestId 去重了。
 */
object ControlProtocol {

    /** 协议版本；升级格式时递增，两侧必须一致。 */
    const val VERSION = 1

    /** 默认控制器 HTTP 端口（与推流端口分开，避免冲突）。 */
    const val DEFAULT_PORT = 8081

    // ---- 动作类型 ----

    const val ACTION_LED_ON = "led_on"
    const val ACTION_LED_OFF = "led_off"
    const val ACTION_SET_LED = "set_led"      // 带 brightness 参数
    const val ACTION_SERVO_SET = "servo_set"  // 带 angle 参数
    const val ACTION_STOP = "stop"            // 立即停止所有执行器
    const val ACTION_STATUS = "status"        // 只读查询

    /**
     * 允许重试的动作。
     *
     * LED 开关是幂等的（重复执行结果相同），可以有限重试。
     * 舵机/电机等运动动作绝不自动重试：重复执行会让机构来回运动，
     * 必须由用户手动再次触发。
     */
    val RETRYABLE_ACTIONS = setOf(ACTION_LED_ON, ACTION_LED_OFF, ACTION_SET_LED)

    /** 全部已知动作（用于界面下拉与校验）。 */
    val ALL_ACTIONS = listOf(
        ACTION_LED_ON, ACTION_LED_OFF, ACTION_SET_LED,
        ACTION_SERVO_SET, ACTION_STOP, ACTION_STATUS,
    )

    // ---- 命令 ----

    /**
     * 一条控制命令（序列化成 POST body）。
     *
     * @param requestId 全局唯一请求编号（手机生成，控制器回显）
     * @param target 目标设备标识（默认 "led0"；多执行器时区分）
     * @param action 动作类型，见 ACTION_*
     * @param params 动作参数（如 brightness 0-255、angle 0-180）
     */
    data class Command(
        val requestId: String,
        val target: String,
        val action: String,
        val params: Map<String, Any> = emptyMap(),
        val protocolVersion: Int = VERSION,
    ) {
        fun toJson(): String {
            val sb = StringBuilder()
            sb.append("{")
            sb.append("\"v\":").append(protocolVersion).append(",")
            sb.append("\"requestId\":\"").append(escape(requestId)).append("\",")
            sb.append("\"target\":\"").append(escape(target)).append("\",")
            sb.append("\"action\":\"").append(escape(action)).append("\"")
            if (params.isNotEmpty()) {
                sb.append(",\"params\":{")
                var first = true
                for ((k, v) in params) {
                    if (!first) sb.append(",")
                    first = false
                    sb.append("\"").append(escape(k)).append("\":")
                    when (v) {
                        is Number, is Boolean -> sb.append(v.toString())
                        else -> sb.append("\"").append(escape(v.toString())).append("\"")
                    }
                }
                sb.append("}")
            }
            sb.append("}")
            return sb.toString()
        }

        private fun escape(s: String): String =
            s.replace("\\", "\\\\").replace("\"", "\\\"")
    }

    // ---- 反馈 ----

    /** 命令状态枚举。顺序即严重程度。 */
    enum class CommandStatus {
        /** 手机已发出，尚未收到任何回应 */
        SENT,

        /** 控制器确认收到了命令 */
        RECEIVED,

        /** 控制器确认已执行（仅当设备能确认实际动作完成时） */
        EXECUTED,

        /** 超时或失败 */
        FAILED,
    }

    /**
     * 控制器的反馈。
     *
     * @param requestId 回显的命令编号
     * @param status 命令状态
     * @param executedAtMs 控制器侧执行完成时间（单调毫秒，仅设备支持时有意义）
     * @param message 人类可读说明（错误原因等）
     */
    data class Feedback(
        val requestId: String,
        val status: CommandStatus,
        val executedAtMs: Long? = null,
        val message: String = "",
    ) {
        companion object {
            fun fromJson(json: String): Feedback? {
                return try {
                    val o = org.json.JSONObject(json)
                    val status = when (o.optString("status", "").lowercase()) {
                        "received" -> CommandStatus.RECEIVED
                        "executed" -> CommandStatus.EXECUTED
                        "failed", "error" -> CommandStatus.FAILED
                        else -> return null
                    }
                    Feedback(
                        requestId = o.optString("requestId", ""),
                        status = status,
                        executedAtMs = if (o.has("executedAtMs")) {
                            o.optLong("executedAtMs")
                        } else {
                            null
                        },
                        message = o.optString("message", ""),
                    )
                } catch (e: Exception) {
                    null
                }
            }
        }
    }

    /** 连接状态（界面据此显示设备在线/离线）。 */
    enum class LinkState {
        DISCONNECTED,
        CONNECTING,
        CONNECTED,
        ERROR,
    }
}
