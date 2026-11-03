package com.phonevisionlab.app

import android.content.Context
import android.util.Log
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.util.zip.ZipInputStream

/**
 * PhoneVision Lab — 模型包导入与校验。
 *
 * 职责：解析用户通过系统文件选择器选中的 .pvlmodel.zip，校验完整性与兼容性，
 * 通过后把模型文件落到 App 私有目录，供重启后继续使用。
 *
 * 为什么这样设计：
 *   - 模型包必须自描述：manifest.json 里带输入/输出/预处理/训练参数/兼容信息。
 *     导入时逐项校验，任何不匹配都给出明确原因并拒绝，绝不让 App 崩溃或
 *     "看起来导入了实际跑不起来"。
 *   - 完整性：必需文件缺失、manifest 解析失败、tflite 文件为空/过小都判失败。
 *   - 落盘位置用 App 的 filesDir（无需额外权限，卸载即清理），
 *     并记录已导入模型列表，重启后仍可选择。
 *   - 不做远程下载、不做账号、不联网：完全本地导入。
 *
 * 初学者调试观察点：
 *   - 导入被拒：看返回的 [ImportResult.error]，里面写明了是哪一项不匹配。
 *   - 重启后模型没了：确认走的是 importFromZip（会写 manifest 列表），
 *     而不是只把 tflite 拷进去。
 */
object ModelPackage {

    private const val TAG = "ModelPackage"

    /** 模型包格式版本（与 PC 端 pvl_export.MODEL_PACKAGE_FORMAT_VERSION 一致）。 */
    const val FORMAT_VERSION = 1

    /** 模型包内必需文件。 */
    private val REQUIRED_ENTRIES = setOf(
        "model.tflite", "manifest.json", "labels.json"
    )

    /** tflite 文件的最小字节数（小于这个值基本不是有效模型）。 */
    private const val MIN_TFLITE_BYTES = 1024
    const val MAX_ARCHIVE_BYTES = 80L * 1024 * 1024
    private const val MAX_MODEL_BYTES = 64 * 1024 * 1024
    private const val MAX_METADATA_BYTES = 1024 * 1024
    private const val MAX_ENTRIES = 16

    /** 已导入模型在 filesDir 下的子目录。 */
    private const val MODELS_SUBDIR = "models"

    /** 记录已导入模型的清单文件名。 */
    private const val INDEX_FILE = "imported-models.json"

    /** 一个已导入模型的元数据（界面据此显示与选择）。 */
    data class ImportedModel(
        val id: String,
        val displayName: String,
        val modelFile: String,
        val manifestFile: String,
        val labelsFile: String,
        val consistencyFile: String?,
        val importedAt: Long,
    )

    /** 导入结果：成功带模型元数据；失败带明确原因。 */
    sealed class ImportResult {
        data class Success(val model: ImportedModel) : ImportResult()
        data class Failure(val error: String) : ImportResult()
    }

    /** 模型包的完整内容（导入校验后供推理层使用）。 */
    data class LoadedModel(
        val id: String,
        val displayName: String,
        val tflitePath: String,
        val spec: PreprocessSpec.Spec,
        val labels: List<String>,
        val displayLabels: List<String>,
        val consistencyMaxAbsError: Double?,
        val consistencyTop1Agreement: Double?,
    )

    // =====================================================================
    // 导入
    // =====================================================================

