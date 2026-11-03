# 训练说明：模型、权重、许可证与复现

本文说明 PhoneVision Lab 训练链路的**可复现性**与**第三方资产来源**，避免把随机初始化的模型包装成"训练成果"。

---

## 1. 选了什么模型与运行时

| 项目 | 选择 | 理由 |
| --- | --- | --- |
| 模型架构 | MobileNetV3Small | ImageNet 预训练权重 + 参数量约 2.9M；转 TFLite 后约 3-4 MB，适合旧手机 CPU 推理 |
| 训练框架 | TensorFlow / Keras（CPU） | 生态成熟，`tf.lite.TFLiteConverter` 导出路径直接 |
| 推理运行时 | TensorFlow Lite 2.16.1 | AAR `minSdk=19`，兼容本项目 `minSdk=21`（旧手机目标） |
| ABI 覆盖 | arm64-v8a / armeabi-v7a / x86 / x86_64 | 覆盖绝大多数存量手机 |
| 加速 | **默认仅 CPU** | NNAPI/GPU 委派在不同厂商 ROM 上行为差异大，未逐台验证前不启用 |

**没有同时接入多套推理框架**：本轮只实现 TFLite 一条路径。ONNX Runtime 等方案不在范围内（其 Android AAR `minSdk=24`，会把本项目的最低系统版本从 5.0 提到 7.0，与"旧手机"目标冲突）。

---

## 2. 预训练权重来源与许可证

| 项 | 值 |
| --- | --- |
| 架构 | MobileNetV3Small |
| 权重名 | `imagenet` |
| 提供方 | Keras Applications（`tensorflow.keras.applications.MobileNetV3Small`） |
| 下载主机 | `storage.googleapis.com` |
| 大小 | 约 8 MB |
| 许可证 | **Apache License 2.0**（与 Keras / TensorFlow 相同） |

权重文件本身**不**随仓库分发（避免把第三方资产提交进 Git）。首次训练时由 Keras 自动下载。

### 离线准备方法

```powershell
# 1) 联网状态下跑一次训练（任意小数据集都行），权重会缓存：
python scripts\smoke_train.py

# 2) 确认缓存位置（Windows）：
#    %USERPROFILE%\.keras\models\
#    文件名形如 weights_mobilenet_v3_small_224_1.0_224_ema_no_top.h5

# 3) 之后断网也能训练：Keras 会优先读本地缓存
```

换机器时，把 `.keras/models/` 下的权重文件复制到目标机同一路径即可。

---

## 3. 预处理契约（PC 与手机必须一致）

训练、PC 推理、Android 推理共用同一份规则，序列化进模型包的 `manifest.json`：

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `input_size` | 224 | 模型期望的方形边长 |
| `layout` | `NHWC` | TFLite 默认 |
| `color_order` | `RGB` | PC 端 OpenCV 是 BGR，导入时交换；Android 直接给 RGB |
| `normalization` | `raw` | RGB 浮点像素保持在 `[0,255]`，由模型内部 Rescaling 层缩放 |
| `mean` | `(0.485, 0.456, 0.406)` | ImageNet 均值（RGB 顺序） |
| `std` | `(0.229, 0.224, 0.225)` | ImageNet 标准差 |
| `center_crop` | `true` | 短边等比缩放后中心裁剪（保留构图，不拉伸） |
| `contract_version` | `1` | 升级预处理语义时递增，旧模型包会被拒绝导入 |

### MobileNetV3 的输入范围

当前模型明确设置 `include_preprocessing=True`；Keras 在模型内加入 Rescaling 层，
需要输入 RGB `[0,255]`，因此新训练选择 `raw`。见
[TensorFlow MobileNetV3Small 官方说明](https://www.tensorflow.org/api_docs/python/tf/keras/applications/MobileNetV3Small)。
旧版本使用 `imagenet` 预处理训练出的模型仍按包内原配置加载，但其预训练特征输入不正确，
不能用此前的合成数据结果证明实际效果；建议用真实数据重新训练并导出。

---

## 4. 数据划分：为什么按批次而不是随机

**随机按单张划分会造成验证指标虚高。**

连续采集时，相邻两帧往往只差几毫秒、画面几乎相同。如果它们一个进训练集、一个进验证集，验证集实际上"见过"训练集的内容，准确率会高得没有意义。

本项目的做法：

- 一次"开始连续采集"到"停止"算一个**批次**（batch）。
- 划分以批次为最小单位：同一批次的全部样本**要么全进训练、要么全进验证**。
- 每个类别独立分层，尽量让每个类别在验证集里都有代表。
- 随机种子与比例写进 `split.json`，任何人重跑得到同样划分。
- 只有 1 个批次时**拒绝划分**并说明原因，不伪造验证指标。

---

## 5. 训练流程（两阶段迁移学习）

| 阶段 | 做什么 | 学习率 |
| --- | --- | --- |
| 1 | 冻结 MobileNetV3 骨干网，只训练分类头 | `1e-3` |
| 2 | 解冻骨干网最后 20 层微调（BatchNorm 保持推理态） | `1e-4`（1/10） |

- 每个 epoch 结束在验证集上评估，**只在验证准确率提升时保存** `best.keras`。
- 训练步数少于 5 时**拒绝导出**（防止把没训练的模型当成果）。
- 取消是协作式的：每个 step 检查取消标志，干净退出并落盘当前状态。

---

## 6. 复现命令

```powershell
cd pc-client
.venv\Scripts\activate

# 完整链路冒烟测试（合成数据，不需要真机/照片）
# 会跑：建数据集 -> 采集 -> 体检 -> 划分 -> 训练 -> 导出 -> 一致性校验
.venv-train\Scripts\python.exe scripts\smoke_train.py

# 只跑测试
$env:QT_QPA_PLATFORM = "offscreen"
python -m unittest discover -s tests -t tests
```

### 训练配置记录在哪里

每次训练的完整配置写在 `<run 目录>/config.json`，包含：

- 数据集根目录、类别名与顺序
- 全部超参数（epochs / batch / lr / seed / 输入尺寸）
- 预处理 spec
- 预训练权重来源与许可证
- 使用的设备（CPU / GPU）与说明
- 划分文件路径与随机种子

---

## 7. 已知限制

| 限制 | 说明 |
| --- | --- |
| 不做 int8 全量化 | 需要代表性数据集校准，分类任务上更容易掉点；首版保持可解释性 |
| 不承诺 GPU 加速 | 只在检测到 GPU 时才出现 GPU 选项；实际加速效果需真机验证 |
| 数据集全量读入内存 | 适合几十到几百张/类的小数据集；上万张需要改成 `tf.data` 生成器 |
| 不支持目标检测/分割 | 本轮只做图像分类；检测/分割是后续扩展 |
| 训练指标依赖真实数据 | 合成数据只能验证链路可用，真实准确率必须用你自己的照片测 |

---

## 8. 第三方许可证汇总

| 组件 | 许可证 | 用途 |
| --- | --- | --- |
| TensorFlow / Keras | Apache-2.0 | 训练与 TFLite 转换 |
| MobileNetV3 权重 | Apache-2.0 | ImageNet 预训练权重 |
| TensorFlow Lite (Android) | Apache-2.0 | 手机端推理 |
| NumPy | BSD-3-Clause | 数值计算 |
| Pillow | HPND | 图片编解码 |
| OpenCV | Apache-2.0 | 传统视觉处理 |
| PySide6 | LGPL-3.0 | 桌面界面（见 `docs/qt-lgpl-compliance.md`） |
| ArduinoJson | MIT | 控制器固件 JSON 解析 |
