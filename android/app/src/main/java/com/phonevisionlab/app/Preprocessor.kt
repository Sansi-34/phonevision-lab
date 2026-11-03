package com.phonevisionlab.app

import android.graphics.Bitmap
import android.graphics.Matrix
import kotlin.math.max
import kotlin.math.min
import kotlin.math.floor
import kotlin.math.round

/**
 * PhoneVision Lab — 预处理契约（与 PC 端 pvl_preprocess.py 逐字段对应）。
 *
 * 职责：把一帧相机画面按模型包 manifest 里声明的规则整理成模型输入张量。
 * 规则与 PC 端完全一致，否则训练准确率无法在手机上复现。
 *
 * 为什么这样设计：
 *   - 两边共用同一份 spec（JSON），导入模型时逐项比对，不匹配就明确拒绝，
 *     绝不"手机自己猜一套预处理"。
 *   - 颜色顺序：Camera2 的 YUV_420_888 可以直接拿到 RGB；本类要求调用方
 *     传入 RGB 顺序的 ByteArray/NV21 派生数据，或直接用 [bitmapToRgb] 转换。
 *   - 缩放：短边等比缩放到 input_size 再中心裁剪（保留构图，不拉伸），
 *     与 PC 端 resize_frame(center_crop=true) 语义一致。
 *   - 归一化：imagenet（默认，MobileNetV3 预训练权重必须）、unit、raw 三种。
 *
 * 初学者调试观察点：
 *   - 手机上预测明显不对：先比对 manifest 的 preprocess 与本类默认值是否一致。
 *   - 画面是反的：检查调用方是否处理了旋转/镜像（本类不做，属于相机层职责）。
 */
object PreprocessSpec {

    const val CONTRACT_VERSION = 1

    const val LAYOUT_NHWC = "NHWC"
    const val LAYOUT_NCHW = "NCHW"
    const val COLOR_RGB = "RGB"
    const val COLOR_BGR = "BGR"

    const val NORM_UNIT = "unit"
    const val NORM_IMAGENET = "imagenet"
    const val NORM_RAW = "raw"

    /** ImageNet 均值/标准差（按 RGB 顺序；与 PC 端默认值一致）。 */
    val IMAGENET_MEAN = floatArrayOf(0.485f, 0.456f, 0.406f)
    val IMAGENET_STD = floatArrayOf(0.229f, 0.224f, 0.225f)

    /**
     * 预处理配置（从 manifest.json 解析而来）。
     *
     * @param inputSize 模型期望的方形边长（像素）
     * @param layout 张量布局 NHWC/NCHW
     * @param colorOrder 颜色顺序 RGB/BGR
     * @param normalization 归一化方式 unit/imagenet/raw
     * @param centerCrop 是否中心裁剪（true=保留构图，false=拉伸）
     * @param contractVersion 契约版本，必须等于 CONTRACT_VERSION
     */
    data class Spec(
        val inputSize: Int = 224,
        val layout: String = LAYOUT_NHWC,
        val colorOrder: String = COLOR_RGB,
        val normalization: String = NORM_IMAGENET,
        val centerCrop: Boolean = true,
        val contractVersion: Int = CONTRACT_VERSION,
        val mean: List<Float> = IMAGENET_MEAN.toList(),
        val std: List<Float> = IMAGENET_STD.toList(),
    ) {
        /** 返回人类可读的问题列表；空列表表示合法。 */
        fun validate(): List<String> {
            val problems = mutableListOf<String>()
            if (inputSize !in 1..1024) problems += "inputSize 必须在 1..1024 之间"
            if (layout != LAYOUT_NHWC && layout != LAYOUT_NCHW) {
                problems += "layout 只能是 NHWC 或 NCHW"
            }
            if (colorOrder != COLOR_RGB && colorOrder != COLOR_BGR) {
                problems += "colorOrder 只能是 RGB 或 BGR"
            }
            if (normalization != NORM_UNIT && normalization != NORM_IMAGENET &&
                normalization != NORM_RAW
            ) {
                problems += "normalization 只能是 unit / imagenet / raw"
            }
            if (contractVersion != CONTRACT_VERSION) {
                problems += "预处理契约版本不匹配：模型包 v$contractVersion，本端支持 v$CONTRACT_VERSION"
            }
            if (mean.size != 3 || mean.any { !it.isFinite() }) problems += "mean 必须包含 3 个有限数值"
            if (std.size != 3 || std.any { !it.isFinite() || it == 0f }) {
                problems += "std 必须包含 3 个有限非零数值"
            }
            return problems
        }
    }
}

