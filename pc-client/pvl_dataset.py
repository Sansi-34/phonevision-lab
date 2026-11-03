"""
PhoneVision Lab — 数据集管理（创建/打开、类别、采集、保存、划分）。

职责：把"用户自定义类别的图片集合"作为一个数据集持久化到用户目录，
并提供按采集批次划分训练/验证集的能力。

为什么这样设计：
  - 相邻近似帧（连续采集的同一次会话）如果分别进入训练集和验证集，
    验证集会"见过"几乎相同的画面，指标虚高。因此划分以 batch（一次
    连续采集会话）为最小单位：同一 batch 的全部样本要么全进训练、要么
    全进验证，绝不打散。
  - 数据集目录结构对人类可读：<datasets>/<name>/images/<class>/<batch>/<file>.jpg，
    清理误采图片直接在文件管理器里删即可。
  - 配置与批次信息是 JSON（dataset.json），可手改、可版本控制、可跨机器复制。
  - 所有写盘操作返回结构化结果（成功/失败原因），GUI 只负责展示，
    不在这里做任何阻塞式弹窗。

初学者调试观察点：
  - 样本数不对：看 dataset.json 的 batches 记录，或 images/<class> 下实际文件数。
  - 验证指标异常高：确认 split 是按 batch 划分，而不是按单张随机划分。
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

# 数据集配置文件名。
DATASET_CONFIG_NAME = "dataset.json"

# 图片目录名。
IMAGES_DIR_NAME = "images"

# 允许的图片扩展名（小写）。
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")

# 类别名安全字符：只允许字母、数字、下划线、连字符、点，且不能以点开头。
# 类别名会变成目录名，必须避免路径穿越（"../"）与非法文件名字符。
_CLASS_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")


def normalize_class_name(raw: str) -> str:
    """把用户输入的类别名规范化成安全目录名。

    - 去掉首尾空白；空名抛错。
    - 空格转下划线；非法字符转下划线。
    - 以点开头（隐藏文件/相对路径）会被拒绝。
    """
    name = (raw or "").strip()
    if not name:
        raise ValueError("类别名不能为空")
    name = name.replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9_.\-]", "_", name)
    if not _CLASS_NAME_RE.match(name):
        raise ValueError(
            f"类别名 {raw!r} 含非法字符；只允许字母、数字、_ - . ，且不能以 . 开头")
    if name in (".", ".."):
        raise ValueError("类别名不能是 . 或 ..")
    return name


@dataclass
class ClassInfo:
    """一个类别的持久化信息。"""

    name: str                     # 规范化后的目录名（安全）
    display_name: str             # 用户原始输入（保留大小写/空格）
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ClassInfo":
        return cls(
            name=str(data.get("name", "")),
            display_name=str(data.get("display_name", data.get("name", ""))),
            created_at=float(data.get("created_at", 0.0) or 0.0),
        )


@dataclass
class BatchInfo:
    """一次采集会话（batch）。

    划分训练/验证集以 batch 为最小单位：同一 batch 的所有样本同进同出，
    避免相邻近似帧跨集合导致验证指标虚高。
    """

    batch_id: str
    class_name: str
    created_at: float = 0.0
    count: int = 0                # 采集时的样本数（实际以目录文件数为准）
    split: str = "train"          # "train" 或 "val"

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "class_name": self.class_name,
            "created_at": self.created_at,
            "count": self.count,
            "split": self.split,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BatchInfo":
        return cls(
            batch_id=str(data.get("batch_id", "")),
            class_name=str(data.get("class_name", "")),
            created_at=float(data.get("created_at", 0.0) or 0.0),
            count=int(data.get("count", 0) or 0),
            split=str(data.get("split", "train")),
        )


@dataclass
class Dataset:
    """一个数据集的完整内存表示（可序列化为 dataset.json）。"""

    name: str
    root: str
    classes: list = field(default_factory=list)        # list[ClassInfo]
    batches: list = field(default_factory=list)        # list[BatchInfo]
    created_at: float = 0.0
    updated_at: float = 0.0
    notes: str = ""

    # ---- 序列化 ----

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "notes": self.notes,
            "classes": [c.to_dict() for c in self.classes],
            "batches": [b.to_dict() for b in self.batches],
        }

    @classmethod
    def from_dict(cls, data: dict, root: str) -> "Dataset":
        return cls(
            name=str(data.get("name", os.path.basename(root))),
            root=root,
            classes=[ClassInfo.from_dict(c) for c in data.get("classes", [])],
            batches=[BatchInfo.from_dict(b) for b in data.get("batches", [])],
            created_at=float(data.get("created_at", 0.0) or 0.0),
            updated_at=float(data.get("updated_at", 0.0) or 0.0),
            notes=str(data.get("notes", "")),
        )

    # ---- 类别 ----

    def class_names(self) -> list:
        return [c.name for c in self.classes]

    def display_names(self) -> list:
        return [c.display_name or c.name for c in self.classes]

    def get_class(self, name: str) -> ClassInfo | None:
        for c in self.classes:
            if c.name == name:
                return c
        return None

    def add_class(self, display_name: str) -> ClassInfo:
        """新增类别；已存在则返回既有（幂等）。"""
        name = normalize_class_name(display_name)
        existing = self.get_class(name)
        if existing is not None:
            return existing
        info = ClassInfo(name=name, display_name=display_name.strip(),
                         created_at=time.time())
        self.classes.append(info)
        self.touch()
        return info

    def rename_class(self, name: str, new_display_name: str) -> ClassInfo:
        """重命名类别（同时改目录名）。"""
        info = self.get_class(name)
        if info is None:
            raise ValueError(f"类别不存在: {name}")
        new_name = normalize_class_name(new_display_name)
        if new_name != name:
            if self.get_class(new_name) is not None:
                raise ValueError(f"类别已存在: {new_name}")
            old_dir = self.class_dir(name)
            new_dir = self.class_dir(new_name)
            if os.path.isdir(old_dir):
                os.rename(old_dir, new_dir)
            for batch in self.batches:
                if batch.class_name == name:
                    batch.class_name = new_name
            info.name = new_name
        info.display_name = new_display_name.strip()
        self.touch()
        return info

    def remove_class(self, name: str) -> None:
        """删除类别及其图片目录。

        至少保留一个类别：没有类别的数据集无法训练，直接拒绝比留下空目录更好。
        """
        info = self.get_class(name)
        if info is None:
            return
        if len(self.classes) <= 1:
            raise ValueError("至少需要保留一个类别")
        directory = self.class_dir(name)
        if os.path.isdir(directory):
            for entry in os.listdir(directory):
                path = os.path.join(directory, entry)
                if os.path.isfile(path):
                    os.remove(path)
                else:
                    _rmtree(path)
            os.rmdir(directory)
        self.classes = [c for c in self.classes if c.name != name]
        self.batches = [b for b in self.batches if b.class_name != name]
        self.touch()

    # ---- 路径 ----

    def class_dir(self, class_name: str) -> str:
        return os.path.join(self.root, IMAGES_DIR_NAME, class_name)

    def batch_dir(self, class_name: str, batch_id: str) -> str:
        return os.path.join(self.class_dir(class_name), batch_id)

    def touch(self) -> None:
        self.updated_at = time.time()

    # ---- 统计 ----

    def count_images(self, class_name: str) -> int:
        """统计某类别实际磁盘上的图片文件数（不信任内存计数）。"""
        directory = self.class_dir(class_name)
        if not os.path.isdir(directory):
            return 0
        total = 0
        for base, _dirs, files in os.walk(directory):
            for f in files:
                if f.lower().endswith(IMAGE_EXTENSIONS):
                    total += 1
        return total

    def class_counts(self) -> dict:
        """{class_name: 图片数}，按类别顺序。"""
        return {c.name: self.count_images(c.name) for c in self.classes}

    def list_samples(self, class_name: str) -> list:
        """列出某类别全部样本的相对路径（相对数据集 root），按路径排序。"""
        directory = self.class_dir(class_name)
        if not os.path.isdir(directory):
            return []
        out = []
        for base, _dirs, files in os.walk(directory):
            for f in files:
                if f.lower().endswith(IMAGE_EXTENSIONS):
                    full = os.path.join(base, f)
                    out.append(os.path.relpath(full, self.root))
        return sorted(out)

    def batches_for(self, class_name: str) -> list:
        return [b for b in self.batches if b.class_name == class_name]

    def delete_sample(self, relative_path: str) -> None:
        """删除单个样本文件（清理误采图片）。路径必须在数据集内。"""
        target = self._safe_join(relative_path)
        if not os.path.isfile(target):
            raise ValueError(f"样本不存在: {relative_path}")
        os.remove(target)
        # 同步 batch 计数
        rel = os.path.relpath(target, self.root)
        parts = rel.split(os.sep)
        if len(parts) >= 3 and parts[1].startswith("batch-"):
            for batch in self.batches:
                if batch.batch_id == parts[1] and batch.class_name == parts[0]:
                    batch.count = max(0, batch.count - 1)
                    break
        self.touch()

    def _safe_join(self, relative_path: str) -> str:
        """把用户可见的相对路径解析成数据集内的绝对路径，拒绝越界。

        规则：路径里出现任何 ".." 段、绝对路径、或解析后落到数据集目录之外，
        一律拒绝。宁可直接拒绝，也不给路径穿越留任何空间。
        """
        if not self.root:
            raise ValueError("没有打开的数据集")
        raw = str(relative_path)
        if not raw:
            raise ValueError("样本路径为空")
        if os.path.isabs(raw):
            raise ValueError(f"非法样本路径（不允许绝对路径）: {relative_path}")
        parts = raw.replace("\\", "/").split("/")
        if any(p == ".." for p in parts):
            raise ValueError(f"非法样本路径（不允许上级目录）: {relative_path}")
        target = os.path.normpath(os.path.join(self.root, raw))
        root_norm = os.path.normpath(self.root)
        if not (target == root_norm or target.startswith(root_norm + os.sep)):
            raise ValueError(f"样本路径越界: {relative_path}")
        return target


def _rmtree(path: str) -> None:
    """递归删除目录（小工具，避免依赖 shutil 之外的逻辑分散）。"""
    for base, dirs, files in os.walk(path, topdown=False):
        for f in files:
            os.remove(os.path.join(base, f))
        for d in dirs:
            _rmtree(os.path.join(base, d))
    if os.path.isdir(path):
        os.rmdir(path)


class DatasetStore:
    """数据集的创建/打开/保存，以及采集写入。

    所有方法都不做 GUI 相关操作，也不打印到 stdout（日志由调用方负责）。
    """

    def __init__(self, root: str):
        # root 允许为空：表示"用用户数据目录 + 数据集名"（create 时再定）。
        self.root = os.path.abspath(root) if root else ""
        self.dataset: Dataset | None = None

    # ---- 创建 / 打开 / 保存 ----

    @staticmethod
    def sanitize_name(raw: str) -> str:
        """数据集名规范化（用作目录名）。"""
        name = (raw or "").strip()
        if not name:
            raise ValueError("数据集名不能为空")
        name = name.replace(" ", "_")
        name = re.sub(r"[^A-Za-z0-9_.\-]", "_", name)
        if name in (".", "..") or name.startswith("."):
            raise ValueError("数据集名不能以 . 开头，也不能是 . 或 ..")
        return name[:64]

    def create(self, name: str, class_names: list | None = None) -> Dataset:
        """创建数据集（已存在则打开既有，避免误覆盖）。

        目录位置：以构造函数传入的 root 为准；只有 root 为空时才回落到
        用户数据目录（PVL_DATA_DIR 或默认位置）下的 <name> 子目录。
        这样调用方显式指定的路径不会被环境变量悄悄改写。
        """
        safe = self.sanitize_name(name)
        if not self.root:
            self.root = os.path.join(_default_datasets_root(), safe)
        os.makedirs(os.path.join(self.root, IMAGES_DIR_NAME), exist_ok=True)
        config_path = self.config_path()
        if os.path.isfile(config_path):
            return self.open(self.root)
        dataset = Dataset(name=name, root=self.root, created_at=time.time())
        for cn in (class_names or []):
            dataset.add_class(cn)
        self.dataset = dataset
        self.save()
        return dataset

    def config_path(self) -> str:
        if not self.root:
            raise ValueError("尚未确定数据集目录")
        return os.path.join(self.root, DATASET_CONFIG_NAME)

    def open(self, root: str) -> Dataset:
        """打开既有数据集；配置缺失时按目录结构重建类别列表。"""
        root = os.path.abspath(root)
        config_path = os.path.join(root, DATASET_CONFIG_NAME)
        if os.path.isfile(config_path):
            with open(config_path, encoding="utf-8") as fh:
                data = json.load(fh)
            dataset = Dataset.from_dict(data, root)
        else:
            dataset = Dataset(name=os.path.basename(root), root=root,
                              created_at=time.time())
            images = os.path.join(root, IMAGES_DIR_NAME)
            if os.path.isdir(images):
                for entry in sorted(os.listdir(images)):
                    if os.path.isdir(os.path.join(images, entry)):
                        dataset.add_class(entry)
        self.root = root
        self.dataset = dataset
        # 用磁盘真实文件数校正 batch.count，避免手改文件后计数失真。
        self._resync_batch_counts()
        self.save()
        return dataset

    def save(self) -> None:
        if self.dataset is None:
            raise ValueError("没有打开的数据集")
        self.dataset.touch()
        os.makedirs(self.root, exist_ok=True)
        tmp = self.config_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.dataset.to_dict(), fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.config_path())   # 原子替换，避免写一半损坏

    def _resync_batch_counts(self) -> None:
        """按磁盘真实文件数校正 batch.count（用户可能手动删过文件）。"""
        if self.dataset is None:
            return
        for batch in self.dataset.batches:
            directory = self.dataset.batch_dir(batch.class_name, batch.batch_id)
            if os.path.isdir(directory):
                real = sum(
                    1 for f in os.listdir(directory)
                    if f.lower().endswith(IMAGE_EXTENSIONS))
                batch.count = real

    # ---- 采集 ----

    def start_batch(self, class_name: str, prefix: str = "batch") -> BatchInfo:
        """开始一次采集会话，返回 BatchInfo（目录立即创建）。"""
        if self.dataset is None:
            raise ValueError("没有打开的数据集")
        if self.dataset.get_class(class_name) is None:
            raise ValueError(f"类别不存在: {class_name}")
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        batch_id = f"{prefix}-{stamp}-{os.urandom(2).hex()}"
        directory = self.dataset.batch_dir(class_name, batch_id)
        os.makedirs(directory, exist_ok=True)
        info = BatchInfo(batch_id=batch_id, class_name=class_name,
                         created_at=time.time(), count=0)
        self.dataset.batches.append(info)
        self.save()
        return info

    def save_frame(self, class_name: str, batch_id: str, jpeg_bytes: bytes) -> str:
        """写入一帧 JPEG，返回相对路径。

        同名文件加序号后缀，绝不静默覆盖已有图片。
        """
        if self.dataset is None:
            raise ValueError("没有打开的数据集")
        directory = self.dataset.batch_dir(class_name, batch_id)
        os.makedirs(directory, exist_ok=True)
        if not jpeg_bytes:
            raise ValueError("空图像数据")
        index = 0
        while True:
            filename = f"{index:04d}.jpg"
            target = os.path.join(directory, filename)
            if not os.path.exists(target):
                break
            index += 1
            if index > 9999:
                raise ValueError("单个批次样本数超过 9999，请开始新批次")
        with open(target, "wb") as fh:
            fh.write(jpeg_bytes)
        for batch in self.dataset.batches:
            if batch.batch_id == batch_id and batch.class_name == class_name:
                batch.count += 1
                break
        self.save()
        return os.path.relpath(target, self.dataset.root)

    def end_batch(self, class_name: str, batch_id: str) -> None:
        """结束采集会话（当前只是落盘计数，保留给后续扩展）。"""
        if self.dataset is None:
            return
        self._resync_batch_counts()
        self.save()


def _default_datasets_root() -> str:
    """默认数据集根目录（用户目录下），可被 PVL_DATA_DIR 覆盖。"""
    override = os.environ.get("PVL_DATA_DIR", "").strip()
    if override:
        return os.path.join(os.path.abspath(override), "datasets")
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(local, "PhoneVisionLab", "datasets")
    return os.path.join(os.path.expanduser("~"), ".local", "share",
                        "PhoneVisionLab", "datasets")


def list_datasets() -> list:
    """列出用户目录下全部数据集（含根路径与类别数）。"""
    root = _default_datasets_root()
    if not os.path.isdir(root):
        return []
    out = []
    # Earlier versions accidentally created the dataset in the parent itself.
    # Keep it discoverable without moving or modifying the user's data.
    legacy_config = os.path.join(root, DATASET_CONFIG_NAME)
    if os.path.isfile(legacy_config):
        try:
            with open(legacy_config, encoding="utf-8") as fh:
                data = json.load(fh)
            out.append({"name": str(data.get("name", os.path.basename(root))),
                        "root": root, "classes": len(data.get("classes", [])),
                        "samples": 0})
        except (OSError, ValueError):
            pass
    for entry in sorted(os.listdir(root)):
        path = os.path.join(root, entry)
        if not os.path.isdir(path):
            continue
        config = os.path.join(path, DATASET_CONFIG_NAME)
        if not os.path.isfile(config) and not os.path.isdir(os.path.join(path, IMAGES_DIR_NAME)):
            continue
        info = {"name": entry, "root": path, "classes": 0, "samples": 0}
        if os.path.isfile(config):
            try:
                with open(config, encoding="utf-8") as fh:
                    data = json.load(fh)
                info["name"] = str(data.get("name", entry))
                info["classes"] = len(data.get("classes", []))
            except (OSError, ValueError):
                pass
        out.append(info)
    return out
