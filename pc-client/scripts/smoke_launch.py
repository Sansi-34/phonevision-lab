"""
PhoneVision Lab — 启动链路确定性验证（offscreen，不弹窗、不阻塞）。

验证 start.cmd / start-training.cmd 实际走的同一条路径：
    scripts\local_tasks.ps1 -Task Run|TrainRun
        -> & $env:PVL_PYTHON main.py
            -> qt_client.main.main()

这里不真正进入 Qt 事件循环（会永久阻塞），而是：
  1. 解析 .local\environment.ps1 拿到的 PVL_PYTHON；
  2. 确认该 Python 能 import 客户端入口模块；
  3. 确认 main.py 可被 import（即入口无语法/导入错误）；
  4. 确认 QApplication + 连接对话框可构造（启动页能出来）。

运行：
  cd pc-client
  python scripts\smoke_launch.py
"""
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PC_CLIENT = os.path.dirname(_HERE)
_PROJECT = os.path.dirname(_PC_CLIENT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def read_local_python() -> str:
    """从 .local\environment.ps1 里取 PVL_PYTHON（与 local_tasks.ps1 同源）。"""
    cfg = os.path.join(_PROJECT, ".local", "environment.ps1")
    if not os.path.isfile(cfg):
        return ""
    with open(cfg, encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith("$env:PVL_PYTHON"):
                # 形如: $env:PVL_PYTHON = Join-Path (Split-Path -Parent $PSScriptRoot) 'pc-client\.venv-build\Scripts\python.exe'
                tail = s.split("Join-Path", 1)[-1]
                parts = [p.strip().strip("'\"") for p in tail.split()]
                parts = [p for p in parts if p and "Split-Path" not in p
                         and "PSScriptRoot" not in p and p != ")"
                         and "(" not in p]
                if parts:
                    rel = parts[-1].replace("\\", os.sep).replace("/", os.sep)
                    return os.path.normpath(os.path.join(_PROJECT, rel))
    return ""


def main() -> int:
    print("== 1. 定位 local_tasks.ps1 会用的 Python ==")
    py = read_local_python()
    print(f"   PVL_PYTHON (start.cmd)        = {py or '(未解析到)'}")
    train_py = os.path.join(_PC_CLIENT, ".venv-train", "Scripts", "python.exe")
    print(f"   PVL_PYTHON (start-training)   = {train_py}")

    candidates = [p for p in (py, train_py) if p and os.path.isfile(p)]
    if not candidates:
        print("FAIL: 找不到可用的 Python 解释器")
        return 1

    print("\n== 2. 用各解释器 import 客户端入口 ==")
    for exe in candidates:
        label = ("start.cmd" if exe == py else "start-training.cmd")
        code = (
            "import sys; sys.path.insert(0, %r); "
            "import main; "
            "import qt_client.main; "
            "print('OK ' + %r)" % (_PC_CLIENT, label)
        )
        r = subprocess.run([exe, "-c", code], capture_output=True, text=True,
                           timeout=180, cwd=_PC_CLIENT)
        out = (r.stdout or "").strip().splitlines()
        tail = out[-1] if out else ""
        if r.returncode != 0:
            err = (r.stderr or "").strip().splitlines()
            print(f"   FAIL {label}: {err[-1] if err else 'unknown'}")
            return 1
        print(f"   {tail}  ({os.path.basename(os.path.dirname(os.path.dirname(exe)))})")

    print("\n== 3. 构造 QApplication + 启动页连接对话框 ==")
    code = (
        "import sys; sys.path.insert(0, %r); "
        "from PySide6.QtWidgets import QApplication; "
        "app = QApplication(sys.argv); "
        "from qt_client.connection_dialog import ConnectionDialog; "
        "from qt_client.i18n import Translator; "
        "d = ConnectionDialog(translator=Translator()); "
        "print('DIALOG_OK', d.windowTitle())" % _PC_CLIENT
    )
    r = subprocess.run([candidates[-1], "-c", code], capture_output=True,
                       text=True, timeout=180, cwd=_PC_CLIENT)
    tail = ((r.stdout or "").strip().splitlines() or [""])[-1]
    if r.returncode != 0 or not tail.startswith("DIALOG_OK"):
        err = (r.stderr or "").strip().splitlines()
        print(f"   FAIL: {err[-1] if err else 'unknown'}")
        return 1
    print(f"   {tail}")

    print("\n== 4. 构造主窗口（四个新面板 + 标签页标题） ==")
    code = (
        "import sys; sys.path.insert(0, %r); "
        "from PySide6.QtWidgets import QApplication; "
        "app = QApplication(sys.argv); "
        "from qt_client.main_window import MainWindow; "
        "w = MainWindow('http://127.0.0.1:1/stream', 'http://127.0.0.1:1/ping', {}); "
        "titles = [w.tabs.tabText(i) for i in range(w.tabs.count())]; "
        "assert w.tabs.count() == 4, titles; "
        "assert all(t.strip() for t in titles), titles; "
        "w.close(); "
        "print('MAINWINDOW_OK', '|'.join(titles))" % _PC_CLIENT
    )
    r = subprocess.run([candidates[-1], "-c", code], capture_output=True,
                       text=True, timeout=240, cwd=_PC_CLIENT)
    tail = ((r.stdout or "").strip().splitlines() or [""])[-1]
    if r.returncode != 0 or not tail.startswith("MAINWINDOW_OK"):
        err = (r.stderr or "").strip().splitlines()
        print(f"   FAIL: {err[-1] if err else 'unknown'}")
        return 1
    print(f"   {tail}")

    print("\nRESULT=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
