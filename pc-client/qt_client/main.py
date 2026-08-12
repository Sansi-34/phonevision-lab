"""
PhoneVision Lab — PySide6 桌面客户端入口（正式默认）。

职责：解析命令行参数（手机 IP/端口或完整流地址、语言）、用 connection 模块做
/ping 预检、加载 QSS 主题、初始化 Translator 与全局字体、启动 MainWindow。
这是"产品级"客户端的大门，也是 root main.py 委托的对象。

为什么这样设计：
  - URL 构造与 /ping 预检统一走 pc-client/connection.py（与 Legacy Tkinter 入口共用）。
  - 支持 `python -m qt_client.main`（包内相对导入），不依赖从特定子目录启动。
  - root `python main.py` 是默认入口，本模块是其委托实现。
  - 语言解析：--lang 命令行 > QSettings 保存 > 系统 locale；首次启动按系统 locale 选择。
  - P0-5A 无参数启动：打包成 windowed EXE 后没有终端，双击时若仍强制 --host 会
    argparse 报错直接退出。因此 --host/--stream-url 改为可选：
      有参数   → 保持原有直接连接行为（ping 成功直接 MainWindow；失败在源码有
                  终端时打印错误，但 GUI 仍打开预填地址的 ConnectionDialog 让用户修正，
                  windowed EXE 绝不无提示退出）。
      无参数   → 创建 QApplication 后打开 ConnectionDialog（启动页），用户输入
                  手机 IP/端口、后台 /ping 成功后创建 MainWindow。全程不退出到终端。

常用命令：
  python main.py --host 192.168.x.x            # 中文（按系统/保存）
  python main.py --host 192.168.x.x --lang en  # 英文
  python -m qt_client.main --host 192.168.x.x --lang zh-CN
  python main.py                               # 双击式：打开启动页手动连接
"""
from __future__ import annotations

import os
import sys

# 让 import 能找到 pc-client 根目录下的 mjpeg_reader / vision_modes / app_model
_PC_CLIENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

import argparse

from PySide6.QtWidgets import QApplication

import connection
from qt_client.main_window import MainWindow


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="PhoneVision Lab 桌面客户端（PySide6 工作台）")
    # 可选互斥组：无参数时不报错退出（双击启动页语义），有任一参数时二者互斥。
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--host", help="手机局域网 IP，如 192.168.2.14")
    group.add_argument("--stream-url", help="完整流地址，如 http://192.168.2.14:8080/stream")
    parser.add_argument("--port", type=int, default=8080, help="手机 HTTP 端口（默认 8080）")
    parser.add_argument("--lang", choices=["zh-CN", "en"], default=None,
                        help="界面语言：zh-CN 或 en（默认按系统/保存语言）")
    return parser.parse_args(argv)


def _system_language() -> str:
    """按系统 locale 推断语言：含 zh 前缀 -> zh-CN，否则 en。"""
    try:
        import locale
        loc = locale.getlocale()[0] or locale.getdefaultlocale()[0] or "en_US"
    except Exception:
        loc = "en_US"
    return "zh-CN" if str(loc).lower().startswith("zh") else "en"


def _load_theme(app) -> None:
    """加载 style.qss 深色主题（失败不阻塞，退回默认外观）。

    必须用 resources.resource_path()：frozen（PyInstaller onedir）下模块的
    __file__ 不可靠，资源在 sys._MEIPASS/qt_client/ 下（见 spec datas）。
    """
    try:
        from qt_client.resources import style_qss_path
        qss_path = style_qss_path()
        app.setStyleSheet(open(qss_path, encoding="utf-8").read())
    except FileNotFoundError:
        print("警告: 找不到 style.qss，使用默认外观。")


def _make_translator(args) -> "Translator":
    """构造并初始化 Translator：--lang > QSettings 保存 > 系统 locale。"""
    from qt_client.i18n import Translator
    tr = Translator(initial_language="zh-CN")
    saved = tr.language()  # Translator 构造时若 QSettings 有保存值会优先
    lang = tr.resolve_initial_language(args.lang, saved, _system_language())
    tr.set_language(lang, persist=False)
    return tr


