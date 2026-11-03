"""
PhoneVision Lab — 数据划分（按采集批次切分训练/验证集）+ 数据体检。

职责：把数据集切成训练集与验证集，并在切分前做完整性检查。

为什么这样设计：
  - 按 batch 划分：一次连续采集产生的相邻帧几乎相同。如果随机按单张划分，
    验证集里会出现与训练集只差几毫秒的近似帧，准确率虚高、没有意义。
    这里以 batch 为最小单位，同一 batch 全进训练或全进验证。
  - 可复现：随机种子显式记录并写入 split.json，任何人重跑都得到同样划分。
  - 不伪造指标：类别缺失、样本不足、图片损坏、严重失衡时给出明确问题列表，
    调用方决定是否继续；本模块绝不"偷偷补样本"或"偷偷降低要求"。
  - 分层保证：每个类别都尽量在验证集里有代表（按类别内 batch 数分配），
    否则某个类别的验证准确率无从谈起。

初学者调试观察点：
  - 验证集里出现"和训练集长得一样"的图：说明没按 batch 划分，检查这里。
  - 划分结果为空：看 problems 列表，通常是样本太少或 batch 数不够。
"""
from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field

from pvl_dataset import Dataset, IMAGE_EXTENSIONS

# 每个类别至少需要的 batch 数（少于这个数无法在不"泄漏"的前提下切出验证集）。
MIN_BATCHES_PER_CLASS = 2

# 每个类别至少需要的样本数（少于这个数训练没有意义）。
MIN_SAMPLES_PER_CLASS = 4

# 严重失衡阈值：最大类别样本数 / 最小类别样本数 超过该比值时告警。
IMBALANCE_RATIO_WARN = 5.0


@dataclass
class SampleRef:
    """一个样本的引用（相对路径 + 所属类别 + 所属批次）。"""

    relative_path: str
    class_name: str
    batch_id: str

    def to_dict(self) -> dict:
        return {
            "relative_path": self.relative_path,
            "class_name": self.class_name,
            "batch_id": self.batch_id,
        }


@dataclass
class SplitResult:
    """一次划分的结果。"""

    train: list = field(default_factory=list)     # list[SampleRef]
    val: list = field(default_factory=list)       # list[SampleRef]
    seed: int = 0
    val_ratio: float = 0.2
    method: str = "by_batch"
    problems: list = field(default_factory=list)  # 人类可读的问题列表
    warnings: list = field(default_factory=list)

    def class_counts(self, split: str) -> dict:
        """某集合内各类别样本数。"""
        items = self.train if split == "train" else self.val
        out: dict = {}
        for s in items:
            out[s.class_name] = out.get(s.class_name, 0) + 1
        return out

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "val_ratio": self.val_ratio,
            "method": self.method,
            "train": [s.to_dict() for s in self.train],
            "val": [s.to_dict() for s in self.val],
            "problems": self.problems,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SplitResult":
        def _items(key):
            return [SampleRef(
                relative_path=str(d.get("relative_path", "")),
                class_name=str(d.get("class_name", "")),
                batch_id=str(d.get("batch_id", "")),
            ) for d in data.get(key, [])]
        return cls(
            train=_items("train"),
            val=_items("val"),
            seed=int(data.get("seed", 0) or 0),
            val_ratio=float(data.get("val_ratio", 0.2) or 0.2),
            method=str(data.get("method", "by_batch")),
            problems=list(data.get("problems", [])),
            warnings=list(data.get("warnings", [])),
        )


