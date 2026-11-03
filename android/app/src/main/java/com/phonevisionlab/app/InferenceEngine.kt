package com.phonevisionlab.app

import android.graphics.Bitmap
import android.util.Log
import org.tensorflow.lite.Interpreter
import org.tensorflow.lite.DataType
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import kotlin.math.roundToInt

/**
 * PhoneVision Lab — 本机推理引擎（TFLite）。
 *
 * 职责：加载模型，把相机帧跑成分类结果，并记录可测量的性能数据。
 *
 * 为什么这样设计：
 *   - 只用 TFLite CPU：旧手机（minSdk 21）确定可用，不承诺 GPU/NNAPI 加速。
 *     加速委派需要真机验证，未验证前不启用（见 Config.USE_NNAPI）。
 *   - 性能数据分开记录：预处理、模型执行、后处理三段各自计时，
 *     不混成一个"推理耗时"，否则无法判断瓶颈在哪一段。
 *   - 用 [android.os.SystemClock.elapsedRealtimeNanos] 单调时钟测本机间隔，
 *     绝不拿手机时间戳与电脑时间戳相减（两端未同步，相减没有意义）。
 *   - 帧率用"最近 N 帧的完成时间差"算，不用计数/墙钟除法，避免低频抖动。
 *   - 线程安全：推理在调用方线程执行；本类内部用原子量做计数，
 *     多线程读统计不会读到撕裂数据。
 *
 * 初学者调试观察点：
 *   - 帧率远低于预期：看 model_ms（模型执行）是否占满整个周期。
 *   - 预处理很慢：说明 input_size 太大或中心裁剪路径在反复创建 Bitmap。
 *   - 结果不稳定：先确认预处理契约与训练时一致（manifest 的 preprocess）。
 */