def _make_application() -> QApplication:
    """创建 QApplication，加载主题与日志配置。

    logging_config.py 由另一 agent 提供（setup_logging 需要 QApplication 已创建）；
    若该模块缺失或异常，降级跳过，不阻塞启动。
    """
    app = QApplication(sys.argv)
    _load_theme(app)

    try:
        from qt_client.logging_config import setup_logging, log_startup
        logger = setup_logging()
        log_startup(logger)  # 记录版本/启动时间到本地日志（windowed EXE 无终端）
    except Exception:  # noqa: BLE001 - 日志配置失败绝不阻塞启动
        pass

    return app


def _apply_language_and_font(app, lang) -> Translator:
    """按解析出的语言设置全局字体，返回 Translator（供窗口/对话框复用）。"""
    from qt_client.i18n import Translator
    from qt_client.fonts import apply_application_font
    tr = Translator(initial_language="zh-CN")
    saved = tr.language()
    final_lang = tr.resolve_initial_language(lang, saved, _system_language())
    tr.set_language(final_lang, persist=False)
    apply_application_font(app, final_lang)
    return tr


def _print_device_info(ping_info) -> None:
    """把 /ping 设备信息打印到 stdout（源码运行时可见，windowed EXE 无终端则忽略）。"""
    print(f"手机: {ping_info.get('device', '?')}  "
          f"{ping_info.get('width', '?')}x{ping_info.get('height', '?')}  "
          f"采集FPS:{ping_info.get('actualFps', '?')}  状态:{ping_info.get('status', '?')}")
    if ping_info.get("status") != "streaming":
        print("提示：手机当前未在推流，请先在 App 点击\"开始推流\"。")


def _run_connected(stream_url, ping_url, ping_info, tr) -> int:
    """直接连接：ping 已成功，创建并显示 MainWindow，进入事件循环。"""
    win = MainWindow(stream_url, ping_url, ping_info, translator=tr)
    win.show()
    return app_exec()


def app_exec() -> int:
    """进入 Qt 事件循环（独立函数便于测试不真正阻塞）。"""
    return QApplication.instance().exec()


def main(argv=None):
    args = parse_args(argv)

    if args.host or args.stream_url:
        # ---- 有参数：保持原有直接连接行为 ----
        stream_url, ping_url = connection.build_urls(
            host=args.host, port=args.port, stream_url=args.stream_url)

        result = connection.ping_device(ping_url)
        ping_info = result.info if result.success else None
        if result.success:
            _print_device_info(ping_info)
            print(f"流地址: {stream_url}")

        app = _make_application()
        tr = _apply_language_and_font(app, args.lang)

        if result.success:
            return _run_connected(stream_url, ping_url, ping_info, tr)

        # CLI 预检失败：源码有终端可打印错误，但 GUI 仍打开预填地址的
        # ConnectionDialog 让用户修正；windowed EXE 不能无提示退出。
        print(f"错误：{result.error}")
        return _run_dialog(app, tr, host=args.host, port=args.port)

    # ---- 无参数：双击启动页语义，全程不退出到终端 ----
    print("PhoneVision Lab：未指定 --host/--stream-url，打开启动页手动连接。")
    app = _make_application()
    tr = _apply_language_and_font(app, None)
    return _run_dialog(app, tr)


def _run_dialog(app, tr, host=None, port=None) -> int:
    """打开 ConnectionDialog，用户连接成功后创建 MainWindow。

    - 优先用最近一次成功连接的地址预填（QSettings）；若调用方显式传入
      host/port（CLI 预检失败的场景），则用 CLI 地址预填，用户可直接修正。
    - 对话框内部异步 /ping；成功时 emit connected(stream_url, ping_url)。
    - 迟到 worker 不会在窗口关闭后创建 MainWindow（ConnectionDialog 内已保证）。
    """
    from qt_client.connection_dialog import ConnectionDialog

    dialog = ConnectionDialog(translator=tr)
    dialog.prefill_last_address()
    if host:
        dialog.host_input.setText(host)
        if port:
            dialog.port_input.setText(str(port))

    def on_connected(stream_url, ping_url):
        print(f"流地址: {stream_url}")
        win = MainWindow(stream_url, ping_url, {}, translator=tr)
        win.show()

    dialog.connected.connect(on_connected)
    dialog.show()
    return app_exec()


if __name__ == "__main__":
    sys.exit(main())