def collect_samples(dataset: Dataset) -> list:
    """遍历磁盘，收集全部样本（相对路径 + 类别 + 批次）。

    批次号从路径推断：images/<class>/<batch_id>/<file>。
    不在任何 batch 目录下的文件归入一个 "loose" 伪批次（不允许跨集合，
    会被整体划到训练集，并在 warnings 中说明）。
    """
    out: list = []
    for class_name in dataset.class_names():
        base = dataset.class_dir(class_name)
        if not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            rel_dir = os.path.relpath(root, base)
            batch_id = "loose" if rel_dir == "." else rel_dir.split(os.sep)[0]
            for f in sorted(files):
                if not f.lower().endswith(IMAGE_EXTENSIONS):
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, dataset.root)
                out.append(SampleRef(relative_path=rel, class_name=class_name,
                                     batch_id=batch_id))
    return out


def check_dataset(dataset: Dataset) -> tuple:
    """体检数据集，返回 (problems, warnings)。

    problems：阻断性问题（类别缺失、样本不足、没有 batch、图片无法解码）。
    warnings：不阻断但需注意（失衡、批次内样本过少、存在游离文件）。
    """
    problems: list = []
    warnings: list = []

    if not dataset.classes:
        problems.append("数据集没有任何类别")
        return problems, warnings

    samples = collect_samples(dataset)
    if not samples:
        problems.append("数据集没有任何图片样本")
        return problems, warnings

    counts = dataset.class_counts()
    empty_classes = [c for c, n in counts.items() if n == 0]
    if empty_classes:
        problems.append(f"以下类别没有样本: {', '.join(empty_classes)}")

    thin = [f"{c}({n})" for c, n in counts.items()
            if 0 < n < MIN_SAMPLES_PER_CLASS]
    if thin:
        problems.append(
            f"以下类别样本不足 {MIN_SAMPLES_PER_CLASS} 张: {', '.join(thin)}")

    # batch 覆盖检查：每个类别至少要有 MIN_BATCHES_PER_CLASS 个 batch
    for class_name in dataset.class_names():
        batch_ids = {s.batch_id for s in samples if s.class_name == class_name}
        real_batches = {b for b in batch_ids if b != "loose"}
        if len(real_batches) < MIN_BATCHES_PER_CLASS:
            if "loose" in batch_ids and len(real_batches) == 0:
                warnings.append(
                    f"类别 {class_name} 的样本不在 batch 目录下，"
                    f"将全部用于训练，不参与验证")
            else:
                problems.append(
                    f"类别 {class_name} 只有 {len(real_batches)} 个采集批次，"
                    f"至少需要 {MIN_BATCHES_PER_CLASS} 个才能划分验证集"
                    f"（避免相邻近似帧跨集合）")

    # 失衡检查
    nonzero = [n for n in counts.values() if n > 0]
    if nonzero and min(nonzero) > 0:
        ratio = max(nonzero) / max(1, min(nonzero))
        if ratio >= IMBALANCE_RATIO_WARN:
            warnings.append(
                f"类别样本量差距较大（最多/最少 = {ratio:.1f}:1），"
                f"可能偏向样本多的类别")

    # 图片可解码性抽查（每类最多抽查 3 张，避免大数据集上过慢）
    bad = _probe_corrupt_images(dataset, samples, per_class=3)
    if bad:
        problems.append("以下图片无法解码，请删除后重试: " + ", ".join(bad[:5]))

    return problems, warnings


