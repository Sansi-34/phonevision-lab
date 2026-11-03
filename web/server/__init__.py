"""
PhoneVision Lab Web — 包初始化。

web/ 是 PhoneVision Lab 的新客户端（网页版学习与实践平台），与 pc-client
（PySide6 桌面客户端）、android（手机端）并列。它复用 pc-client 的
connection / mjpeg_reader / app_model / vision_modes / pvl_* 模块，
不复制训练、数据集、硬件与性能逻辑。
"""
