"""
PhoneVision Lab — 预处理契约（PC 与 Android 共用的唯一事实来源）。

职责：定义"一张 BGR 图像如何变成模型输入张量"的完整规则，并保证：
  - 训练（PC）、导出前对比（PC）、Android 端推理 使用完全一致的预处理；
  - 规则可序列化进模型包，手机端据此自检是否兼容，而不是靠双方各自假设。

为什么这样设计：
  - "训练用 /255 归一化、推理用 /255.0"这类微小差异会让准确率凭空下降。
    把规则集中成一个纯函数 + 一个可 JSON 序列化的 spec，两边都读同一份描述。
  - 预处理是纯数值变换（不依赖 OpenCV 也不依赖 Android Bitmap），
    因此可以在 PC 上用 numpy 直接单测，不需要设备。
  - spec 里显式记录颜色顺序、缩放、裁剪、归一化，模型包自带自描述，
    导入手机时可直接比对，不匹配就明确拒绝。

初学者调试观察点：
  - 结果对不上时，先比对两边的 spec（json 一样才是同一种预处理）。
  - resize 用 INTER_AREA（缩小更清晰）与 INTER_LINEAR（放大）不同，
    这里对"源比目标大"用 AREA、"源比目标小"用 LINEAR，与 Android 端
    Bitmap.createScaledBitmap(filter=true) 的最近邻语义接近但更稳。
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np

# 契约版本：升级预处理语义时必须递增，旧模型包会因版本不匹配被拒绝导入。
PREPROCESS_CONTRACT_VERSION = 1

# 输入张量布局选项。
LAYOUT_NHWC = "NHWC"
LAYOUT_NCHW = "NCHW"

# 颜色顺序选项。
COLOR_RGB = "RGB"
COLOR_BGR = "BGR"


@dataclass(frozen=True)
class PreprocessSpec:
    """预处理规则的自描述快照，可序列化进模型包。"""

    # 模型期望的输入方形边长（像素）。0 表示不缩放（不推荐）。
    input_size: int = 224
    # 张量布局：NHWC（TFLite 默认）或 NCHW（ONNX 常见）。
    layout: str = LAYOUT_NHWC
    # 颜色顺序：RGB 或 BGR。PC 的 OpenCV 帧是 BGR，Android 的 YUV_420_888 可直出 RGB。
    color_order: str = COLOR_RGB
    # 归一化方式：
    #   "imagenet": (x/255.0 - mean) / std，保留用于读取旧模型的契约。
    #               当前 MobileNetV3 自带缩放层，新训练应使用 raw RGB [0,255]。
    #   "unit"    : x / 255.0，输出范围 [0,1]（适合从零训练/无预训练权重）
    #   "raw"     : 不缩放（模型自带）
    normalization: str = "imagenet"
    # imagenet 归一化用的均值/标准差（按 color_order 的顺序）。
    mean: tuple = (0.485, 0.456, 0.406)
    std: tuple = (0.229, 0.224, 0.225)
    # 是否中心裁剪（短边缩放后裁正方形）；False 表示直接拉伸到 input_size。
    center_crop: bool = True
    # 契约版本，用于兼容性校验。
    contract_version: int = PREPROCESS_CONTRACT_VERSION

    def to_dict(self) -> dict:
        """序列化为可 JSON 存储的 dict（tuple -> list）。"""
        data = asdict(self)
        data["mean"] = list(self.mean)
        data["std"] = list(self.std)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "PreprocessSpec":
        """从 dict 还原；缺字段用默认值，多余字段忽略（向前兼容）。"""
        known = {f for f in cls.__dataclass_fields__}
        kwargs = {k: v for k, v in (data or {}).items() if k in known}
        mean = tuple(kwargs.get("mean") or cls.mean)
        std = tuple(kwargs.get("std") or cls.std)
        kwargs["mean"] = mean
        kwargs["std"] = std
        return cls(**kwargs)

    def validate(self) -> list:
        """返回人类可读的问题列表；空列表表示合法。"""
        problems: list = []
        if not isinstance(self.input_size, int) or self.input_size <= 0:
            problems.append("input_size 必须是正整数")
        if self.layout not in (LAYOUT_NHWC, LAYOUT_NCHW):
            problems.append(f"layout 只能是 {LAYOUT_NHWC} 或 {LAYOUT_NCHW}")
        if self.color_order not in (COLOR_RGB, COLOR_BGR):
            problems.append(f"color_order 只能是 {COLOR_RGB} 或 {COLOR_BGR}")
        if self.normalization not in ("unit", "imagenet", "raw"):
            problems.append("normalization 只能是 unit / imagenet / raw")
        if len(self.mean) != 3 or len(self.std) != 3:
            problems.append("mean/std 必须各有 3 个值")
        if any(float(s) == 0.0 for s in self.std):
            problems.append("std 不能含 0")
        if self.contract_version != PREPROCESS_CONTRACT_VERSION:
            problems.append(
                f"契约版本不匹配：模型包为 v{self.contract_version}，"
                f"本端支持 v{PREPROCESS_CONTRACT_VERSION}")
        return problems


def resize_frame(frame: np.ndarray, size: int, center_crop: bool = True) -> np.ndarray:
    """把任意尺寸的 BGR/RGB 帧整理成 size x size。

    - center_crop=True：短边等比放大/缩小到 size，再中心裁 size x size。
      这保留完整构图（不拉伸），与训练时 tf.image.resize_with_crop_or_pad
      的语义一致。
    - center_crop=False：直接拉伸到 size x size（会变形，仅用于对齐实验）。
    """
    if frame is None or frame.size == 0:
        raise ValueError("空图像")
    if size <= 0:
        raise ValueError("size 必须是正整数")

    src_h, src_w = frame.shape[:2]

    if not center_crop:
        # 直接拉伸（双线性）。
        return _resize_bilinear(frame, size, size)

    scale = size / float(min(src_h, src_w))
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))

    if new_w >= src_w and new_h >= src_h:
        resized = _resize_bilinear(frame, new_w, new_h)      # 放大：双线性
    else:
        resized = _resize_area(frame, new_w, new_h)          # 缩小：区域采样

    # 若缩放后仍小于目标（极端长宽比），补边到目标尺寸。
    if new_h < size or new_w < size:
        pad_h = max(0, size - new_h)
        pad_w = max(0, size - new_w)
        top, bottom = pad_h // 2, pad_h - pad_h // 2
        left, right = pad_w // 2, pad_w - pad_w // 2
        resized = np.pad(
            resized,
            ((top, bottom), (left, right), (0, 0)),
            mode="edge",
        )

    # 中心裁剪到 size x size
    h, w = resized.shape[:2]
    top = max(0, (h - size) // 2)
    left = max(0, (w - size) // 2)
    return resized[top:top + size, left:left + size]


def _resize_area(frame: np.ndarray, new_w: int, new_h: int) -> np.ndarray:
    """缩小的区域平均采样（ separable box filter，比双线性缩小更稳）。

    实现是"可分离"的：先沿 y 方向按源行区间求平均，再沿 x 方向按源列区间
    求平均。这样做的好处是中间数组只有 (src_w, 3)，内存与代码都简单，
    且每个输出像素恰好是它覆盖的源像素的平均值（与 Android 端
     RenderScript/Bitmap 的缩小语义接近）。

    纯 numpy 实现，避免训练/推理两端因 OpenCV 版本差异产生不同结果。
    """
    src_h, src_w = frame.shape[:2]
    if src_h == new_h and src_w == new_w:
        return frame.copy()

    y0, y1 = _axis_blocks(src_h, new_h)
    x0, x1 = _axis_blocks(src_w, new_w)

    src = frame.astype(np.float32)
    # 第一步：y 方向平均 -> (new_h, src_w, 3)
    rows = np.empty((new_h, src_w, frame.shape[2]), dtype=np.float32)
    for ty in range(new_h):
        rows[ty] = src[y0[ty]:y1[ty]].mean(axis=0)

    # 第二步：x 方向平均 -> (new_h, new_w, 3)
    out = np.empty((new_h, new_w, frame.shape[2]), dtype=np.float32)
    for tx in range(new_w):
        out[:, tx] = rows[:, x0[tx]:x1[tx]].mean(axis=1)

    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def _axis_blocks(src_n: int, dst_n: int) -> tuple:
    """把 src_n 个源像素划分成 dst_n 个连续区间，返回 (starts, ends)。

    - 每个区间至少 1 个像素。
    - 区间边界用"中心对齐"计算（(i + 0.5) * scale），与常见图像缩放一致。
    - 相邻区间不重叠、不漏掉任何源像素（start[0]=0, end[-1]=src_n）。
    """
    scale = src_n / float(dst_n)
    starts = np.empty(dst_n, dtype=np.int64)
    ends = np.empty(dst_n, dtype=np.int64)
    for i in range(dst_n):
        s = int(round(i * scale))
        e = int(round((i + 1) * scale))
        if i == dst_n - 1:
            e = src_n
        s = min(max(s, 0), src_n - 1)
        e = min(max(e, s + 1), src_n)
        starts[i] = s
        ends[i] = e
    # 保证区间单调不重叠（防御性修正）
    for i in range(1, dst_n):
        if starts[i] < ends[i - 1]:
            starts[i] = ends[i - 1]
            ends[i] = max(ends[i], starts[i] + 1)
    return starts, ends


def _resize_bilinear(frame: np.ndarray, new_w: int, new_h: int) -> np.ndarray:
    """放大的双线性采样（纯 numpy，可分离实现）。

    可分离：先按 y 权重在行方向插值，再按 x 权重在列方向插值。
    每一步都是 (out, in) x (in,) 的广播，不会出现 (64,512,3) 与 (1,512)
    这类维度不匹配的错误。
    """
    src_h, src_w = frame.shape[:2]
    if src_h == new_h and src_w == new_w:
        return frame.copy()

    ys = np.clip((np.arange(new_h) + 0.5) * (src_h / new_h) - 0.5, 0, src_h - 1)
    xs = np.clip((np.arange(new_w) + 0.5) * (src_w / new_w) - 0.5, 0, src_w - 1)

    y0 = np.floor(ys).astype(np.int64)
    x0 = np.floor(xs).astype(np.int64)
    y1 = np.minimum(y0 + 1, src_h - 1)
    x1 = np.minimum(x0 + 1, src_w - 1)
    wy = (ys - y0).astype(np.float32).reshape(-1, 1)      # (new_h, 1)
    wx = (xs - x0).astype(np.float32).reshape(1, -1)      # (1, new_w)

    src = frame.astype(np.float32)

    # 第一步：行方向插值 -> (new_h, src_w, 3)
    top_rows = src[y0] * (1 - wy)[:, :, None] + src[y1] * wy[:, :, None]

    # 第二步：列方向插值 -> (new_h, new_w, 3)
    out = top_rows[:, x0] * (1 - wx)[:, :, None] + top_rows[:, x1] * wx[:, :, None]

    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def preprocess(frame_bgr: np.ndarray, spec: PreprocessSpec) -> np.ndarray:
    """按 spec 把一张 BGR 帧变成模型输入张量（float32）。

    这是训练、PC 推理、导出前后对比共用的唯一实现。Android 端按 spec
    的字段逐条等价实现（见 android 的 Preprocessor.kt），并在导入模型时
    比对 spec。
    """
    problems = spec.validate()
    if problems:
        raise ValueError("预处理配置非法：" + "；".join(problems))
    if frame_bgr is None or frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3:
        raise ValueError("输入必须是 3 通道图像")

    # 1) 尺寸整理（缩放 + 中心裁剪）
    resized = resize_frame(frame_bgr, spec.input_size, center_crop=spec.center_crop)

    # 2) 颜色顺序：OpenCV 帧是 BGR；需要 RGB 时交换通道。
    if spec.color_order == COLOR_RGB:
        ordered = resized[:, :, ::-1]
    else:
        ordered = resized

    # 3) 归一化（在 float32 域进行，避免 uint8 溢出）。
    values = ordered.astype(np.float32)
    if spec.normalization == "unit":
        values = values / 255.0
    elif spec.normalization == "imagenet":
        values = values / 255.0
        mean = np.asarray(spec.mean, dtype=np.float32)
        std = np.asarray(spec.std, dtype=np.float32)
        values = (values - mean) / std
    # "raw"：保持原值。

    # 4) 张量布局 + batch 维。
    if spec.layout == LAYOUT_NHWC:
        tensor = values.reshape(1, spec.input_size, spec.input_size, 3)
    else:
        tensor = np.transpose(values, (2, 0, 1)).reshape(
            1, 3, spec.input_size, spec.input_size)
    return np.ascontiguousarray(tensor, dtype=np.float32)


def softmax(logits: np.ndarray) -> np.ndarray:
    """数值稳定的 softmax（行方向）。"""
    row = np.asarray(logits, dtype=np.float32).reshape(-1)
    shifted = row - float(np.max(row))
    exp = np.exp(shifted)
    total = float(np.sum(exp))
    if total <= 0.0 or not math.isfinite(total):
        # 退化情况：均匀分布，绝不平白报错。
        return np.full(row.shape, 1.0 / row.size, dtype=np.float32)
    return (exp / total).astype(np.float32)


def top_k(probs: np.ndarray, k: int = 1) -> list:
    """取概率最高的 k 个 (index, prob)，按概率降序。"""
    flat = np.asarray(probs, dtype=np.float32).reshape(-1)
    k = max(1, min(int(k), flat.size))
    idx = np.argpartition(flat, -k)[-k:]
    idx = idx[np.argsort(flat[idx])[::-1]]
    return [(int(i), float(flat[i])) for i in idx]