def _probe_corrupt_images(dataset: Dataset, samples: list,
                          per_class: int = 3) -> list:
    """抽查图片能否解码（用 Pillow，避免训练框架的重依赖）。"""
    try:
        from PIL import Image
    except ImportError:  # Pillow 缺失：跳过检查而不是报错
        return []

    by_class: dict = {}
    for s in samples:
        by_class.setdefault(s.class_name, []).append(s)

    bad: list = []
    for class_name, items in by_class.items():
        step = max(1, len(items) // max(1, per_class))
        for s in items[::step][:per_class]:
            full = os.path.join(dataset.root, s.relative_path)
            try:
                with Image.open(full) as img:
                    img.verify()
            except Exception:  # noqa: BLE001 - 抽查失败只记录，不中断
                bad.append(s.relative_path)
    return bad


def split_dataset(dataset: Dataset, val_ratio: float = 0.2,
                  seed: int = 1234) -> SplitResult:
    """按采集批次划分训练/验证集。

    算法（保证可复现与分层）：
      1. 每个类别独立处理，收集该类别全部 batch。
      2. 用固定 seed 的 random.Random 打乱 batch 顺序。
      3. 按目标比例取验证 batch：至少 1 个；若只有 2 个 batch 则取 1 个。
      4. 剩余 batch 的全部样本进训练集，验证 batch 的全部样本进验证集。
      5. "loose"（不在 batch 目录）的样本全部进训练集，不参与验证。
    """
    result = SplitResult(seed=int(seed), val_ratio=float(val_ratio))

    samples = collect_samples(dataset)
    if not samples:
        result.problems.append("数据集没有任何图片样本")
        return result

    rng = random.Random(seed)

    for class_name in dataset.class_names():
        class_samples = [s for s in samples if s.class_name == class_name]
        if not class_samples:
            continue

        by_batch: dict = {}
        loose: list = []
        for s in class_samples:
            if s.batch_id == "loose":
                loose.append(s)
            else:
                by_batch.setdefault(s.batch_id, []).append(s)

        # 游离文件全部进训练，并明确告知不参与验证。
        result.train.extend(loose)
        if loose:
            result.warnings.append(
                f"类别 {class_name} 有 {len(loose)} 个样本不在批次目录下，"
                f"已全部用于训练（无法保证与训练集不重复，不参与验证）")

        batch_ids = list(by_batch.keys())
        if not batch_ids:
            continue

        rng.shuffle(batch_ids)

        # 只有一个批次（或用户要求 0 比例验证）：无法在不泄漏的前提下切验证集。
        # 原实现在这里 max(1, len-1)=1 会把唯一 batch 判进 val，train 为空，
        # 界面显示"划分成功"但训练立刻失败在"训练集为空"。全部进训练 + 明确警告。
        if len(batch_ids) < MIN_BATCHES_PER_CLASS or val_ratio <= 0:
            for items in by_batch.values():
                result.train.extend(items)
            result.warnings.append(
                f"类别 {class_name} 只有 {len(batch_ids)} 个采集批次"
                f"（需要 {MIN_BATCHES_PER_CLASS} 个才能切验证集），"
                f"全部样本用于训练，该类别不参与验证")
            continue

        # 选择"验证 batch 个数"：在允许范围内（至少留 1 个训练 batch）挑选
        # 实际验证比例最接近目标比例的数量。用前缀和而不是逐个累加，
        # 避免"批次大小不整除目标比例"时多拿一整批（例如 3 个等大批次、
        # 目标 40% 时会错拿 2 批变成 67%）。
        total = sum(len(by_batch[b]) for b in batch_ids)
        max_val_batches = len(batch_ids) - 1  # 至少留 1 个训练 batch（上面已保证 >=2）
        prefix = []
        running = 0
        for bid in batch_ids:
            running += len(by_batch[bid])
            prefix.append(running)

        best_n = 1
        best_err = float("inf")
        for n in range(1, min(max_val_batches, len(batch_ids)) + 1):
            achieved = prefix[n - 1] / float(total)
            err = abs(achieved - val_ratio)
            if err < best_err - 1e-12:
                best_err = err
                best_n = n

        val_batches = set(batch_ids[:best_n])
        for bid, items in by_batch.items():
            if bid in val_batches:
                result.val.extend(items)
            else:
                result.train.extend(items)

    # 统一排序，保证 split.json 稳定可比对。
    result.train.sort(key=lambda s: s.relative_path)
    result.val.sort(key=lambda s: s.relative_path)
    return result


def save_split(result: SplitResult, path: str) -> None:
    """把划分结果写入 JSON（含种子、比例、问题与警告）。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(result.to_dict(), fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_split(path: str) -> SplitResult:
    with open(path, encoding="utf-8") as fh:
        return SplitResult.from_dict(json.load(fh))