    /**
     * 从用户选中的 zip 导入模型。
     *
     * @param context 用于定位 filesDir
     * @param zipPath 系统文件选择器返回的临时可读路径
     * @param displayNameOverride 用户指定的显示名（空则用 manifest/文件名）
     */
    fun importFromZip(context: Context, zipPath: String,
                      displayNameOverride: String = ""): ImportResult {
        val workDir = File(context.cacheDir, "model-import-${System.nanoTime()}")
        try {
            workDir.mkdirs()
            // 1) 解压
            val extracted = extract(zipPath, workDir)
                ?: return ImportResult.Failure("无法读取模型包：$zipPath")

            // 2) 必需文件检查
            val missing = REQUIRED_ENTRIES - extracted.keys
            if (missing.isNotEmpty()) {
                return ImportResult.Failure(
                    "模型包缺少必要文件: ${missing.sorted().joinToString(", ")}")
            }

            // 3) manifest 解析与校验
            val manifestText = extracted.readText("manifest.json")
            val manifest = try {
                JSONObject(manifestText)
            } catch (e: Exception) {
                return ImportResult.Failure("manifest.json 不是合法 JSON: ${e.message}")
            }

            val formatVersion = manifest.optInt("format_version", -1)
            if (formatVersion != FORMAT_VERSION) {
                return ImportResult.Failure(
                    "模型包格式版本不兼容：包为 v$formatVersion，本 App 支持 v$FORMAT_VERSION")
            }

            val modelObj = manifest.optJSONObject("model")
                ?: return ImportResult.Failure("manifest 缺少 model 段")
            val tfliteName = modelObj.optString("file", "model.tflite")
            if (tfliteName != "model.tflite") {
                return ImportResult.Failure(
                    "manifest 声明的模型文件名不受支持: $tfliteName（只支持 model.tflite）")
            }

            val inputObj = modelObj.optJSONObject("input")
                ?: return ImportResult.Failure("manifest 缺少 model.input 段")
            val outputObj = modelObj.optJSONObject("output")
                ?: return ImportResult.Failure("manifest 缺少 model.output 段")

            // 输入形状必须是 [1, H, W, 3] 且与预处理声明的尺寸一致
            val shape = inputObj.optJSONArray("shape")
            if (shape == null || shape.length() != 4) {
                return ImportResult.Failure("manifest 的 model.input.shape 不完整")
            }
            if (shape.optInt(0, -1) != 1 || shape.optInt(3, -1) != 3) {
                return ImportResult.Failure(
                    "只支持单张 3 通道输入（实际 shape=${shape.toString()}）")
            }

            // 预处理 spec
            val preObj = manifest.optJSONObject("preprocess")
                ?: return ImportResult.Failure("manifest 缺少 preprocess 段")
            val spec = PreprocessSpec.Spec(
                inputSize = preObj.optInt("input_size", 0),
                layout = preObj.optString("layout", PreprocessSpec.LAYOUT_NHWC),
                colorOrder = preObj.optString("color_order", PreprocessSpec.COLOR_RGB),
                normalization = preObj.optString(
                    "normalization", PreprocessSpec.NORM_IMAGENET),
                centerCrop = preObj.optBoolean("center_crop", true),
                contractVersion = preObj.optInt("contract_version", -1),
                mean = readVector(preObj, "mean", PreprocessSpec.IMAGENET_MEAN),
                std = readVector(preObj, "std", PreprocessSpec.IMAGENET_STD),
            )
            val specProblems = spec.validate()
            if (specProblems.isNotEmpty()) {
                return ImportResult.Failure(
                    "模型预处理配置不兼容：" + specProblems.joinToString("；"))
            }
            if (spec.layout != PreprocessSpec.LAYOUT_NHWC) {
                return ImportResult.Failure("当前模型包格式只支持 NHWC 输入布局")
            }
            // spec 声明的尺寸必须与 model.input.shape 一致
            if (shape.optInt(1, -1) != spec.inputSize ||
                shape.optInt(2, -1) != spec.inputSize
            ) {
                return ImportResult.Failure(
                    "model.input.shape(${shape.optInt(1)}x${shape.optInt(2)}) 与 " +
                        "preprocess.input_size(${spec.inputSize}) 不一致")
            }

            // 输出解释：必须是分类概率
            val interpretation = outputObj.optString("interpretation", "")
            if (interpretation.isBlank()) {
                return ImportResult.Failure("manifest 缺少 model.output.interpretation")
            }

            // 标签
            val labelsText = extracted.readText("labels.json")
            val labelsObj = try {
                JSONObject(labelsText)
            } catch (e: Exception) {
                return ImportResult.Failure("labels.json 不是合法 JSON: ${e.message}")
            }
            val indexToName = labelsObj.optJSONObject("index_to_name")
                ?: return ImportResult.Failure("labels.json 缺少 index_to_name")
            val count = labelsObj.optInt("count", indexToName.length())
            if (count < 2) {
                return ImportResult.Failure("模型至少需要 2 个类别（实际 $count）")
            }
            val labels = ArrayList<String>(count)
            val displayLabels = ArrayList<String>(count)
            val indexToDisplay = labelsObj.optJSONObject("index_to_display")
            for (i in 0 until count) {
                val name = indexToName.optString(i.toString(), "")
                if (name.isBlank()) {
                    return ImportResult.Failure("labels.json 缺少索引 $i 的类别名")
                }
                labels += name
                displayLabels += indexToDisplay?.optString(i.toString(), name) ?: name
            }
            // 输出类别数必须与标签数一致
            val outShape = outputObj.optJSONArray("shape")
            val outClasses = outShape?.optInt(outShape.length() - 1, -1) ?: -1
            if (outClasses > 0 && outClasses != count) {
                return ImportResult.Failure(
                    "模型输出类别数 $outClasses 与标签数 $count 不一致")
            }

            // tflite 文件大小合理性
            val tfliteBytes = extracted.bytes("model.tflite")
                ?: return ImportResult.Failure("模型包内 model.tflite 无法读取")
            if (tfliteBytes.size < MIN_TFLITE_BYTES) {
                return ImportResult.Failure(
                    "model.tflite 过小（${tfliteBytes.size} 字节），不是有效模型")
            }

            // Validate the actual TFLite tensors before recording an import;
            // a plausible manifest and file size alone do not make a model valid.
            val testFile = File(workDir, "validated.tflite")
            testFile.writeBytes(tfliteBytes)
            try {
                InferenceEngine(testFile.absolutePath, spec, labels, displayLabels).close()
            } catch (e: Exception) {
                return ImportResult.Failure("模型文件或张量与声明不兼容: ${e.message}")
            }

            // 4) 落盘到 App 私有目录
            val id = "model-" + System.currentTimeMillis().toString(16)
            val targetDir = File(File(context.filesDir, MODELS_SUBDIR), id)
            targetDir.mkdirs()
            File(targetDir, "model.tflite").writeBytes(tfliteBytes)
            File(targetDir, "manifest.json").writeText(manifestText)
            File(targetDir, "labels.json").writeText(labelsText)
            extracted.text("consistency.json")?.let {
                File(targetDir, "consistency.json").writeText(it)
            }

            val manifestName = manifest.optJSONObject("labels")
                ?.optString("file", "labels.json")
            val nameFromManifest = displayNameOverride.ifBlank {
                manifest.optString("name", "").ifBlank {
                    // 用第一个类别名拼一个可读名字，避免只显示 "model-xxxx"
                    labels.take(2).joinToString("+") + " 等${count}类"
                }
            }

            val record = ImportedModel(
                id = id,
                displayName = nameFromManifest,
                modelFile = "model.tflite",
                manifestFile = "manifest.json",
                labelsFile = manifestName ?: "labels.json",
                consistencyFile = if (extracted.contains("consistency.json")) {
                    "consistency.json"
                } else {
                    null
                },
                importedAt = System.currentTimeMillis(),
            )
            appendToIndex(context, record)
            Log.i(TAG, "模型导入成功: ${record.displayName} (${count} 类, " +
                "${spec.inputSize}px ${spec.colorOrder} ${spec.normalization})")
            return ImportResult.Success(record)
        } catch (e: Exception) {
            Log.e(TAG, "导入失败", e)
            return ImportResult.Failure("导入过程出错: ${e.message}")
        } finally {
            workDir.deleteRecursively()
        }
    }

