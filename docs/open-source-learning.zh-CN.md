# 开源学习路线维护记录

核对日期：2026-11-02。页面地址：`/#/opensource`。路线和练习目标由 PhoneVision Lab 整理，链接指向上游资料；未复制上游教程全文，也未声称示例已在用户设备上运行。

## 内容来源与课程对应

| 阶段 | 项目与原始资料 | 本平台关联 | 整理依据 |
| --- | --- | --- | --- |
| 图像处理 | [OpenCV](https://github.com/opencv/opencv)、[Python 教程](https://docs.opencv.org/4.x/d6/d00/tutorial_py_root.html) | 第 1、3 课，实验台 | 官方教程包含图像基础操作和处理；本站设计原图、灰度、边缘对比练习。 |
| 数据与验证 | [scikit-learn](https://github.com/scikit-learn/scikit-learn)、[Common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html) | 第 4、5 课，数据集工作区 | 从数据泄漏原则引导用户检查自己的采集批次；不把其随机划分当成本平台批次划分实现。 |
| 模型训练 | [TensorFlow Docs](https://github.com/tensorflow/docs)、[中文迁移学习教程](https://www.tensorflow.org/tutorials/images/transfer_learning?hl=zh-cn) | 第 4、5 课，训练页 | 官方教程讲解特征提取和微调。教程模型 MobileNetV2 与本平台 MobileNetV3Small 不同，已在页面注明。 |
| 手机部署 | [TensorFlow Examples](https://github.com/tensorflow/examples)、[Android 分类 README](https://github.com/tensorflow/examples/blob/master/lite/examples/image_classification/android/README.md) | 第 6、8 课，部署页 | README 说明实时摄像头分类、Kotlin、物理设备、Android 6.0+ 和旧版 Studio 工具链。定位为源码阅读材料，不保证 Android 5.0 或平台模型包兼容。 |
| 硬件联动 | [ESP-IDF](https://github.com/espressif/esp-idf)、[HTTP 服务示例](https://github.com/espressif/esp-idf/blob/master/examples/protocols/http_server/simple/README.md) | 第 7、8 课，硬件页 | 官方示例演示 GET /hello、POST /echo 等请求处理；本站的 LED 动作、去重、回执是需要额外设计的练习，非上游现成功能。 |
| 相机开发支线 | [Android Camera Samples](https://github.com/android/camera-samples)、[当前 README](https://github.com/android/camera-samples/blob/main/README.md) | 第 2、6 课，实验台 | 当前 main 为 Camera2 / CameraX 统一目录，包含拍照与帧处理相关样例。旧 Camera2Basic 路径不适用于 main，未向用户提供失效链接。 |

## 实现

- `web/static/open-source.js`：单一数据源，保存项目链接、准备条件、练习顺序、完成目标、平台课程映射及兼容性说明。
- `web/static/pages/learn.js`：渲染路线及课后关联资源。`?stage=` 记录选择，刷新可恢复打开的阶段。
- 侧栏、学习中心、首页与课程详情提供入口；外链新标签打开，页面本身不自动访问第三方服务。
- 保留原来的 8 课和完成状态，拓展路线不计入课程进度。

更新资料时重新检查仓库分支、示例路径、Android / SDK 要求与模型预处理差异，并更新核对日期。不要用 Star 数或未经确认的运行结果判断课程适用性。

## 验证

现有前端测试 10 项通过；浏览器验证学习中心入口、路线选择 URL、阶段展开、课后资源及回到平台课程的跳转。320 / 390 / 768 / 1440 宽度下展开全部项目无横向溢出，无未捕获脚本错误。Hallmark 静态与新页面渲染检查 0 FAIL、0 WARN。相关验收与截图保存在 `.hallmark/`。

## 第二版内容与界面（2026-11-02）

页面已改为左侧路线目录、右侧当前阶段的学习指南；手机端使用原生阶段选择器。保留 `?stage=` 深链接，增加 `&section=concepts|reading|practice|check` 章节定位，并提供上一站 / 下一站及课程往返入口。未知阶段回退到第一站。

六个项目分别补充了三个核心概念、两份有具体阅读提示的上游材料、三个步骤的实践任务、三项练习交付物、三个自查问题和两个常见问题。内容仍存放于 `open-source.js`，以 `guide` 字段扩展原项目资料；阅读指引与实践任务由本站编写，不声称属于上游官方课程。

新增或进一步核对的来源：

- [OpenCV 颜色空间](https://docs.opencv.org/4.x/df/d9d/tutorial_py_colorspaces.html)与 [Canny 教程](https://docs.opencv.org/4.x/da/d22/tutorial_py_canny.html)。
- [scikit-learn 按组交叉验证](https://scikit-learn.org/stable/modules/cross_validation.html#cross-validation-iterators-for-grouped-data)。
- [TensorFlow 迁移学习 Notebook](https://github.com/tensorflow/docs/blob/master/site/en/tutorials/images/transfer_learning.ipynb)。
- [Android 分类示例 CameraFragment.kt](https://github.com/tensorflow/examples/blob/master/lite/examples/image_classification/android/app/src/main/java/org/tensorflow/lite/examples/imageclassification/fragments/CameraFragment.kt)。
- [ESP-IDF HTTP 示例 main.c](https://github.com/espressif/esp-idf/blob/master/examples/protocols/http_server/simple/main/main.c)与 [HTTP Server API](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/protocols/esp_http_server.html)。
- [Camera2 中文概览](https://developer.android.com/media/camera/camera2?hl=zh-cn)。

本轮验证：6 阶段 × 320 / 390 / 768 / 1024 / 1440 共 30 组页面检查通过；实际点击验证路线选择、刷新保留、章节跳转与焦点、问题展开、下一阶段、平台课程往返、手机选择器与非法阶段回退。无脚本异常；现有前端契约测试 10 项通过；Hallmark 渲染检查 0 FAIL、0 WARN。实机训练与硬件运行不在本次页面验收范围内。
