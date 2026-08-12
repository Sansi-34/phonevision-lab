"""
PhoneVision Lab — 一体化 Tkinter GUI 客户端。

职责：把"画面显示 + 命令台 + 状态栏"集成到一个窗口：
  - 顶部：视频画面区（嵌入 OpenCV 帧）
  - 左下：命令台（5 种模式按钮、参数滑块、保存/重连/退出）
  - 底部：状态栏（手机采集/PC接收/PC显示 FPS、状态、分辨率、带宽、丢帧、错误）

为什么这样设计：
  - Tkinter 是 Python 内置 GUI，零新增依赖，适合学习。
  - 相比"OpenCV 窗口 + 控制台窗口"分离，一体化窗口用滑块调参更直观（绕开
    OpenCV HighGUI 在高 DPI 下的 trackbar bug，用 Tkinter 的 Scale 控件）。
  - 后台用 mjpeg_reader 线程收帧（只留最新帧），主线程用 after() 定时刷新，
    互不阻塞，延迟不累积。
  - 视觉处理仍复用 vision_modes.apply_mode，GUI 只负责取帧、调参、显示。

初学者调试观察点：
  - 画面不动：看状态栏 state=Reconnecting，说明流断了在等重连。
  - 滑块调参没效果：确认当前模式是对应的（Canny 滑块只影响 Canny 模式）。
  - 处理慢：看"显示 FPS"明显低于"接收 FPS"。
"""
import threading
import time
import tkinter as tk
from tkinter import ttk

import cv2
import numpy as np

import app_model
import mjpeg_reader
import theme
import vision_modes