    // =====================================================================
    // 读取已导入模型
    // =====================================================================

    fun listImported(context: Context): List<ImportedModel> {
        val index = File(File(context.filesDir, MODELS_SUBDIR), INDEX_FILE)
        if (!index.isFile) return emptyList()
        return try {
            val arr = org.json.JSONArray(index.readText())
            (0 until arr.length()).mapNotNull { i ->
                val o = arr.optJSONObject(i) ?: return@mapNotNull null
                val record = ImportedModel(
                    id = o.optString("id"),
                    displayName = o.optString("display_name"),
                    modelFile = o.optString("model_file", "model.tflite"),
                    manifestFile = o.optString("manifest_file", "manifest.json"),
                    labelsFile = o.optString("labels_file", "labels.json"),
                    consistencyFile = o.optString("consistency_file").ifBlank { null },
                    importedAt = o.optLong("imported_at", 0L),
                )
                // 模型文件必须真实存在，否则视为已损坏/被清理
                val modelPath = modelDir(context, record.id)
                if (File(modelPath, record.modelFile).isFile) record else null
            }
        } catch (e: Exception) {
            Log.w(TAG, "读取已导入模型列表失败", e)
            emptyList()
        }
    }

    fun deleteImported(context: Context, id: String): Boolean {
        val dir = modelDir(context, id)
        val ok = dir.deleteRecursively()
        removeFromIndex(context, id)
        return ok
    }

