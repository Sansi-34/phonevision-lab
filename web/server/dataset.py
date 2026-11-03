"""
PhoneVision Lab Web — 数据集服务（创建/类别/采集/体检/划分/缩略图）。

职责：把 pvl_dataset / pvl_split 的能力暴露给网页，采集帧来自 DeviceSession
（真实手机流），不引入第二套数据存储。

为什么这样设计：
  - 复用 pvl_dataset.DatasetStore：目录结构、batch 划分、原子写 dataset.json
    全部与桌面客户端一致，网页只是新客户端，不改写用户已有数据。
  - 采集用 store.start_batch/save_frame/end_batch，与 dataset_panel 同一套 API；
    帧号去重（同一帧不重复存）也沿用同样语义。
  - 体检/划分直接调 pvl_split.check_dataset / split_dataset：问题与警告文案
    来自同一处实现，避免网页和桌面端给出不同结论。
"""
from __future__ import annotations

import io
import os
import sys
import threading

_PC_CLIENT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "pc-client")
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

from .util import (  # noqa: E402
    ApiError, ERR_BAD_REQUEST, ERR_NOT_FOUND, ERR_NO_FRAME, is_image_file,
    safe_path_join,
)

# 缩略图缓存大小上限（避免长期运行占用内存）。
_THUMB_CACHE_LIMIT = 512

# 数据集内样本图片所在的子目录名（与 pvl_dataset.IMAGES_DIR_NAME 一致）。
_IMAGES_DIR_NAME = "images"


def _within(root: str, target: str) -> bool:
    """target 是否位于 root 之下（大小写不敏感，拒绝跨盘/非法路径）。"""
    try:
        root_key = os.path.normcase(os.path.abspath(root))
        target_key = os.path.normcase(os.path.abspath(target))
        return os.path.commonpath([root_key, target_key]) == root_key
    except (OSError, ValueError):
        return False


