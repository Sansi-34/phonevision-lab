"""
PhoneVision Lab — PC 端 5 种 OpenCV 视觉学习模式。

职责：把一帧 BGR 画面按所选模式处理成要显示的 BGR 帧。参数通过 params 字典
传入，由 main.py 用控制台按键（+/− 等）更新，实时生效。

为什么这样设计：
  - 所有模式共用一张主窗口（WINDOW_NAME）和共享的 params 字典：main.py 只负责
    取帧、调用 apply_mode、显示结果，完全不关心每种模式的处理细节。
  - 不用 OpenCV trackbar：本机（Windows 高 DPI + OpenCV 5.0）的 HighGUI trackbar
    拖动不更新值，是环境级 bug。改用控制台按键调参，100% 可靠且适合学习。
  - Canny / HSV / Contour 都基于"当前帧 + 当前参数"实时计算，不依赖历史帧，
    逻辑直白，便于初学者逐行理解。

初学者调试观察点：
  - GRAY：画面变黑白，最基础的通道转换。
  - CANNY：阈值越低边缘越多越碎，越高越干净但容易断边，找"刚好连成轮廓"的平衡。
  - HSV：调 H 选颜色、S 选鲜艳度、V 选亮度；白色部分是选中的像素，黑色被过滤。
  - CONTOUR：调 Min Area 过滤小噪点，看绿色轮廓、蓝色外接框和红色中心坐标。
"""
import cv2
import numpy as np

# ---- 模式常量（main.py 通过它们切换模式）----
MODE_ORIGINAL = "original"   # 原始画面
MODE_GRAY = "gray"           # 灰度
MODE_CANNY = "canny"         # Canny 边缘
MODE_HSV = "hsv"             # HSV 颜色掩膜
MODE_CONTOUR = "contour"     # 轮廓

WINDOW_NAME = "Vision"

# ---- 参数默认值（main.py 用控制台 +/− 交互更新这些键）----
# H 通道范围是 0-179（OpenCV 约定，不同于 0-360），S/V 是 0-255
DEFAULT_PARAMS = {
    "canny_low": 50,
    "canny_high": 150,
    "h_min": 0,
    "h_max": 179,
    "s_min": 0,
    "s_max": 255,
    "v_min": 0,
    "v_max": 255,
    "contour_min_area": 500,
}


def create_windows(mode: str) -> None:
    """创建主窗口。mode 仅做占位。

    注意：本机（Windows 高 DPI + OpenCV 5.0）的 HighGUI trackbar 拖动不更新值，
    是 OpenCV 环境级 bug，所以这里不创建 trackbar。参数全部由 main.py 通过
    控制台（msvcrt）交互更新到 params 字典，vision_modes 每帧读 params。
    """
    cv2.namedWindow(WINDOW_NAME)


def destroy_windows() -> None:
    """销毁主窗口。"""
    cv2.destroyWindow(WINDOW_NAME)


def apply_mode(mode: str, frame_bgr, params: dict):
    """按模式分发处理，返回要显示的 BGR 帧；原图/未知模式一律显示原始帧。"""
    if mode == MODE_ORIGINAL:
        return frame_bgr
    if mode == MODE_GRAY:
        return _apply_gray(frame_bgr)
    if mode == MODE_CANNY:
        return _apply_canny(frame_bgr, params)
    if mode == MODE_HSV:
        return _apply_hsv(frame_bgr, params)
    if mode == MODE_CONTOUR:
        return _apply_contour(frame_bgr, params)
    return frame_bgr


# ----------------------------------------------------------------------
# 各模式处理函数
# ----------------------------------------------------------------------

def _apply_gray(frame_bgr):
    """灰度：BGR -> GRAY -> BGR 两跳转换，输出仍是 3 通道方便统一显示。"""
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def _apply_canny(frame_bgr, params: dict):
    """Canny 边缘：双阈值决定边缘的多少与粗细。"""
    edges = cv2.Canny(frame_bgr, params["canny_low"], params["canny_high"])
    return cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)


def _apply_hsv(frame_bgr, params: dict):
    """HSV 颜色掩膜：按上下限做 inRange，掩膜转 BGR 显示成黑白图。"""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    lower = np.array([params["h_min"], params["s_min"], params["v_min"]], dtype=np.uint8)
    upper = np.array([params["h_max"], params["s_max"], params["v_max"]], dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)
    return cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)


def _apply_contour(frame_bgr, params: dict):
    """轮廓：HSV 掩膜 -> findContours -> 过滤小面积 -> 画轮廓/外接框/中心坐标。

    基于当前帧 + 当前 HSV 参数实时计算掩膜，不依赖历史帧。
    """
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    lower = np.array([params["h_min"], params["s_min"], params["v_min"]], dtype=np.uint8)
    upper = np.array([params["h_max"], params["s_max"], params["v_max"]], dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)

    # OpenCV 4.x/5.x 的 findContours 返回 (contours, hierarchy)，不要写旧版 3 元组
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    display = frame_bgr.copy()
    min_area = params["contour_min_area"]
    for cnt in contours:
        if cv2.contourArea(cnt) < min_area:
            continue
        cv2.drawContours(display, [cnt], -1, (0, 255, 0), 2)   # 绿色：轮廓
        x, y, w, h = cv2.boundingRect(cnt)
        cv2.rectangle(display, (x, y), (x + w, y + h), (255, 0, 0), 2)  # 蓝色：外接矩形
        cx, cy = x + w // 2, y + h // 2
        cv2.circle(display, (cx, cy), 3, (0, 0, 255), -1)      # 红色：矩形中心点
        cv2.putText(display, f"({cx}, {cy})", (cx + 8, cy + 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
    return display