    /**
     * 加载一个已导入模型的完整内容（校验 spec、读标签与一致性记录）。
     *
     * 返回 null 时用 [lastLoadError] 查看原因。
     */
    fun load(context: Context, id: String): LoadedModel? {
        lastLoadError = null
        val record = listImported(context).firstOrNull { it.id == id }
            ?: run {
                lastLoadError = "找不到已导入模型: $id"
                return null
            }
        val dir = modelDir(context, record.id)
        return try {
            val manifestText = File(dir, record.manifestFile).readText()
            val manifest = JSONObject(manifestText)
            val preObj = manifest.getJSONObject("preprocess")
            val spec = PreprocessSpec.Spec(
                inputSize = preObj.optInt("input_size", 0),
                layout = preObj.optString("layout", PreprocessSpec.LAYOUT_NHWC),
                colorOrder = preObj.optString("color_order", PreprocessSpec.COLOR_RGB),
                normalization = preObj.optString(
                    "normalization", PreprocessSpec.NORM_IMAGENET),
                centerCrop = preObj.optBoolean("center_crop", true),
                contractVersion = preObj.optInt("contract_version", -1),
                mean = readVector(preObj, "mean", PreprocessSpec.IMAGENET_MEAN),
                std = readVector(preObj, "std", PreprocessSpec.IMAGENET_STD),
            )
            val problems = spec.validate()
            if (problems.isNotEmpty()) {
                lastLoadError = "模型预处理配置不兼容：" + problems.joinToString("；")
                return null
            }
            val labelsObj = JSONObject(File(dir, record.labelsFile).readText())
            val indexToName = labelsObj.getJSONObject("index_to_name")
            val indexToDisplay = labelsObj.optJSONObject("index_to_display")
            val count = labelsObj.optInt("count", indexToName.length())
            val labels = (0 until count).map { indexToName.getString(it.toString()) }
            val displayLabels = (0 until count).map {
                indexToDisplay?.optString(it.toString()) ?: labels[it]
            }

            var maxErr: Double? = null
            var agreement: Double? = null
            record.consistencyFile?.let { name ->
                val f = File(dir, name)
                if (f.isFile) {
                    try {
                        val c = JSONObject(f.readText())
                        if (c.has("max_abs_error")) maxErr = c.getDouble("max_abs_error")
                        if (c.has("top1_agreement")) {
                            agreement = c.getDouble("top1_agreement")
                        }
                    } catch (e: Exception) {
                        Log.w(TAG, "读取 consistency.json 失败", e)
                    }
                }
            }

            LoadedModel(
                id = record.id,
                displayName = record.displayName,
                tflitePath = File(dir, record.modelFile).absolutePath,
                spec = spec,
                labels = labels,
                displayLabels = displayLabels,
                consistencyMaxAbsError = maxErr,
                consistencyTop1Agreement = agreement,
            )
        } catch (e: Exception) {
            Log.e(TAG, "加载模型失败", e)
            lastLoadError = "加载模型失败: ${e.message}"
            null
        }
    }

    /** 最近一次 load() 失败的原因（供界面显示）。 */
    @Volatile
    var lastLoadError: String? = null
        private set