class InferenceEngine(
    private val modelPath: String,
    val spec: PreprocessSpec.Spec,
    val labels: List<String>,
    val displayLabels: List<String>,
    private val numThreads: Int = Config.INFERENCE_THREADS,
) {
    companion object {
        private const val TAG = "InferenceEngine"

        /** 帧率统计窗口：最近这么多帧的间隔求平均。 */
        private const val FPS_WINDOW = 20
    }

    private var interpreter: Interpreter? = null
    private val preprocessor = Preprocessor(spec)
    private val outputBuffer: FloatArray = FloatArray(labels.size)
    private val inputTensor = ByteBuffer.allocateDirect(preprocessor.elementCount * 4)
        .order(ByteOrder.nativeOrder())
    private val outputTensor = ByteBuffer.allocateDirect(labels.size * 4)
        .order(ByteOrder.nativeOrder())

    /** 关闭标志：close 后所有 run 调用立即返回 null，不再触碰已释放的 interpreter。 */
    private val closed = AtomicBoolean(false)

    // ---- 统计（原子量，跨线程安全）----
    private val _completedFrames = AtomicLong(0)
    private val _droppedFrames = AtomicLong(0)
    private val _preprocessTotalMs = AtomicLong(0)
    private val _modelTotalMs = AtomicLong(0)
    private val _postprocessTotalMs = AtomicLong(0)
    private val _lastFrameIntervalMs = AtomicLong(0)
    private val _frameCountInWindow = AtomicLong(0)
    private val _fpsWindowStartNs = AtomicLong(0)

    /** 当前测得的推理帧率（完成帧/秒），未满一窗时为 0。 */
    @Volatile
    var measuredFps: Float = 0f
        private set

    init {
        try {
            val options = Interpreter.Options().apply {
                // TFLite 2.16 的 Options 用 setNumThreads(int)，不是 Kotlin 属性
                // 语法 threadCount = ...；写错会报 Unresolved reference。
                setNumThreads(numThreads.coerceIn(1, 8))
                // 明确不使用 NNAPI/GPU：未在真机验证前不启用（见 Config.USE_NNAPI）。
                setUseNNAPI(Config.USE_NNAPI)
            }
            val created = Interpreter(File(modelPath), options)
            try {
                val expectedInput = if (spec.layout == PreprocessSpec.LAYOUT_NHWC) {
                    intArrayOf(1, spec.inputSize, spec.inputSize, 3)
                } else {
                    intArrayOf(1, 3, spec.inputSize, spec.inputSize)
                }
                require(created.inputTensorCount == 1 && created.outputTensorCount == 1) {
                    "只支持一个输入和一个输出"
                }
                val actualInput = created.getInputTensor(0)
                val actualOutput = created.getOutputTensor(0)
                require(actualInput.dataType() == DataType.FLOAT32 &&
                    actualInput.shape().contentEquals(expectedInput)) {
                    "模型输入类型或形状不匹配: ${actualInput.dataType()} ${actualInput.shape().contentToString()}"
                }
                require(actualOutput.dataType() == DataType.FLOAT32 &&
                    actualOutput.shape().contentEquals(intArrayOf(1, labels.size))) {
                    "模型输出类型或形状不匹配: ${actualOutput.dataType()} ${actualOutput.shape().contentToString()}"
                }
                interpreter = created
            } catch (e: Exception) {
                created.close()
                throw e
            }
            Log.i(TAG, "模型已加载: $modelPath 输入=${spec.inputSize}px " +
                "${spec.colorOrder} ${spec.normalization} 线程=$numThreads")
        } catch (e: Exception) {
            Log.e(TAG, "模型加载失败", e)
            throw IllegalStateException("模型加载失败: ${e.message}", e)
        }
    }

    /** 一次推理的结果。 */
    data class Prediction(
        val topIndex: Int,
        val topLabel: String,
        val topDisplayLabel: String,
        val confidence: Float,
        val preprocessMs: Float,
        val modelMs: Float,
        val postprocessMs: Float,
        val totalMs: Float,
        val timestampNs: Long,
    )

    /**
     * 对一帧执行推理。
     *
     * @param bitmap 已按显示方向处理好旋转/镜像的画面
     * @return 预测结果；引擎已关闭时返回 null
     */
    @Synchronized
    fun run(bitmap: Bitmap): Prediction? {
        if (closed.get()) return null
        val interp = interpreter ?: return null

        val t0 = SystemClock_elapsedRealtimeNanos()

        // 1) 预处理（复用内部缓冲，不每帧分配）
        val input = try {
            preprocessor.process(bitmap)
        } catch (e: Exception) {
            Log.w(TAG, "预处理失败", e)
            _droppedFrames.incrementAndGet()
            return null
        }
        val t1 = SystemClock_elapsedRealtimeNanos()

        // 2) 模型执行
        val ok = try {
            inputTensor.clear()
            inputTensor.asFloatBuffer().put(input)
            outputTensor.clear()
            interp.run(inputTensor, outputTensor)
            outputTensor.rewind()
            outputTensor.asFloatBuffer().get(outputBuffer)
            true
        } catch (e: Exception) {
            Log.e(TAG, "推理执行失败", e)
            _droppedFrames.incrementAndGet()
            false
        }
        if (!ok) return null
        val t2 = SystemClock_elapsedRealtimeNanos()

        // 3) 后处理：取 Top-1
        var bestIdx = 0
        var bestVal = Float.NEGATIVE_INFINITY
        for (i in outputBuffer.indices) {
            if (outputBuffer[i] > bestVal) {
                bestVal = outputBuffer[i]
                bestIdx = i
            }
        }
        val t3 = SystemClock_elapsedRealtimeNanos()

        // ---- 统计 ----
        _completedFrames.incrementAndGet()
        _preprocessTotalMs.addAndGet(toMs(t1 - t0))
        _modelTotalMs.addAndGet(toMs(t2 - t1))
        _postprocessTotalMs.addAndGet(toMs(t3 - t2))
        updateFps(t3)

        val preMs = (t1 - t0) / 1_000_000f
        val modelMs = (t2 - t1) / 1_000_000f
        val postMs = (t3 - t2) / 1_000_000f

        return Prediction(
            topIndex = bestIdx,
            topLabel = labels.getOrElse(bestIdx) { "?" },
            topDisplayLabel = displayLabels.getOrElse(bestIdx) { labels.getOrElse(bestIdx) { "?" } },
            confidence = bestVal,
            preprocessMs = preMs,
            modelMs = modelMs,
            postprocessMs = postMs,
            totalMs = preMs + modelMs + postMs,
            timestampNs = t3,
        )
    }

    /** 记录一帧"因限频被主动丢弃"（不是失败）。 */
    fun markFrameSkipped() {
        _droppedFrames.incrementAndGet()
    }

    // ---- 统计读取 ----

    fun completedFrames(): Long = _completedFrames.get()
    fun droppedFrames(): Long = _droppedFrames.get()

    /** 平均预处理耗时（毫秒）；无样本时为 0。 */
    fun averagePreprocessMs(): Float =
        _preprocessTotalMs.get().toFloat() / maxOf(1L, _completedFrames.get())

    /** 平均模型执行耗时（毫秒）；无样本时为 0。 */
    fun averageModelMs(): Float =
        _modelTotalMs.get().toFloat() / maxOf(1L, _completedFrames.get())

    /** 平均后处理耗时（毫秒）；无样本时为 0。 */
    fun averagePostprocessMs(): Float =
        _postprocessTotalMs.get().toFloat() / maxOf(1L, _completedFrames.get())

    /** 最近一帧的间隔（毫秒），用于观察抖动。 */
    fun lastFrameIntervalMs(): Long = _lastFrameIntervalMs.get()

    fun resetStats() {
        _completedFrames.set(0)
        _droppedFrames.set(0)
        _preprocessTotalMs.set(0)
        _modelTotalMs.set(0)
        _postprocessTotalMs.set(0)
        _lastFrameIntervalMs.set(0)
        _frameCountInWindow.set(0)
        _fpsWindowStartNs.set(0)
        measuredFps = 0f
    }

    /**
     * 用"最近 FPS_WINDOW 帧的完成时间差"更新帧率。
     *
     * 不用"计数/墙钟"：低频下窗口切换会让数字跳变。
     */
    private fun updateFps(frameEndNs: Long) {
        val start = _fpsWindowStartNs.get()
        if (start == 0L) {
            _fpsWindowStartNs.set(frameEndNs)
            _frameCountInWindow.set(0)
            return
        }
        val count = _frameCountInWindow.incrementAndGet()
        if (count >= FPS_WINDOW) {
            val elapsedNs = frameEndNs - start
            if (elapsedNs > 0) {
                measuredFps = (count * 1_000_000_000f) / elapsedNs
                _lastFrameIntervalMs.set(elapsedNs / count / 1_000_000)
            }
            _fpsWindowStartNs.set(frameEndNs)
            _frameCountInWindow.set(0)
        }
    }

    /** 释放 interpreter 与复用缓冲。幂等，可安全重复调用。 */
    @Synchronized
    fun close() {
        if (closed.getAndSet(true)) return
        try {
            interpreter?.close()
        } catch (e: Exception) {
            Log.w(TAG, "close interpreter failed", e)
        }
        interpreter = null
        Log.i(TAG, "推理引擎已释放")
    }

    // ---- 内部工具 ----

    private fun SystemClock_elapsedRealtimeNanos(): Long =
        android.os.SystemClock.elapsedRealtimeNanos()

    /** 纳秒差转毫秒（四舍五入）。 */
    private fun toMs(deltaNs: Long): Long =
        (deltaNs / 1_000_000.0).roundToInt().toLong()
}
