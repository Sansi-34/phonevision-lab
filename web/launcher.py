"""
PhoneVision Lab Web — 便携版启动器（双击 EXE 后运行）。

职责：在冻结（PyInstaller onedir）与源码两种环境下都能：
  1. 找到真实的前端静态资源目录（frozen 下在 sys._MEIPASS，源码下在 web/static）；
  2. 在后台线程启动本地 HTTP 服务（默认 127.0.0.1:8088）；
  3. 服务就绪后打开系统默认浏览器；
  4. 显示一个"正在运行"的提示窗口，关闭窗口即停止服务。

为什么不用 http.server 的 __main__：
  - `python -m web.server` 面向开发者（有终端、要看日志、要指定 --host/--port）；
  - 便携版面向学生：双击 → 浏览器自动打开 → 用完关窗口。没有终端也能用。

为什么静态资源路径要单独处理：
  - frozen 下模块的 __file__ 指向临时解包目录 sys._MEIPASS，web/static 就在那里；
  - 源码下 __file__ 就在仓库里。两处都要能定位，否则前端 404。

安全边界：默认只监听 127.0.0.1（仅本机）。需要局域网共享时由开发者在
源码模式下显式 `python -m web.server --host 0.0.0.0`，便携版不开放这个选项，
避免学生在公共 Wi-Fi 下无意暴露无认证的接口。
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser


def is_frozen() -> bool:
    """是否运行在 PyInstaller 冻结环境中。"""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def static_dir() -> str:
    """定位前端静态资源目录（frozen 与源码两种环境）。"""
    if is_frozen():
        return os.path.join(sys._MEIPASS, "static")
    # 源码：web/launcher.py 的上一级是 web/，static 在其下。
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def repo_root() -> str:
    """定位仓库根目录（frozen 下 import path 已由 spec 注入，源码下推导）。"""
    if is_frozen():
        # frozen 下 _MEIPASS 里有 pc-client 与 server；源码路径只用于日志。
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log_dir() -> str:
    """本地日志目录（与桌面客户端同一约定：%LOCALAPPDATA%\\PhoneVisionLab\\logs）。"""
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA") or os.path.expanduser(
            "~\\AppData\\Local")
        base = os.path.join(local, "PhoneVisionLab", "logs")
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share",
                            "PhoneVisionLab", "logs")
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        return ""
    return base


class ServiceHandle:
    """本地 HTTP 服务的启动/停止句柄。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8088):
        self.host = host
        self.port = port
        self.server = None
        self.thread = None
        self.error: str = ""

    def start(self) -> bool:
        try:
            # 延迟 import：frozen 下 Analysis 已收集 server 包，这里只触发加载。
            from server.app import create_server
        except Exception as exc:  # noqa: BLE001 - 启动失败要能看到原因
            self.error = f"无法加载服务模块: {exc}"
            return False
        try:
            self.server = create_server(self.host, self.port)
        except OSError as exc:
            # 端口被占用是最常见的情况：给一句可操作的话。
            self.error = (f"端口 {self.port} 已被占用（{exc}）。"
                          f"请关闭占用该程序的窗口后重试。")
            return False
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True, name="pvl-web-service")
        self.thread.start()
        return True

    def stop(self) -> None:
        if self.server is not None:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:  # noqa: BLE001 - 停止失败不影响退出
                pass

    def wait_ready(self, timeout: float = 10.0) -> bool:
        """轮询 /api/health 直到服务就绪（不靠固定 sleep，更快也更可靠）。"""
        import urllib.request
        url = f"http://{self.host}:{self.port}/api/health"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1.0) as response:
                    if response.status == 200:
                        return True
            except Exception:  # noqa: BLE001 - 还没起来，继续等
                pass
            time.sleep(0.15)
        return False


def _write_log(text: str) -> None:
    directory = log_dir()
    if not directory:
        return
    try:
        path = os.path.join(directory, "phonevision-web.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
    except OSError:
        pass


def show_window(handle: ServiceHandle, url: str) -> int:
    """显示"服务正在运行"窗口（Tkinter：标准库自带，frozen 下也无需额外依赖）。"""
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title("PhoneVision Lab Web")
    root.geometry("460x240")
    root.minsize(420, 220)
    root.configure(bg="#0E1116")

    frame = tk.Frame(root, bg="#0E1116", padx=20, pady=18)
    frame.pack(fill="both", expand=True)

    tk.Label(frame, text="PhoneVision Lab Web", bg="#0E1116", fg="#E6EAF0",
             font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w")
    tk.Label(frame, text="视觉 AI 学习与实践平台", bg="#0E1116", fg="#9AA5B4",
             font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(2, 14))

    tk.Label(frame, text="本地服务已启动：", bg="#0E1116", fg="#9AA5B4",
             font=("Microsoft YaHei UI", 10)).pack(anchor="w")
    tk.Label(frame, text=url, bg="#0E1116", fg="#22D3EE",
             font=("Consolas", 11)).pack(anchor="w", pady=(2, 14))

    tk.Label(
        frame,
        text=("关闭本窗口即停止服务。\n"
              "手机需在同一局域网，并先在 App 点击“开始推流”。\n"
              "本服务只监听本机 127.0.0.1，其他设备无法访问。"),
        bg="#0E1116", fg="#6B7684", justify="left",
        font=("Microsoft YaHei UI", 9),
    ).pack(anchor="w")

    def on_close():
        if messagebox.askokcancel("退出", "关闭窗口会停止本地服务，确定退出吗？"):
            handle.stop()
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    return 0


def main() -> int:
    handle = ServiceHandle()
    if not handle.start():
        message = handle.error or "服务启动失败"
        _write_log("start failed: " + message)
        # 无窗口环境下也要让用户看到原因（双击 EXE 时 messagebox 就是唯一输出）。
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("PhoneVision Lab Web 启动失败", message)
            root.destroy()
        except Exception:  # noqa: BLE001
            print(message, file=sys.stderr)
        return 1

    url = f"http://{handle.host}:{handle.port}"
    _write_log(f"service started at {url}")

    if not handle.wait_ready():
        handle.stop()
        message = "服务未能在 10 秒内就绪，请重试或查看日志。"
        _write_log(message)
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("PhoneVision Lab Web", message)
            root.destroy()
        except Exception:  # noqa: BLE001
            print(message, file=sys.stderr)
        return 1

    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - 打不开浏览器不影响服务运行
        _write_log("webbrowser.open failed")

    try:
        return show_window(handle, url)
    finally:
        handle.stop()
        _write_log("service stopped")


if __name__ == "__main__":
    sys.exit(main())
