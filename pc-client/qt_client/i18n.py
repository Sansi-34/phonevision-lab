"""
PhoneVision Lab — 双语国际化模块（简体中文 / 英文）。

职责：为整个 PySide6 工作台提供可切换语言的文案服务：
  - STRINGS：集中定义两种语言所有用户可见文案，两种语言 key 集合严格一致。
  - Translator：按当前语言取字符串、切换语言（可选 QSettings 持久化）、
    语言切换信号、初始语言解析、缺失 key 回退。

为什么这样设计：
  - 字典驱动：界面全部文案收敛到一个 dict，UI 只通过 key 取文案，
    不散落硬编码，改文案/加语言只动这一处。
  - 显式回退：text() 遇到缺失 key 返回 "???" + key + "???"，绝不静默返回
    空白，方便在界面上直接看到哪个 key 漏了；missing_keys() 可程序化查询。
  - key 集合一致性：两种语言必须拥有完全相同的 key 集合，否则界面切换语言
    后某处文案会回退成 "???"。keys(language) 暴露给测试做一致性断言。
  - 可注入 QSettings：测试传 settings=QSettings("test", "test") 或 mock，
    读写内存/临时存储，不污染真实用户配置。
  - 可注入初始语言：无界面测试可传 initial_language="en" 直接构造英文实例。
  - language_changed 信号：界面组件连接它，语言切换时统一刷新文案，
    不用每个组件各自监听菜单。

注意：
  - 不联网、不下载、不加第三方依赖，只用 PySide6 自带能力。
  - 状态专名（Streaming/Connecting/...）与英文模式名（Canny/HSV）在两种
    语言保持原文，只提供 status_* 别名供组件取用。
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Signal, QObject

# 语言标识常量（供调用方 import，避免字符串散落）。
LANG_ZH = "zh-CN"
LANG_EN = "en"

# =====================================================================
# 双语字符串表
# =====================================================================
# 约定：
#   - 两种语言 key 集合必须完全一致（测试会断言）。
#   - 含 {name} 的 key 通过 text(key, name=...) 传参，两种语言占位符集合
#     必须一致（测试会断言），否则切换语言后 format 会 KeyError/遗留花括号。
#   - 专名（Streaming/Canny/HSV/PhoneVision Lab）两种语言保持原文。

STRINGS = {
    # ---------- 顶栏 ----------
    "app_title": ("PhoneVision Lab", "PhoneVision Lab"),
    "device_placeholder": ("等待设备信息", "Waiting for device"),
    "save_screenshot": ("保存截图", "Save Screenshot"),
    "reconnect": ("重新连接", "Reconnect"),
    "language": ("语言", "Language"),

    # ---------- 状态专名（两种语言保持英文专名）----------
    # StatusPill/占位直接显示这些英文状态词，界面语义统一。
    "status_connecting": ("Connecting", "Connecting"),
    "status_streaming": ("Streaming", "Streaming"),
    "status_reconnecting": ("Reconnecting", "Reconnecting"),
    "status_stopped": ("Stopped", "Stopped"),
    "status_error": ("Error", "Error"),

    # ---------- 视觉模式 ----------
    "mode_title": ("视觉模式", "Vision Mode"),
    "mode_original": ("原始", "Original"),
    "mode_gray": ("灰度", "Gray"),
    "mode_canny": ("Canny", "Canny"),
    "mode_hsv": ("HSV", "HSV"),
    "mode_contour": ("轮廓", "Contours"),
    "current_mode": ("当前: {mode}", "Current: {mode}"),

    # ---------- 参数区 ----------
    "param_title": ("当前模式参数", "Mode Parameters"),
    "param_hint": ("按模式生效", "Applies to current mode"),
    # 参数标签（主标签两种语言均保持英文缩写，中文只作副标签说明）。
    "canny_low": ("Canny Low", "Canny Low"),
    "canny_high": ("Canny High", "Canny High"),
    "h_min": ("H Min", "H Min"),
    "h_max": ("H Max", "H Max"),
    "s_min": ("S Min", "S Min"),
    "s_max": ("S Max", "S Max"),
    "v_min": ("V Min", "V Min"),
    "v_max": ("V Max", "V Max"),
    "contour_min_area": ("Min Area", "Min Area"),
    # 参数副标签（中文说明 / 英文说明）。
    "param_canny_low_sub": ("阈值下限", "Lower threshold"),
    "param_canny_high_sub": ("阈值上限", "Upper threshold"),
    "param_h_min_sub": ("色相下限", "Hue lower"),
    "param_h_max_sub": ("色相上限", "Hue upper"),
    "param_s_min_sub": ("饱和度下限", "Saturation lower"),
    "param_s_max_sub": ("饱和度上限", "Saturation upper"),
    "param_v_min_sub": ("明度下限", "Value lower"),
    "param_v_max_sub": ("明度上限", "Value upper"),
    "param_contour_min_area_sub": ("最小面积", "Min contour area"),
    # 无参数模式的教学空状态。
    "param_empty_original": (
        "此模式无参数，先熟悉画面",
        "No parameters for this mode",
    ),
    "param_empty_gray": (
        "此模式无参数，先熟悉灰度",
        "No parameters for this mode",
    ),

    # ---------- 教学提示（P0-4A 文案 + 英文翻译）----------
    "hint_original": (
        "观察手机摄像头的原始画面",
        "Observe the raw camera feed",
    ),
    "hint_gray": (
        "先观察亮度结构，再进入阈值和边缘处理",
        "Study the brightness structure first, then move on to thresholds and edges",
    ),
    "hint_canny": (
        "Low以下丢弃，High以上保留，中间边缘需与强边相连",
        "Below Low is dropped, above High is kept, in-between edges must connect to a strong edge",
    ),
    "hint_hsv": (
        "白色区域表示当前颜色范围被选中",
        "The white region marks the currently selected color range",
    ),
    "hint_contour": (
        "Min Area用于滤除面积较小的噪点",
        "Min Area filters out small noise regions",
    ),

    # ---------- 诊断面板 ----------
    "diag_title": ("实时诊断", "Live Diagnostics"),
    "diag_expand": ("展开诊断", "Expand"),
    "diag_collapse": ("收起诊断", "Collapse"),
    # 指标标签。
    "metric_recv_fps": ("接收FPS", "Receive FPS"),
    "metric_disp_fps": ("显示FPS", "Display FPS"),
    "metric_dropped": ("丢帧", "Dropped"),
    "metric_phone_fps": ("采集FPS", "Capture FPS"),
    "metric_mbps": ("带宽Mbps", "Mbps"),
    "metric_avg_jpeg": ("平均JPEG", "Avg JPEG"),
    "metric_received": ("接收帧", "Frames"),
    "metric_invalid": ("无效帧", "Invalid"),
    "metric_resolution": ("分辨率", "Resolution"),
    # 各指标 tooltip 说明。
    "tip_recv_fps": ("PC实际接收速率", "Actual frames received by the PC per second"),
    "tip_disp_fps": ("实际显示的新画面频率", "How often a new frame is displayed"),
    "tip_dropped": ("手机发出但电脑没收到的帧", "Frames sent by the phone but missed by the PC"),
    "tip_phone_fps": ("手机端采集帧率（来自 /ping）", "Phone capture rate (from /ping)"),
    "tip_mbps": ("网络吞吐，反映推流带宽占用", "Network throughput used by the stream"),
    "tip_avg_jpeg": ("每帧 JPEG 平均大小", "Average encoded size of each frame"),
    "tip_received": ("已成功解析的帧总数", "Total frames successfully decoded"),
    "tip_invalid": ("损坏或无法解析的帧数", "Frames that were corrupt or could not be decoded"),
    "tip_resolution": ("视频画面宽x高", "Video width x height"),

    # ---------- 画面占位 ----------
    "placeholder_connecting": ("正在连接...", "Connecting..."),
    "placeholder_connecting_sub": ("正在建立与手机推流的连接", "Establishing connection to the phone stream"),
    "placeholder_reconnecting": ("视频流已中断", "Video stream interrupted"),
    "placeholder_reconnecting_sub": ("正在自动重连，或点击下方按钮立即重试", "Auto-reconnecting, or press the button below to retry now"),
    "placeholder_stopped": ("已停止", "Stopped"),
    "placeholder_stopped_sub": ("未在接收视频", "No video is being received"),
    "placeholder_error": ("连接失败", "Connection failed"),
    "placeholder_error_sub": ("请检查网络或手机推流状态", "Check the network or the phone streaming state"),
    "placeholder_reconnect_button": ("重新连接", "Reconnect"),

    # ---------- Toast 通知 ----------
    "toast_saved": ("已保存: {path}", "Saved: {path}"),
    "toast_no_frame": ("当前无画面可保存", "No frame to save"),
    "toast_conn_error": ("连接错误", "Connection error"),
    "toast_restored": ("连接已恢复", "Connection restored"),
    "toast_save_failed": ("保存失败: {error}", "Save failed: {error}"),

    # ---------- 连接启动页（ConnectionDialog） ----------
    "connect_title": ("PhoneVision Lab", "PhoneVision Lab"),
    "version_label": ("版本: {version}", "Version: {version}"),
    "version_unknown": ("版本未知", "Version unknown"),
    "enter_ip_label": ("手机 IP 或主机名", "Phone IP or hostname"),
    "ip_placeholder": ("例如 192.168.1.100", "e.g. 192.168.1.100"),
    "port_label": ("端口", "Port"),
    "language_label": ("语言", "Language"),
    "connect_button": ("连接", "Connect"),
    "cancel_button": ("取消 / 退出", "Cancel / Exit"),
    "connecting_text": ("正在连接...", "Connecting..."),
    "step_1": ("1. 手机打开 PhoneVision Lab", "1. Open PhoneVision Lab on the phone"),
    "step_2": ("2. 点击开始推流", "2. Tap Start Streaming"),
    "step_3": ("3. 输入手机界面显示的 IP", "3. Enter the IP shown on the phone"),
    "error_host_required": ("请输入手机 IP 或主机名", "Enter the phone IP or hostname"),
    "error_port_invalid": ("端口必须是 1-65535 的数字", "Port must be a number from 1 to 65535"),
    "error_unknown": ("连接失败，请检查网络后重试", "Connection failed, check the network and retry"),

    # ---------- 数据集工作台（DatasetPanel）----------
    "ds_title": ("数据集", "Dataset"),
    "ds_none": ("（还没有数据集）", "(no dataset yet)"),
    "ds_open": ("打开", "Open"),
    "ds_create": ("新建", "Create"),
    "ds_create_title": ("新建数据集", "Create dataset"),
    "ds_create_prompt": ("数据集名称（用作目录名）", "Dataset name (used as directory name)"),
    "ds_create_failed": ("创建失败: {error}", "Create failed: {error}"),
    "ds_open_failed": ("打开失败: {error}", "Open failed: {error}"),
    "ds_open_first": ("请先创建或打开一个数据集", "Create or open a dataset first"),
    "ds_no_dataset": ("尚未打开数据集", "No dataset open"),
    "ds_classes": ("类别", "Classes"),
    "ds_add_class": ("新增类别", "Add class"),
    "ds_rename": ("重命名", "Rename"),
    "ds_rename_title": ("重命名类别", "Rename class"),
    "ds_rename_prompt": ("新的类别名", "New class name"),
    "ds_rename_failed": ("重命名失败: {error}", "Rename failed: {error}"),
    "ds_add_failed": ("新增类别失败: {error}", "Add class failed: {error}"),
    "ds_class_placeholder": ("类别名，如 apple", "Class name, e.g. apple"),
    "ds_capture": ("采集", "Capture"),
    "ds_capture_one": ("采集一张", "Capture one"),
    "ds_capture_start": ("开始连续采集", "Start burst"),
    "ds_capture_stop": ("停止采集", "Stop burst"),
    "ds_capturing": ("采集中：已保存 {count} 张（批次 {batch}）",
                     "Capturing: {count} saved (batch {batch})"),
    "ds_capture_stopped": ("采集结束：已保存 {count} 张", "Capture stopped: {count} saved"),
    "ds_no_frame": ("当前没有可采集的画面（手机未推流或已断线）",
                    "No frame available (phone not streaming or disconnected)"),
    "ds_wait_new_frame": ("等待新的摄像头画面，避免重复保存同一帧",
                          "Waiting for a new camera frame to avoid duplicates"),
    "ds_save_failed": ("保存失败: {error}", "Save failed: {error}"),
    "ds_batch_failed": ("创建采集批次失败: {error}", "Create batch failed: {error}"),
    "ds_no_class": ("请先选择采集类别", "Select a capture class first"),
    "ds_stats": ("样本: {classes}　合计 {total}",
                 "Samples: {classes}  total {total}"),
    "ds_check": ("数据体检", "Check data"),
    "ds_check_ok": ("体检通过：可以开始训练", "Check passed: ready to train"),
    "ds_check_problems": ("问题（需先处理）:", "Problems (fix first):"),
    "ds_check_warnings": ("提示（不阻断）:", "Warnings (non-blocking):"),
    "ds_split": ("划分训练/验证", "Split train/val"),
    "ds_split_failed": ("划分失败: {error}", "Split failed: {error}"),
    "ds_split_done": ("划分完成（按采集批次，避免相邻近似帧跨集合）",
                      "Split done (by capture batch, so near-identical frames stay together)"),
    "ds_split_train": ("训练集: {count} 张（{detail}）",
                       "Train: {count} ({detail})"),
    "ds_split_val": ("验证集: {count} 张（{detail}）",
                     "Val: {count} ({detail})"),
    "ds_split_path": ("已保存: {path}", "Saved: {path}"),

    # ---------- 训练与导出（TrainPanel）----------
    "tr_title": ("训练与导出", "Train & Export"),
    "tr_no_dataset": ("请先在数据集面板打开数据集", "Open a dataset in the Dataset panel first"),
    "tr_no_split": ("尚未划分训练/验证集，请先点“划分训练/验证”",
                    "No train/val split yet — press “Split train/val” first"),
    "tr_need_tensorflow": (
        "当前程序未加载 TensorFlow。请在项目目录使用 start-training.cmd 启动训练工作台；"
        "便携版暂不支持训练。",
        "TensorFlow is not available in this process. Use start-training.cmd in the project folder; "
        "training is not yet available in the portable build."),
    "tr_start": ("开始训练", "Start training"),
    "tr_cancel": ("取消训练", "Cancel training"),
    "tr_export": ("导出模型包", "Export model package"),
    "tr_running": ("训练中…", "Training…"),
    "tr_epoch": ("Epoch {epoch}/{total}", "Epoch {epoch}/{total}"),
    "tr_step": ("step {step}/{total}", "step {step}/{total}"),
    "tr_loss": ("损失 {loss}", "loss {loss}"),
    "tr_acc": ("训练准确率 {acc}", "train acc {acc}"),
    "tr_val": ("验证准确率 {acc}", "val acc {acc}"),
    "tr_best": ("最佳 {acc}", "best {acc}"),
    "tr_done": ("训练完成", "Training complete"),
    "tr_cancelled": ("训练已取消", "Training cancelled"),
    "tr_failed": ("训练失败: {error}", "Training failed: {error}"),
    "tr_export_done": ("模型包已生成: {path}", "Model package created: {path}"),
    "tr_export_failed": ("导出失败: {error}", "Export failed: {error}"),
    "tr_consistency": (
        "导出一致性：最大误差 {error}，Top-1 一致率 {agreement}",
        "Export consistency: max error {error}, Top-1 agreement {agreement}"),
    "tr_device_cpu": ("CPU（兼容所有电脑）", "CPU (works everywhere)"),
    "tr_device_gpu": ("GPU（检测到可用时）", "GPU (when available)"),
    "tr_env_ok": (
        "训练环境已就绪（TensorFlow 已安装）。",
        "Training environment ready (TensorFlow installed)."),
    "tr_exporting": ("正在导出模型包…", "Exporting model package…"),
    "tr_export_wait_close": ("模型正在导出，请等待完成后再关闭窗口。",
                             "A model export is in progress. Wait until it finishes before closing."),
    "tr_export_no_model": (
        "还没有训练产物（best.keras）。请先完成一次训练。",
        "No trained model (best.keras) yet. Finish a training run first."),

    # ---------- 硬件联动（HardwarePanel）----------
    "hw_title": ("硬件联动", "Hardware"),
    "hw_device_ip": ("控制器 IP", "Controller IP"),
    "hw_port": ("端口", "Port"),
    "hw_connect": ("连接", "Connect"),
    "hw_disconnect": ("断开", "Disconnect"),
    "hw_status": ("状态", "Status"),
    "hw_connected": ("已连接", "Connected"),
    "hw_disconnected": ("未连接", "Disconnected"),
    "hw_error": ("连接异常: {error}", "Link error: {error}"),
    "hw_manual": ("手动动作测试", "Manual action test"),
    "hw_led_on": ("LED 开", "LED on"),
    "hw_led_off": ("LED 关", "LED off"),
    "hw_target_class": ("目标类别", "Target class"),
    "hw_trigger_conf": ("触发置信度", "Trigger confidence"),
    "hw_confirm_count": ("连续确认次数", "Confirm count"),
    "hw_exit_conf": ("退出置信度", "Exit confidence"),
    "hw_release_frames": ("退出帧数", "Release frames"),
    "hw_cooldown": ("冷却时间(ms)", "Cooldown (ms)"),
    "hw_auto": ("开启自动控制", "Enable auto control"),
    "hw_auto_on": ("自动控制：已开启", "Auto control: ON"),
    "hw_stop": ("停止控制", "Stop control"),
    "hw_stopped": ("已停止自动控制，不会再产生新的自动动作",
                   "Auto control stopped — no further automatic actions"),
    "hw_need_manual": (
        "请先连接设备并完成手动 LED 验证，再开启自动控制",
        "Connect the device and verify the LED manually before enabling auto control"),
    "hw_no_prediction_source": (
        "当前没有视觉结果来源，自动控制不会产生任何动作。\n\n"
        "PC 客户端默认只提供传统视觉模式（原始/灰度/Canny/HSV/轮廓），"
        "没有分类器，因此无法在此驱动自动控制。\n\n"
        "自动控制在 Android 端可用：手机导入模型并推理后，"
        "识别结果会直接驱动规则引擎与设备。",
        "There is no vision-result source, so auto control will never fire.\n\n"
        "The PC client only provides classical vision modes "
        "(original/gray/Canny/HSV/contours) and has no classifier, so it cannot "
        "drive auto control here.\n\n"
        "Auto control works on Android: after importing a model and running "
        "inference, recognition results drive the rule engine and the device."),
    "hw_not_connected": ("尚未连接设备", "Device not connected"),
    "hw_rule_state": ("规则状态", "Rule state"),
    "hw_rule_triggered": ("已触发", "Triggered"),
    "hw_rule_idle": ("未触发", "Idle"),
    "hw_confirm_progress": ("连续确认 {n}/{total}", "Confirm {n}/{total}"),
    "hw_event_log": ("事件记录", "Event log"),
    "hw_cmd_sent": ("已发送", "Sent"),
    "hw_cmd_received": ("已接收", "Received"),
    "hw_cmd_executed": ("已执行", "Executed"),
    "hw_cmd_failed": ("失败", "Failed"),
    "hw_ack_note": (
        "设备只确认接收时，界面显示“已接收”，不显示执行成功",
        "When the device only confirms receipt, the UI shows “Received”, not “Executed”"),
    "hw_simulated": (
        "模拟设备：仅验证软件链路，不等于真实硬件验收通过",
        "Simulated device: validates the software path only — not a real-hardware pass"),
    "hw_pc_no_classifier": (
        "PC 客户端没有分类器，本面板的自动控制不可用；手动动作测试与设备连接可用。"
        "自动控制在 Android 端可用（导入模型并推理后由识别结果驱动）。",
        "The PC client has no classifier, so auto control is unavailable here; "
        "manual action testing and device connection do work. Auto control works "
        "on Android (driven by recognition results after importing a model)."),
    "hw_pc_has_classifier": (
        "已注入视觉结果来源，自动控制可用。",
        "A vision-result source is injected; auto control is available."),

    # ---------- 性能（PerfPanel）----------
    "pf_title": ("性能分析", "Performance"),
    "pf_start": ("开始测试", "Start test"),
    "pf_stop": ("停止测试", "Stop test"),
    "pf_warmup": ("预热(秒)", "Warmup (s)"),
    "pf_duration": ("测试时长(秒)", "Duration (s)"),
    "pf_procedure_note": ("先预热，再按固定时长采样；帧率为每秒采样均值。手机推理与硬件数据尚未接入时显示 --。",
                          "Warm up, then sample for the selected duration. FPS is the mean of one-second samples; unavailable inference and hardware data is shown as --."),
    "pf_export_csv": ("导出 CSV", "Export CSV"),
    "pf_export_summary": ("导出摘要", "Export summary"),
    "pf_exported": ("已导出: {path}", "Exported: {path}"),
    "pf_capture_fps": ("手机采集帧率", "Phone capture FPS"),
    "pf_receive_fps": ("PC 接收帧率", "PC receive FPS"),
    "pf_display_fps": ("PC 显示帧率", "PC display FPS"),
    "pf_infer_fps": ("手机推理帧率", "Phone inference FPS"),
    "pf_preprocess": ("预处理", "Preprocess"),
    "pf_model": ("模型执行", "Model"),
    "pf_postprocess": ("后处理", "Postprocess"),
    "pf_dropped": ("丢弃帧", "Dropped"),
    "pf_completed": ("完成帧", "Completed"),
    "pf_unsupported": ("不支持", "Unsupported"),
    "pf_power_note": (
        "功耗仅在设备提供真实数据源时显示；PC 客户端不测量手机功耗。",
        "Power is shown only when the device exposes a real source; the PC client does not measure phone power."),
    "pf_hw_latency": ("命令确认耗时", "Command ack latency"),
    "pf_hw_note": (
        "命令确认耗时 = 发送到控制器确认；设备只确认接收时不等于机械动作完成耗时。",
        "Ack latency = send-to-controller-confirmation; it is not mechanical completion time when the device only confirms receipt."),

    # ---------- 工作台标签页 ----------
    "wb_tab_vision": ("视觉工作台", "Vision"),
    "wb_tab_dataset": ("数据集", "Dataset"),
    "wb_tab_train": ("训练与导出", "Train & Export"),
    "wb_tab_hardware": ("硬件联动", "Hardware"),
    "wb_tab_perf": ("性能分析", "Performance"),
}

# 缺失 key 的显式回退模板：绝不清空白，界面上一眼可见。
_MISSING_TEMPLATE = "???{key}???"


def _normalize_language(language: str) -> str:
    """把任意传入语言标识归一化为 zh-CN / en；未知一律回落到 zh-CN。"""
    if language is None:
        return LANG_ZH
    low = str(language).strip().lower().replace("_", "-")
    if low.startswith("zh"):
        return LANG_ZH
    return LANG_EN


class Translator(QObject):
    """双语文案服务：取字符串 / 切语言 / 初始语言解析 / 缺失回退。

    线程安全性：仅应在 GUI 主线程使用（Qt 对象）。语言切换会 emit
    language_changed(str)，UI 组件连接它统一刷新。
    """

    # 语言切换信号：参数为新的语言标识（"zh-CN"/"en"）。
    language_changed = Signal(str)

    def __init__(self, settings: QSettings | None = None,
                 initial_language: str = "zh-CN"):
        super().__init__()
        # 可注入 QSettings 用于测试隔离；不传则用真实用户配置。
        self._settings = settings if settings is not None else \
            QSettings("PhoneVisionLab", "PhoneVisionLab")
        self._language = _normalize_language(initial_language)

    # ---- 文案获取 ----

    def text(self, key: str, **kwargs) -> str:
        """取当前语言字符串；kwargs 用于 {name} 占位符格式化。

        缺失 key 返回 "???{key}???"（显式回退，绝不清空白），
        并通过 self.missing 集合记录，供 missing_keys() 查询。
        """
        table = STRINGS.get(key)
        if table is None:
            self._mark_missing(key)
            return _MISSING_TEMPLATE.format(key=key)
        # 二元组顺序固定：(zh-CN, en)。
        raw = table[0] if self._language == LANG_ZH else table[1]
        if kwargs:
            # 占位符一致性由测试保证；此处仍做防御性兜底，缺参时保留原花括号。
            try:
                return raw.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return raw
        return raw

    def keys(self, language: str | None = None) -> set[str]:
        """返回某个语言的 key 集合（language 缺省取当前语言）。

        两种语言 key 集合相同，因此返回值与语言无关；此参数保留是为了
        让测试显式断言两种语言的一致性，语义清晰。
        """
        if language is None:
            return set(STRINGS.keys())
        return set(STRINGS.keys())

    def missing_keys(self) -> set[str]:
        """返回本次实例中 text() 访问过的缺失 key 集合（用于测试/排查）。"""
        return set(getattr(self, "_missing", set()))

    def _mark_missing(self, key: str) -> None:
        if not hasattr(self, "_missing"):
            self._missing = set()
        self._missing.add(key)

    # ---- 语言切换 ----

    def set_language(self, language: str, persist: bool = True) -> None:
        """切换语言；persist=True 时用 QSettings 保存。

        归一化后若与当前语言不同，emit language_changed 并更新内部状态。
        """
        new_lang = _normalize_language(language)
        if persist:
            self._settings.setValue("language", new_lang)
        if new_lang == self._language:
            return
        self._language = new_lang
        self.language_changed.emit(new_lang)

    def language(self) -> str:
        """返回当前语言："zh-CN"/"en"。"""
        return self._language

    @staticmethod
    def available_languages() -> list[str]:
        """返回全部可用语言标识。"""
        return [LANG_ZH, LANG_EN]

    # ---- 初始语言解析 ----

    @staticmethod
    def resolve_initial_language(cli_value: str | None, saved_value: str | None,
                                 system_locale: str | None) -> str:
        """初始语言优先级：CLI > 已保存 > 系统区域。

        cli_value/saved_value 传语言标识（"zh-CN"/"en" 或任意含 "zh" 前缀的
        写法）；system_locale 传系统区域字符串（如 "zh_CN"/"zh-CN" 或
        "en_US"），仅按是否含 "zh" 前缀决定 zh-CN，否则 en。
        """
        for value in (cli_value, saved_value):
            if value:  # 非空则归一化后直接采用
                return _normalize_language(value)
        # 系统区域：仅看是否含 "zh" 前缀，无法识别时默认英文。
        if system_locale:
            low = str(system_locale).strip().lower().replace("_", "-")
            if low.startswith("zh"):
                return LANG_ZH
        return LANG_EN
