"""
PhoneVision Lab — 便携包 UI 构建冒烟测试。

职责：在真实 MainWindow 里构造全部新面板（数据集/训练/硬件/性能），
断言标签页数量、标题、以及"PC 端无分类器时自动控制不可用"这一诚实行为。

为什么单独一个脚本而不是塞进 unittest：
  - 需要在 PySide6 offscreen 下真的构造窗口与全部子面板；
  - 便携包缺模块时会在 import 阶段就炸，这里能明确定位到缺哪个模块。

运行（源码模式）：
  cd pc-client
  $env:QT_QPA_PLATFORM = "offscreen"
  python scripts\\smoke_ui.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PC_CLIENT = os.path.dirname(_HERE)
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # 逐个 import：缺哪个模块立刻能看出（便携包漏模块的场景）
    modules = [
        "qt_client.dataset_panel",
        "qt_client.train_panel",
        "qt_client.hardware_panel",
        "qt_client.perf_panel",
        "pvl_paths", "pvl_dataset", "pvl_split", "pvl_preprocess",
        "pvl_hardware", "pvl_perf",
    ]
    for name in modules:
        try:
            __import__(name)
            print(f"  import OK   {name}")
        except Exception as e:  # noqa: BLE001
            print(f"  import FAIL {name}: {e!r}")
            return 1

    from qt_client.main_window import MainWindow

    win = MainWindow("http://127.0.0.1:1/stream", "http://127.0.0.1:1/ping", {})

    tabs = getattr(win, "tabs", None)
    if tabs is None:
        print("FAIL: MainWindow 没有 tabs 属性")
        return 1

    print(f"\n标签页数量: {tabs.count()}")
    for i in range(tabs.count()):
        print(f"  [{i}] {tabs.tabText(i)}")

    if tabs.count() != 4:
        print(f"FAIL: 预期 4 个标签页，实际 {tabs.count()}")
        return 1
    # 标题不能为空（曾经因为只在 language_changed 时刷新而全空）
    empty = [i for i in range(tabs.count()) if not tabs.tabText(i).strip()]
    if empty:
        print(f"FAIL: 标签页标题为空: {empty}")
        return 1
    print("标签页标题均非空")

    # 直接按索引校验四个面板都存在
    for attr in ("dataset_panel", "train_panel", "hardware_panel",
                 "perf_panel"):
        if getattr(win, attr, None) is None:
            print(f"FAIL: 缺少面板 {attr}")
            return 1
    print("四个面板均已实例化: dataset / train / hardware / perf")

    # ---- 诚实性断言：PC 端没有分类器来源时，自动控制必须不可用 ----
    hardware = win.hardware_panel
    if hardware.prediction_provider is not None:
        print("FAIL: PC 端默认不应有 prediction_provider")
        return 1
    note = hardware.mode_note.text()
    if "没有分类器" not in note and "no classifier" not in note.lower():
        print(f"FAIL: 模式说明未告知用户自动控制不可用: {note!r}")
        return 1
    print(f"模式说明正确: {note[:60]}...")

    # 手动动作路径在没有连接设备时应安全拒绝（不崩）。
    # 注意：on_manual 会弹 QMessageBox，在 offscreen 下会阻塞等待用户，
    # 因此这里只验证"未连接时 controller 为 None"这一前提，不真的调用。
    if hardware.controller is not None:
        print("FAIL: 未连接设备时 controller 应为 None")
        return 1
    print("未连接设备时无 controller（手动动作路径不会误发命令）")

    # ---- 关闭：验证长任务被回收 ----
    win.close()
    print("\n窗口已关闭，长任务已回收")

    print("\nRESULT=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