/**
 * 把 Bitmap 按 spec 整理成 float 输入缓冲（行主序，长度 = 1*size*size*3 或 NCHW）。
 *
 * 实现要点（必须与 PC 端一致）：
 *   1. 短边等比缩放到 inputSize：缩小用"区域平均"（每目标像素覆盖的源像素均值），
 *      放大用双线性；与 PC 端 _resize_area / _resize_bilinear 对应。
 *   2. 中心裁剪到 inputSize x inputSize。
 *   3. 颜色顺序：Android 默认给 RGB；spec 要求 BGR 时交换 R/B。
 *   4. 归一化在 float 域进行。
 *   5. 布局：NHWC 直接写；NCHW 按通道重排。
 */
class Preprocessor(private val spec: PreprocessSpec.Spec) {

    /** 输出缓冲的元素个数。 */
    val elementCount: Int = 1 * spec.inputSize * spec.inputSize * 3

    /** 复用缓冲（避免每帧分配；调用方必须保证同一时刻只有一个推理在用）。 */
    private val buffer = FloatArray(elementCount)

    /**
     * 处理一帧，返回内部复用缓冲（调用方用完才能再调用本方法）。
     *
     * @param bitmap 已按显示方向处理好旋转/镜像的画面（RGB 顺序由 Bitmap 保证）
     */
    fun process(bitmap: Bitmap): FloatArray {
        val size = spec.inputSize
        writePixels(resizePixels(bitmap, size), size)
        return buffer
    }

    /** Match the PC contract's area/bilinear sampling and center-crop rounding. */
    private fun resizePixels(source: Bitmap, size: Int): IntArray {
        val w = source.width
        val h = source.height
        if (w <= 0 || h <= 0) throw IllegalArgumentException("画面尺寸无效: ${w}x${h}")
        val pixels = IntArray(w * h)
        source.getPixels(pixels, 0, w, 0, 0, w, h)
        val scaledW: Int
        val scaledH: Int
        if (spec.centerCrop) {
            val scale = size.toDouble() / min(w, h)
            scaledW = max(1, round(w * scale).toInt())
            scaledH = max(1, round(h * scale).toInt())
        } else {
            scaledW = size
            scaledH = size
        }
        val cropLeft = max(0, (scaledW - size) / 2)
        val cropTop = max(0, (scaledH - size) / 2)
        val useArea = spec.centerCrop && (scaledW < w || scaledH < h)
        val xBounds = if (useArea) Array(size) { bounds(w, scaledW, it + cropLeft) } else null
        val yBounds = if (useArea) Array(size) { bounds(h, scaledH, it + cropTop) } else null
        val out = IntArray(size * size)
        for (y in 0 until size) {
            for (x in 0 until size) {
                val sx = x + cropLeft
                val sy = y + cropTop
                val rgb = if (useArea) {
                    areaPixel(pixels, w, xBounds!![x], yBounds!![y])
                } else {
                    bilinearPixel(pixels, w, h, scaledW, scaledH, sx, sy)
                }
                out[y * size + x] = rgb
            }
        }
        return out
    }

    private fun bounds(source: Int, target: Int, index: Int): Pair<Int, Int> {
        val scale = source.toDouble() / target
        val start = round(index * scale).toInt().coerceIn(0, source - 1)
        val end = (if (index == target - 1) source else round((index + 1) * scale).toInt())
            .coerceIn(start + 1, source)
        return Pair(start, end)
    }