class DatasetService:
    """数据集操作 + 采集会话状态。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._store = None
        self._batch = None
        self._captured = 0
        self._last_frame_number = None
        self._capturing = False
        self._thumbs: dict = {}

    # ------------------------------------------------------------------
    # 列表 / 打开 / 创建
    # ------------------------------------------------------------------

    def list_datasets(self) -> list:
        from pvl_dataset import list_datasets
        out = []
        for info in list_datasets():
            out.append({
                "name": info.get("name", ""),
                "root": info.get("root", ""),
                "classes": int(info.get("classes", 0) or 0),
                "samples": self._count_samples(info.get("root", "")),
            })
        return out

    @staticmethod
    def _count_samples(root: str) -> int:
        if not root or not os.path.isdir(root):
            return 0
        total = 0
        images = os.path.join(root, "images")
        if not os.path.isdir(images):
            return 0
        for _base, _dirs, files in os.walk(images):
            total += sum(1 for f in files if f.lower().endswith(
                (".jpg", ".jpeg", ".png")))
        return total

    def open(self, root: str) -> dict:
        """打开数据集：root 必须落在数据目录 datasets_dir() 之内。

        这是安全边界而不是便利性检查：/api/datasets/open 接受前端传入的任意
        路径，若不限定范围，任意本地目录都会被当成数据集写入 dataset.json。
        """
        from pvl_dataset import DatasetStore
        target = self._validated_root(root)
        if not os.path.isdir(target):
            raise ApiError(ERR_BAD_REQUEST, "数据集目录不存在")
        with self._lock:
            self._stop_capture_locked()
            store = DatasetStore(target)
            dataset = store.open(target)
            self._store = store
        return self.describe()

    @staticmethod
    def _validated_root(root: str) -> str:
        """规范化并校验数据集目录（禁止 UNC、路径穿越与数据目录外路径）。"""
        from pvl_paths import datasets_dir
        raw = str(root or "").strip()
        if not raw:
            raise ApiError(ERR_BAD_REQUEST, "数据集目录不能为空")
        # Windows: \\server\share、\\?\C:\... 以及 //server/share 都是网络/设备路径。
        # 这些路径会绕开本地目录语义（也可能触发 SMB 认证），一律拒绝。
        if raw.replace("/", "\\").startswith("\\\\"):
            raise ApiError(ERR_BAD_REQUEST, "不支持 UNC/网络路径，请使用本机数据集目录")
        try:
            base = os.path.realpath(datasets_dir())
            target = os.path.realpath(os.path.abspath(os.path.normpath(raw)))
        except (OSError, ValueError):
            raise ApiError(ERR_BAD_REQUEST, "数据集目录不合法")
        base_key = os.path.normcase(base)
        target_key = os.path.normcase(target)
        try:
            inside = (os.path.commonpath([base_key, target_key]) == base_key
                      and target_key != base_key)
        except (OSError, ValueError):
            inside = False
        if not inside:
            raise ApiError(ERR_BAD_REQUEST,
                           "只能打开数据目录下的数据集（禁止任意本地路径）")
        return target

    def create(self, name: str, class_names: list | None = None) -> dict:
        from pvl_dataset import DatasetStore
        from pvl_paths import datasets_dir
        name = (name or "").strip()
        if not name:
            raise ApiError("bad_request", "数据集名称不能为空")
        try:
            safe = DatasetStore.sanitize_name(name)
        except ValueError as exc:
            raise ApiError("bad_request", str(exc))
        root = os.path.join(datasets_dir(), safe)
        with self._lock:
            self._stop_capture_locked()
            store = DatasetStore(root)
            try:
                store.create(name, class_names or [])
            except Exception as exc:  # noqa: BLE001
                raise ApiError("bad_request", f"创建数据集失败: {exc}")
            self._store = store
        return self.describe()

    def current(self) -> dict:
        if self._store is None:
            raise ApiError("no_dataset", "还没有打开数据集，请先创建或选择一个数据集")
        return self.describe()

    def describe(self) -> dict:
        store = self._store
        if store is None or store.dataset is None:
            return {"opened": False, "name": "", "root": "", "classes": [],
                    "total_samples": 0, "capturing": self._capturing,
                    "captured_in_batch": self._captured,
                    "current_batch": None}
        dataset = store.dataset
        counts = dataset.class_counts()
        classes = []
        for info in dataset.classes:
            batches = dataset.batches_for(info.name)
            classes.append({
                "name": info.name,
                "display_name": info.display_name or info.name,
                "count": counts.get(info.name, 0),
                "batches": len(batches),
            })
        return {
            "opened": True,
            "name": dataset.name,
            "root": dataset.root,
            "classes": classes,
            "total_samples": sum(counts.values()),
            "capturing": self._capturing,
            "captured_in_batch": self._captured,
            "current_batch": (self._batch.batch_id if self._batch else None),
        }

    # ------------------------------------------------------------------
    # 类别
    # ------------------------------------------------------------------

    def add_class(self, display_name: str) -> dict:
        store = self._require_store()
        raw = (display_name or "").strip()
        if not raw:
            raise ApiError("bad_request", "类别名称不能为空")
        try:
            store.dataset.add_class(raw)
            store.save()
        except ValueError as exc:
            raise ApiError("bad_request", str(exc))
        return self.describe()

    def rename_class(self, name: str, new_display: str) -> dict:
        store = self._require_store()
        try:
            store.dataset.rename_class(name, (new_display or "").strip())
            store.save()
        except ValueError as exc:
            raise ApiError("bad_request", str(exc))
        return self.describe()

    def remove_class(self, name: str) -> dict:
        store = self._require_store()
        try:
            store.dataset.remove_class(name)
            store.save()
        except ValueError as exc:
            raise ApiError("bad_request", str(exc))
        return self.describe()

    # ------------------------------------------------------------------
    # 采集
    # ------------------------------------------------------------------

    def capture_one(self, device_session, class_name: str = "") -> dict:
        """采集一帧。没有打开数据集/类别时给出明确原因。"""
        store = self._require_store()
        dataset = store.dataset
        selected = class_name or self._selected_class or self._default_class()
        if not selected:
            raise ApiError("bad_request",
                           "数据集里还没有类别，请先添加至少一个类别再采集")
        if dataset.get_class(selected) is None:
            raise ApiError("bad_request", f"类别不存在: {selected}")
        frame, number = self._fresh_frame(device_session)
        with self._lock:
            if self._batch is None or self._batch.class_name != selected:
                self._batch = store.start_batch(selected)
                self._captured = 0
            self._save_frame(store, selected, frame, number)
            self._captured += 1
            batch_id = self._batch.batch_id
        return {"captured": self._captured, "batch_id": batch_id,
                "dataset": self.describe()}

    def start_capture(self, device_session, class_name: str = "") -> dict:
        store = self._require_store()
        selected = class_name or self._selected_class or self._default_class()
        if not selected:
            raise ApiError("bad_request",
                           "数据集里还没有类别，请先添加至少一个类别再采集")
        if store.dataset.get_class(selected) is None:
            raise ApiError("bad_request", f"类别不存在: {selected}")
        # 立即验证一次可采性，失败时给出真实原因（不进入假采集状态）
        self._fresh_frame(device_session)
        with self._lock:
            if self._batch is None or self._batch.class_name != selected:
                self._batch = store.start_batch(selected)
                self._captured = 0
            self._capturing = True
        return self.describe()

    def stop_capture(self) -> dict:
        store = self._store
        with self._lock:
            batch = self._batch
            self._capturing = False
        if store is not None and batch is not None:
            # 结束批次：与 dataset_panel 一样只做落盘计数，不删除已存图片
            try:
                store.end_batch(batch.class_name, batch.batch_id)
            except Exception:  # noqa: BLE001 - 结束失败不影响已保存图片
                pass
        return self.describe()

    def _stop_capture_locked(self) -> None:
        self._capturing = False

    # 采集目标类别由调用方显式传入（按钮携带 class_name），未传时用上一次选择
    _selected_class = ""
    _last_class = ""
    _last_batch_id = ""

    def _fresh_frame(self, device_session):
        """取一帧可采集的新画面。

        两种"没有画面"都要区分：
          - 设备抛 not_connected/no_frame：直接向上传递（连接问题）；
          - 设备返回 (None, None)：AppModel 判定帧陈旧，转成明确提示。
        """
        frame, number = device_session.latest_frame()
        if frame is None or number is None:
            raise ApiError(ERR_NO_FRAME,
                           "当前没有可用画面：请确认手机正在推流且网络正常")
        if number == self._last_frame_number:
            raise ApiError(ERR_NO_FRAME,
                           "摄像头还没有送出新的画面，请稍候再试（避免同一帧重复入库）")
        self._last_frame_number = number
        return frame, number

    def _save_frame(self, store, class_name, frame, number):
        import cv2
        ok, buffer = cv2.imencode(".jpg", frame,
                                  [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            raise ApiError("internal_error", "JPEG 编码失败")
        store.save_frame(class_name, self._batch.batch_id, buffer.tobytes())
        self._last_class = class_name
        self._last_batch_id = self._batch.batch_id

    # ------------------------------------------------------------------
    # 样本浏览 / 删除
    # ------------------------------------------------------------------

    def samples(self, class_name: str | None = None) -> list:
        store = self._require_store()
        dataset = store.dataset
        names = [class_name] if class_name else dataset.class_names()
        out = []
        for name in names:
            if dataset.get_class(name) is None:
                raise ApiError("bad_request", f"类别不存在: {name}")
            for rel in dataset.list_samples(name):
                parts = rel.replace("\\", "/").split("/")
                batch_id = parts[1] if len(parts) >= 3 else "loose"
                out.append({
                    "path": rel,
                    "class": name,
                    "batch": batch_id,
                    "url": f"/api/datasets/samples/image?path={rel}",
                })
        return out

    def _resolve_sample(self, relative_path: str) -> str:
        """把样本相对路径解析成磁盘文件，只允许 <root>/images/** 下的图片。

        非图片（secret.txt、dataset.json 等）与越界路径统一按"样本不存在"
        返回 404：既不泄露文件是否存在，也不给任意文件读取/删除留入口。
        """
        store = self._require_store()
        raw = str(relative_path or "").strip()
        not_found = ApiError(ERR_NOT_FOUND, f"样本不存在: {relative_path}", 404)
        if not raw:
            raise not_found
        parts = [p for p in raw.replace("\\", "/").split("/") if p not in ("", ".")]
        if (len(parts) < 2 or parts[0] != _IMAGES_DIR_NAME
                or any(p == ".." for p in parts) or not is_image_file(parts[-1])):
            raise not_found
        try:
            target = safe_path_join(store.root, *parts)
        except ApiError:
            raise not_found
        images_root = os.path.join(store.root, _IMAGES_DIR_NAME)
        try:
            inside = _within(os.path.realpath(images_root),
                             os.path.realpath(target))
        except (OSError, ValueError):
            inside = False
        if not inside:
            raise not_found
        if not os.path.isfile(target):
            raise not_found
        return target

    def sample_image(self, relative_path: str) -> bytes:
        target = self._resolve_sample(relative_path)
        try:
            with open(target, "rb") as fh:
                return fh.read()
        except OSError:
            raise ApiError(ERR_NOT_FOUND, f"样本不存在: {relative_path}", 404)

    def delete_sample(self, relative_path: str) -> dict:
        store = self._require_store()
        self._resolve_sample(relative_path)
        try:
            store.dataset.delete_sample(relative_path)
            store.save()
        except ValueError as exc:
            raise ApiError(ERR_NOT_FOUND, str(exc), 404)
        return self.describe()

    # ------------------------------------------------------------------
    # 体检 / 划分
    # ------------------------------------------------------------------

    def check(self) -> dict:
        from pvl_split import check_dataset
        store = self._require_store()
        problems, warnings = check_dataset(store.dataset)
        counts = store.dataset.class_counts()
        return {
            "problems": list(problems),
            "warnings": list(warnings),
            "class_counts": counts,
            "total": sum(counts.values()),
            "ready": not problems,
        }

    def split(self, val_ratio: float = 0.2, seed: int = 1234) -> dict:
        from pvl_split import save_split, split_dataset
        store = self._require_store()
        try:
            result = split_dataset(store.dataset, val_ratio=val_ratio, seed=seed)
        except Exception as exc:  # noqa: BLE001
            raise ApiError("bad_request", f"划分失败: {exc}")
        split_path = os.path.join(store.root, "split.json")
        save_split(result, split_path)
        return {
            "train": len(result.train),
            "val": len(result.val),
            "train_by_class": result.class_counts("train"),
            "val_by_class": result.class_counts("val"),
            "seed": result.seed,
            "val_ratio": result.val_ratio,
            "problems": list(result.problems),
            "warnings": list(result.warnings),
            "split_path": split_path,
        }

    def split_status(self) -> dict:
        from pvl_split import load_split
        store = self._require_store()
        path = os.path.join(store.root, "split.json")
        if not os.path.isfile(path):
            return {"exists": False}
        try:
            result = load_split(path)
        except (OSError, ValueError) as exc:
            return {"exists": False, "error": str(exc)}
        return {
            "exists": True,
            "train": len(result.train),
            "val": len(result.val),
            "seed": result.seed,
            "val_ratio": result.val_ratio,
            "problems": list(result.problems),
            "warnings": list(result.warnings),
            "path": path,
        }

    # ------------------------------------------------------------------

    def _require_store(self):
        if self._store is None or self._store.dataset is None:
            raise ApiError("no_dataset", "还没有打开数据集，请先创建或选择一个数据集")
        return self._store

    def _default_class(self) -> str:
        """打开数据集后默认选中第一个类别（与桌面客户端行为一致）。"""
        store = self._store
        if store is None or store.dataset is None:
            return ""
        names = store.dataset.class_names()
        return names[0] if names else ""

    def select_class(self, class_name: str) -> None:
        """设置采集目标类别；传空时回落到第一个类别。"""
        self._selected_class = class_name or self._default_class()
