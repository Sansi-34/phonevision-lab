"""验证 GUI 能否正常构建（不依赖手机，用假 ping_info）。"""
import tkinter as tk
import sys
import os

# 确保能找到 pc-client 目录下的模块（app_gui/theme/mjpeg_reader/vision_modes）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app_gui

# 假 ping_info，模拟手机信息
ping_info = {
    "device": "MIX 2S", "width": 640, "height": 480,
    "requestedFps": 10, "actualFps": 15.0, "status": "streaming",
}

root = tk.Tk()
app = app_gui.PhoneVisionApp(root, "http://127.0.0.1:8080/stream",
                             "http://127.0.0.1:8080/ping", ping_info)
print("GUI 构建成功，窗口标题:", root.title())
# 3 秒后自动关闭（避免阻塞验收）
root.after(3000, root.destroy)
root.mainloop()
print("GUI 正常关闭")