    // =====================================================================
    // 内部
    // =====================================================================

    private fun modelDir(context: Context, id: String): File =
        File(File(context.filesDir, MODELS_SUBDIR), id)

    private fun readVector(obj: JSONObject, key: String, fallback: FloatArray): List<Float> {
        if (!obj.has(key)) return fallback.toList()
        val array = obj.optJSONArray(key) ?: return emptyList()
        return (0 until array.length()).map { array.optDouble(it, Double.NaN).toFloat() }
    }

    private fun extract(zipPath: String, targetDir: File): ExtractedEntries? {
        return try {
            if (File(zipPath).length() > MAX_ARCHIVE_BYTES) {
                throw java.io.IOException("模型包超过大小限制")
            }
            val seen = mutableMapOf<String, ByteArray>()
            var totalBytes = 0L
            var entryCount = 0
            ZipInputStream(java.io.FileInputStream(zipPath)).use { zis ->
                var entry = zis.nextEntry
                while (entry != null) {
                    if (!entry.isDirectory) {
                        entryCount++
                        if (entryCount > MAX_ENTRIES) throw java.io.IOException("模型包文件过多")
                        val name = File(entry.name).name
                        if (name.isBlank() || name != entry.name || seen.containsKey(name)) {
                            throw java.io.IOException("模型包文件名无效或重复")
                        }
                        val limit = if (name == "model.tflite") MAX_MODEL_BYTES else MAX_METADATA_BYTES
                        val out = java.io.ByteArrayOutputStream()
                        val buffer = ByteArray(8192)
                        var entryBytes = 0
                        while (true) {
                            val count = zis.read(buffer)
                            if (count < 0) break
                            entryBytes += count
                            totalBytes += count
                            if (entryBytes > limit || totalBytes > MAX_ARCHIVE_BYTES) {
                                throw java.io.IOException("模型包解压内容超过大小限制")
                            }
                            out.write(buffer, 0, count)
                        }
                        seen[name] = out.toByteArray()
                    }
                    zis.closeEntry()
                    entry = zis.nextEntry
                }
            }
            ExtractedEntries(seen)
        } catch (e: Exception) {
            Log.e(TAG, "解压模型包失败", e)
            null
        }
    }

    private class ExtractedEntries(val files: Map<String, ByteArray>) {
        val keys: Set<String> get() = files.keys
        fun contains(name: String) = files.containsKey(name)
        fun bytes(name: String): ByteArray? = files[name]
        fun text(name: String): String? = files[name]?.toString(Charsets.UTF_8)
        fun readText(name: String): String =
            files[name]?.toString(Charsets.UTF_8)
                ?: throw IllegalStateException("模型包缺少 $name")
    }

    private fun appendToIndex(context: Context, record: ImportedModel) {
        val dir = File(context.filesDir, MODELS_SUBDIR)
        dir.mkdirs()
        val index = File(dir, INDEX_FILE)
        val arr = if (index.isFile) {
            try {
                org.json.JSONArray(index.readText())
            } catch (e: Exception) {
                Log.w(TAG, "索引损坏，重建", e)
                org.json.JSONArray()
            }
        } else {
            org.json.JSONArray()
        }
        arr.put(record.toJson())
        index.writeText(arr.toString())
    }

    private fun removeFromIndex(context: Context, id: String) {
        val dir = File(context.filesDir, MODELS_SUBDIR)
        val index = File(dir, INDEX_FILE)
        if (!index.isFile) return
        try {
            val arr = org.json.JSONArray(index.readText())
            val out = org.json.JSONArray()
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                if (o.optString("id") != id) out.put(o)
            }
            index.writeText(out.toString())
        } catch (e: Exception) {
            Log.w(TAG, "更新索引失败", e)
        }
    }

    private fun ImportedModel.toJson(): JSONObject = JSONObject().apply {
        put("id", id)
        put("display_name", displayName)
        put("model_file", modelFile)
        put("manifest_file", manifestFile)
        put("labels_file", labelsFile)
        put("consistency_file", consistencyFile ?: "")
        put("imported_at", importedAt)
    }
}