class PhoneVisionApp:
    def __init__(self, root, stream_url, ping_url, ping_info):
        self.root = root
        self.stream_url = stream_url
        self.ping_url = ping_url
        self.ping_info = ping_info

        root.title("PhoneVision Lab — 机器视觉学习客户端")
        root.geometry("900x720")
        root.configure(bg=theme.BG)

        # ---- 视觉状态 ----
        self._mode_buttons = {}  # key -> 按钮，用于选中态高亮
        self._chips = {}         # 指标名 -> value_var，状态栏仪表盘用
        self._card_canvases = []  # 记住圆角卡片 canvas，避免被 GC 回收

        # ---- 状态 ----
        self.mode = vision_modes.MODE_ORIGINAL
        self.params = dict(vision_modes.DEFAULT_PARAMS)
        self.stats = {
            "state": "Idle",
            "phone_fps": float(ping_info.get("actualFps", 0) or 0),
            "recv_fps": 0.0,
            "disp_fps": 0.0,
            "width": int(ping_info.get("width") or 0),
            "height": int(ping_info.get("height") or 0),
            "avg_jpeg_mb": 0.0,
            "throughput_mbps": 0.0,
            "received": 0,
            "invalid": 0,
            "dropped": 0,
            "error": "",
        }

        # ---- 共享客户端状态模型（网络 / 统计 / 生命周期唯一来源）----
        self.model = app_model.AppModel(
            stream_url=stream_url,
            ping_url=ping_url,
            device_name=str(ping_info.get("device", "")),
            width=int(ping_info.get("width") or 0),
            height=int(ping_info.get("height") or 0),
            phone_fps=float(ping_info.get("actualFps", 0) or 0),
        )
        self.model.start()
        # 兼容旧引用（部分方法仍用 self.reader）
        self.reader = self.model

        # ---- 构建界面 ----
        self._build_ui()
        # 启动即高亮默认模式（原始）的按钮，与选中态一致
        self.set_mode("1")

        # ---- 定时刷新 ----
        self._refresh_loop()

        # ---- 窗口关闭钩子：点 X 也走 quit()，确保 reader 线程被 stop ----
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

    # =====================================================================
    # 界面构建
    # =====================================================================

    def _build_ui(self):
        # ---------------------------------------------------------------
        # 整体布局：左侧命令台(约 250px) + 右侧画面区，底部整宽状态栏
        # ---------------------------------------------------------------
        # 底部：状态栏（指标小方块仪表盘）先占位，让画面区可 expand
        status = tk.Frame(self.root, bg=theme.BG)
        status.pack(side="bottom", fill="x", padx=12, pady=(0, 10))
        self._build_status_bar(status)

        # 右侧：画面区，占满剩余宽高
        right = tk.Frame(self.root, bg=theme.BG)
        right.pack(side="left", fill="both", expand=True, padx=(12, 12), pady=(14, 0))
        self._build_canvas_area(right)

        # 左侧：命令台（视觉模式 / 参数调节 / 操作 三张圆角卡片）
        cmd = tk.Frame(self.root, bg=theme.BG, width=250)
        cmd.pack(side="left", fill="y", padx=(12, 0), pady=(14, 0))
        cmd.pack_propagate(False)  # 固定 250px 宽，卡片按需撑高
        self._build_command_console(cmd)

    # ---------------------------------------------------------------
    # 子区域
    # ---------------------------------------------------------------

    def _build_canvas_area(self, parent):
        """顶部画面区：上边距拉开，纯黑显示区 + 细描边。"""
        pad = tk.Frame(parent, bg=theme.BG)  # 底部留白，和状态栏分开
        pad.pack(fill="both", expand=True)
        self.canvas = tk.Label(pad, bg=theme.CANVAS_BG,
                               highlightthickness=1, highlightbackground=theme.FRAME_BORDER)
        self.canvas.pack(fill="both", expand=True, pady=(0, 10))

    def _build_command_console(self, parent):
        """命令台：视觉模式、参数调节、操作 三张圆角卡片。"""
        # ---- 卡片一：视觉模式 ----
        card1, inner1 = self._rounded_card(parent)
        tk.Label(inner1, text="视觉模式", bg=theme.CARD, fg=theme.TEXT_DIM,
                 font=(theme.FONT_SEMIBOLD, theme.SIZE_GROUP)).pack(anchor="w")
        mode_row = tk.Frame(inner1, bg=theme.CARD)
        mode_row.pack(fill="x", pady=(4, 2))
        for key, label in [
            ("1", "原始"), ("2", "灰度"), ("3", "Canny"),
            ("4", "HSV"), ("5", "轮廓"),
        ]:
            self._mode_button(mode_row, label, key).pack(side="left", padx=(0, 4))

        self.mode_label = tk.Label(inner1, text="当前: 原始", bg=theme.CARD,
                                   fg=theme.PRIMARY_HOVER, font=(theme.FONT, theme.SIZE_LABEL))
        self.mode_label.pack(anchor="w", pady=(2, 0))

        # ---- 卡片二：参数调节 ----
        card2, inner2 = self._rounded_card(parent)
        self._build_sliders(inner2)

        # ---- 卡片三：操作 ----
        card3, inner3 = self._rounded_card(parent)
        tk.Label(inner3, text="操作", bg=theme.CARD, fg=theme.TEXT_DIM,
                 font=(theme.FONT_SEMIBOLD, theme.SIZE_GROUP)).pack(anchor="w", pady=(0, 4))
        tk.Button(inner3, text="保存 S", width=8, relief="flat", bd=0,
                  bg=theme.GREEN, fg="#08140f", activebackground=theme.PRIMARY,
                  activeforeground="#fff", command=self.save_capture,
                  font=(theme.FONT, theme.SIZE_GROUP)).pack(fill="x", pady=2)
        tk.Button(inner3, text="重连 R", width=8, relief="flat", bd=0,
                  bg=theme.AMBER, fg="#241a02", activebackground=theme.PRIMARY,
                  activeforeground="#fff", command=self.reconnect,
                  font=(theme.FONT, theme.SIZE_GROUP)).pack(fill="x", pady=2)
        tk.Button(inner3, text="退出 Q", width=8, relief="flat", bd=0,
                  bg=theme.RED, fg="#2a0a0a", activebackground=theme.PRIMARY,
                  activeforeground="#fff", command=self.quit,
                  font=(theme.FONT, theme.SIZE_GROUP)).pack(fill="x", pady=2)

        # 底部留白让卡片悬空，不与状态栏贴死
        tk.Frame(parent, bg=theme.BG, height=6).pack()

    def _build_status_bar(self, parent):
        """底部指标小方块仪表盘：小标签在上 + 大数值在下。"""
        self._chips = {}
        self._chip_frames = {}
        fields = [
            ("status", "状态", "Streaming"),
            ("phone_fps", "采集FPS", "--"),
            ("recv_fps", "接收FPS", "--"),
            ("disp_fps", "显示FPS", "--"),
            ("resolution", "分辨率", "--"),
            ("avg_jpeg_mb", "平均JPEG", "--"),
            ("throughput_mbps", "带宽", "--"),
            ("received", "接收帧", "0"),
            ("invalid", "无效帧", "0"),
            ("dropped", "丢帧", "0"),
        ]
        row = tk.Frame(parent, bg=theme.BG)
        row.pack(fill="x")
        for name, label, default in fields:
            frame, value_var = self._chip(row, label)
            value_var.set(default)
            self._chips[name] = value_var
            self._chip_frames[name] = frame
            frame.pack(side="left", padx=(0, 6))

    # ---------------------------------------------------------------
    # 视觉小工具
    # ---------------------------------------------------------------

    def _rounded_card(self, parent, radius=theme.RADIUS, bg=theme.CARD):
        """返回一个 (container_frame, inner_frame)，用于容纳子控件并画圆角背景。

        canvas 只负责画圆角矩形背景；子控件放进 inner，再铺满 canvas。
        注意：<Configure> 绑定必须合并成一个回调，否则后绑定会覆盖先绑定。
        """
        card = tk.Canvas(parent, bg=bg, highlightthickness=0, bd=0, height=10)
        card.pack(fill="x", pady=4, padx=0)
        inner = tk.Frame(card, bg=bg)
        card.create_window(0, 0, window=inner, anchor="nw", tags="win")

        def refresh(event=None):
            # 卡片宽度 = canvas 当前宽度；高度跟着 inner 内容自适应
            w = card.winfo_width() if event is None else event.width
            h = inner.winfo_reqheight() + 6
            card.itemconfigure("win", width=max(0, w - 6))
            card.delete("bg")
            self._draw_round_rect(card, 3, 3, max(0, w - 3), max(0, h - 3),
                                  radius, fill=bg, outline=theme.FRAME_BORDER, tags="bg")
            # 高度相同就不再 config，避免触发新的 <Configure> 造成抖动循环
            if card.winfo_height() != h:
                card.config(height=h)

        card.bind("<Configure>", refresh)
        inner.bind("<Configure>", refresh)  # 子控件增减后同步撑高卡片
        self._card_canvases.append(card)  # 防止 canvas 被垃圾回收
        return card, inner

    def _draw_round_rect(self, canvas, x1, y1, x2, y2, radius,
                         fill=None, outline=None, width=1, tags=None):
        """用带贝塞尔平滑的 polygon 画圆角矩形（Tk 没有 create_rounded_rect）。

        每个角用三段折线逼近圆弧：顶点分别离角 (0, r)、(r, 0)、(r, r)，
        smooth 会在折线间插值出圆角弧线。
        """
        if radius > (x2 - x1) / 2:
            radius = (x2 - x1) / 2
        if radius > (y2 - y1) / 2:
            radius = (y2 - y1) / 2
        pts = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        ]
        return canvas.create_polygon(pts, smooth=True, splinesteps=36,
                                     fill=fill, outline=outline, width=width, tags=tags)

    def _mode_button(self, parent, text, key):
        """扁平化模式按钮：悬停变色 + 选中高亮（bg 切 PRIMARY、文字变白）。"""
        btn = tk.Button(parent, text=text, width=4, relief="flat", bd=0,
                        bg=theme.INPUT_BG, fg=theme.TEXT,
                        activebackground=theme.PRIMARY, activeforeground="#fff",
                        font=(theme.FONT, theme.SIZE_GROUP),
                        command=lambda k=key: self.set_mode(k))
        btn.bind("<Enter>", lambda e: self._set_button_bg(btn, theme.CARD_ACTIVE))
        btn.bind("<Leave>", lambda e: self._restore_button(btn))
        self._mode_buttons[key] = btn
        return btn

    def _set_button_bg(self, btn, bg):
        """悬停/选中时换背景；若按钮处于选中态（当前模式），悬停不破坏高亮。"""
        if btn not in self._mode_buttons.values():
            btn.config(bg=bg)
            return
        cur = self._mode_buttons.get(self.mode_key())
        if btn is cur:
            btn.config(bg=theme.PRIMARY)  # 选中态保持主色
        else:
            btn.config(bg=bg)

    def _restore_button(self, btn):
        """Leave 后恢复：选中态保持主色，普通按钮回到输入区底色。"""
        if btn not in self._mode_buttons.values():
            return
        cur = self._mode_buttons.get(self.mode_key())
        if btn is cur:
            btn.config(bg=theme.PRIMARY)
        else:
            btn.config(bg=theme.INPUT_BG)

    def _chip(self, parent, label):
        """指标小方块：小标签在上 + 大数值在下，背景 CHIP_BG 圆角。

        返回 (chip_frame, value_var)；chip_frame 包一层"边框白板"，卡片铺上去形成圆角效果。
        """
        holder = tk.Frame(parent, bg=theme.FRAME_BORDER)
        chip = tk.Frame(holder, bg=theme.CHIP_BG)
        chip.pack(padx=1, pady=1)
        tk.Label(chip, text=label, bg=theme.CHIP_BG, fg=theme.CHIP_LABEL,
                 font=(theme.FONT, theme.SIZE_CHIP_LABEL)).pack(anchor="center", pady=(3, 0))
        value_var = tk.StringVar(value="--")
        tk.Label(chip, textvariable=value_var, bg=theme.CHIP_BG, fg=theme.CHIP_VALUE,
                 font=(theme.FONT_SEMIBOLD, theme.SIZE_CHIP_VALUE)).pack(anchor="center", pady=(0, 3))
        return holder, value_var

    def _slider_block(self, parent, label, key, maxv, default):
        """一行参数滑块：小标签在上，横条在下，trough 与卡片同色视觉统一。"""
        row = tk.Frame(parent, bg=theme.CARD)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label, anchor="w", bg=theme.CARD, fg=theme.TEXT_DIM,
                 font=(theme.FONT, theme.SIZE_LABEL)).pack(anchor="w")
        scale = tk.Scale(row, from_=0, to=maxv, orient="horizontal", length=210,
                         bg=theme.CARD, fg=theme.TEXT, troughcolor=theme.INPUT_BG,
                         activebackground=theme.PRIMARY, highlightthickness=0,
                         command=lambda v, k=key: self.on_slider(k, v))
        scale.set(default)  # 关键：滑块初始位置必须与生效的默认参数一致
        scale.pack(fill="x", pady=(0, 2))
        self.sliders[key] = scale

    def _build_sliders(self, parent):
        """参数滑块区：Canny 阈值、HSV 上下限、轮廓最小面积。"""
        tk.Label(parent, text="参数调节（按模式生效）", bg=theme.CARD, fg=theme.TEXT_DIM,
                 font=(theme.FONT_SEMIBOLD, theme.SIZE_GROUP)).pack(anchor="w", pady=(0, 2))

        self.sliders = {}
        self._slider_block(parent, "Canny Low", "canny_low", 255, 50)
        self._slider_block(parent, "Canny High", "canny_high", 255, 150)
        self._slider_block(parent, "H Min", "h_min", 179, 0)
        self._slider_block(parent, "H Max", "h_max", 179, 179)
        self._slider_block(parent, "S Min", "s_min", 255, 0)
        self._slider_block(parent, "S Max", "s_max", 255, 255)
        self._slider_block(parent, "V Min", "v_min", 255, 0)
        self._slider_block(parent, "V Max", "v_max", 255, 255)
        self._slider_block(parent, "Min Area", "contour_min_area", 5000, 500)

    # =====================================================================
    # 事件
    # =====================================================================

    def set_mode(self, key):
        mapping = {
            "1": vision_modes.MODE_ORIGINAL,
            "2": vision_modes.MODE_GRAY,
            "3": vision_modes.MODE_CANNY,
            "4": vision_modes.MODE_HSV,
            "5": vision_modes.MODE_CONTOUR,
        }
        self.mode = mapping.get(key, vision_modes.MODE_ORIGINAL)
        names = {
            vision_modes.MODE_ORIGINAL: "原始", vision_modes.MODE_GRAY: "灰度",
            vision_modes.MODE_CANNY: "Canny", vision_modes.MODE_HSV: "HSV",
            vision_modes.MODE_CONTOUR: "轮廓",
        }
        self.mode_label.config(text=f"当前: {names[self.mode]}")
        # 按钮选中态：当前模式按钮高亮为主色，其余恢复输入区底色
        for k, btn in self._mode_buttons.items():
            if k == key:
                btn.config(bg=theme.PRIMARY, fg="#fff")
            else:
                btn.config(bg=theme.INPUT_BG, fg=theme.TEXT)
        self._refresh_params_label()

    def mode_key(self):
        """当前 self.mode 对应的按钮 key，供悬停/恢复选中态判断。"""
        rev = {
            vision_modes.MODE_ORIGINAL: "1", vision_modes.MODE_GRAY: "2",
            vision_modes.MODE_CANNY: "3", vision_modes.MODE_HSV: "4",
            vision_modes.MODE_CONTOUR: "5",
        }
        return rev.get(self.mode)

    def on_slider(self, key, val):
        """Tkinter 滑块回调：实时更新 params。"""
        self.params[key] = int(float(val))
        self._refresh_params_label()

    def _refresh_params_label(self):
        """在模式标签下方显示当前关键参数，便于学习。"""
        pass  # 参数已在滑块上可见，无需额外标签

    def save_capture(self):
        frame, _ = self.reader.get_latest_frame()
        if frame is None:
            self.stats["error"] = "无帧可保存"
            return
        import os
        from datetime import datetime
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")
        os.makedirs(out, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        h, w = frame.shape[:2]
        tag = f"{stamp}-{self.mode}-{w}x{h}"
        disp = vision_modes.apply_mode(self.mode, frame, self.params)
        p_orig = os.path.join(out, f"{tag}-original.jpg")
        p_disp = os.path.join(out, f"{tag}-{self.mode}.png")
        cv2.imwrite(p_orig, frame)
        cv2.imwrite(p_disp, disp)
        self.stats["error"] = f"已保存: {tag}"

    def reconnect(self):
        # 手动重连：AppModel 内部在后台线程执行 stop+start，不阻塞 GUI
        self.model.set_last_error("已请求重连...")
        self.model.reconnect()

    def quit(self):
        self.model.stop()
        self.root.destroy()

    # =====================================================================
    # 主循环刷新
    # =====================================================================

    def _refresh_loop(self):
        """定时刷新：取帧、处理、显示、更新状态栏、/ping。"""
        try:
            self.model.refresh()  # 汇总统计 + /ping 轮询 + 丢帧估算
            self._update_frame()
            self._update_status()
        except Exception as e:  # noqa: BLE001 - GUI 循环不能崩
            self.stats["error"] = str(e)
        self.root.after(33, self._refresh_loop)  # ~30fps

    def _update_frame(self):
        frame, num = self.reader.get_latest_frame()
        # 同帧去重：reader 只留最新帧，主循环 ~30fps 但流可能 ~10fps，
        # 帧号没变就跳过处理与 PhotoImage 重建，避免显示 FPS 虚高和 CPU 浪费
        if num is not None and num == getattr(self, "_last_frame_num", None):
            return
        self._last_frame_num = num

        if frame is None:
            placeholder = np.zeros((360, 640, 3), dtype=np.uint8)
            state = self.reader.get_state()
            text = f"等待画面... 状态: {state}"
            if state == "Reconnecting":
                text = "连接断开，正在重连..."
            cv2.putText(placeholder, text, (30, 180),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            disp = placeholder
        else:
            disp = vision_modes.apply_mode(self.mode, frame, self.params)
            # 通知共享模型：本帧已显示，用于显示 FPS 统计
            self.model.mark_frame_displayed()

        # 显示到 Tkinter
        img = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
        h, w = img.shape[:2]
        # 按画面区缩放（保持比例）；缩小用 INTER_AREA 画质更好
        max_w, max_h = 660, 380
        scale = min(max_w / w, max_h / h)
        new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
        interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
        img = cv2.resize(img, (new_w, new_h), interpolation=interp)
        from PIL import Image, ImageTk
        self._tk_img = ImageTk.PhotoImage(Image.fromarray(img))
        self.canvas.config(image=self._tk_img)

    def _update_status(self):
        """把统计写进状态栏指标小方块；状态块颜色随状态变化。"""
        # 从共享 AppModel 取不可变快照，同步到 self.stats（兼容旧渲染代码）
        snap = self.model.snapshot()
        st = self.stats
        st["state"] = snap.connection_state
        st["phone_fps"] = snap.phone_fps
        st["recv_fps"] = snap.receive_fps
        st["disp_fps"] = snap.display_fps
        st["width"] = snap.width
        st["height"] = snap.height
        st["avg_jpeg_mb"] = snap.average_jpeg_bytes / (1024 * 1024)
        st["throughput_mbps"] = snap.bandwidth_mbps
        st["received"] = snap.received_frames
        st["invalid"] = snap.invalid_frames
        st["dropped"] = snap.estimated_dropped_frames
        # 双向同步错误：有错误显示真实错误；无错误（连接恢复后模型已清空）
        # 立即清空本地残留，标题栏恢复正常，不留旧 HTTP 错误（与 PySide6 对齐）。
        st["error"] = snap.last_error or ""
        if not self._chips:
            return
        self._chips["phone_fps"].set(f"{st['phone_fps']:.1f}")
        self._chips["recv_fps"].set(f"{st['recv_fps']:.1f}")
        self._chips["disp_fps"].set(f"{st['disp_fps']:.1f}")
        self._chips["resolution"].set(
            f"{st['width']}x{st['height']}" if st.get("width") else "--")
        self._chips["avg_jpeg_mb"].set(f"{st['avg_jpeg_mb']:.2f}M")
        self._chips["throughput_mbps"].set(f"{st['throughput_mbps']:.1f}M")
        self._chips["received"].set(str(st["received"]))
        self._chips["invalid"].set(str(st["invalid"]))
        self._chips["dropped"].set(str(st["dropped"]))

        # 状态块配色：Streaming 绿、Reconnecting 琥珀、异常红
        state = st["state"]
        if state == "Streaming":
            color = theme.GREEN
        elif state == "Reconnecting":
            color = theme.AMBER
        elif st.get("error"):
            color = theme.RED
        else:
            color = theme.TEXT_DIM
        self._chips["status"].set(state if state else "Idle")
        f = self._chip_frames["status"]
        for child in f.winfo_children():
            for sub in child.winfo_children():
                if isinstance(sub, tk.Label):
                    sub.config(fg=color)


def run(stream_url, ping_url, ping_info):
    """启动一体化 GUI。"""
    root = tk.Tk()
    app = PhoneVisionApp(root, stream_url, ping_url, ping_info)
    root.mainloop()