    private fun areaPixel(pixels: IntArray, w: Int, xBounds: Pair<Int, Int>,
                          yBounds: Pair<Int, Int>): Int {
        val (x0, x1) = xBounds
        val (y0, y1) = yBounds
        var red = 0f
        var green = 0f
        var blue = 0f
        for (sx in x0 until x1) {
            var sumRed = 0
            var sumGreen = 0
            var sumBlue = 0
            for (sy in y0 until y1) {
                val p = pixels[sy * w + sx]
                sumRed += (p shr 16) and 255
                sumGreen += (p shr 8) and 255
                sumBlue += p and 255
            }
            red += sumRed.toFloat() / (y1 - y0)
            green += sumGreen.toFloat() / (y1 - y0)
            blue += sumBlue.toFloat() / (y1 - y0)
        }
        val r = (red / (x1 - x0) + 0.5f).toInt().coerceIn(0, 255)
        val g = (green / (x1 - x0) + 0.5f).toInt().coerceIn(0, 255)
        val b = (blue / (x1 - x0) + 0.5f).toInt().coerceIn(0, 255)
        return (255 shl 24) or (r shl 16) or (g shl 8) or b
    }

    private fun bilinearPixel(pixels: IntArray, w: Int, h: Int, dw: Int, dh: Int,
                              x: Int, y: Int): Int {
        val xf = ((x + 0.5) * w / dw - 0.5).coerceIn(0.0, (w - 1).toDouble())
        val yf = ((y + 0.5) * h / dh - 0.5).coerceIn(0.0, (h - 1).toDouble())
        val x0 = floor(xf).toInt()
        val y0 = floor(yf).toInt()
        val x1 = min(x0 + 1, w - 1)
        val y1 = min(y0 + 1, h - 1)
        val wx = (xf - x0).toFloat()
        val wy = (yf - y0).toFloat()
        fun channel(shift: Int): Int {
            val tl = (pixels[y0 * w + x0] shr shift) and 255
            val bl = (pixels[y1 * w + x0] shr shift) and 255
            val tr = (pixels[y0 * w + x1] shr shift) and 255
            val br = (pixels[y1 * w + x1] shr shift) and 255
            val left = tl * (1f - wy) + bl * wy
            val right = tr * (1f - wy) + br * wy
            return (left * (1f - wx) + right * wx + 0.5f).toInt().coerceIn(0, 255)
        }
        return (255 shl 24) or (channel(16) shl 16) or (channel(8) shl 8) or channel(0)
    }

    /** 把 size x size 的 RGB 像素写进 buffer（含颜色顺序/归一化/布局）。 */
    private fun writePixels(pixels: IntArray, size: Int) {

        val swapRB = spec.colorOrder == PreprocessSpec.COLOR_BGR
        val normalization = spec.normalization
        val mean = spec.mean
        val std = spec.std

        for (i in pixels.indices) {
            val p = pixels[i]
            var r = (p shr 16) and 0xFF
            var g = (p shr 8) and 0xFF
            var b = p and 0xFF
            if (swapRB) {
                val t = r
                r = b
                b = t
            }

            var fr: Float
            var fg: Float
            var fb: Float
            when (normalization) {
                PreprocessSpec.NORM_UNIT -> {
                    fr = r / 255f
                    fg = g / 255f
                    fb = b / 255f
                }
                PreprocessSpec.NORM_IMAGENET -> {
                    fr = (r / 255f - mean[0]) / std[0]
                    fg = (g / 255f - mean[1]) / std[1]
                    fb = (b / 255f - mean[2]) / std[2]
                }
                else -> { // raw
                    fr = r.toFloat()
                    fg = g.toFloat()
                    fb = b.toFloat()
                }
            }

            if (spec.layout == PreprocessSpec.LAYOUT_NHWC) {
                buffer[i * 3] = fr
                buffer[i * 3 + 1] = fg
                buffer[i * 3 + 2] = fb
            } else {
                // NCHW：通道平面连续
                val plane = size * size
                buffer[i] = fr
                buffer[plane + i] = fg
                buffer[plane * 2 + i] = fb
            }
        }
    }
}

/** 便捷函数：把 Bitmap 旋转/镜像后交给预处理器（相机层调用）。 */
fun Bitmap.rotated(degrees: Float, mirror: Boolean): Bitmap {
    if (degrees == 0f && !mirror) return this
    val matrix = Matrix()
    if (degrees != 0f) matrix.postRotate(degrees)
    if (mirror) matrix.postScale(-1f, 1f)
    return Bitmap.createBitmap(this, 0, 0, width, height, matrix, true)
}
