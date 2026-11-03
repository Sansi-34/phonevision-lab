/** Curated from upstream project documentation on 2026-11-02; exercises are ours. */
window.PVL_OPEN_SOURCE = [
  {
    id: 'opencv', title: '先处理一张图片', project: 'OpenCV', category: '图像处理', level: '入门',
    repo: 'https://github.com/opencv/opencv', entry: 'https://docs.opencv.org/4.x/d6/d00/tutorial_py_root.html', entryLabel: 'OpenCV-Python 教程',
    language: '英文文档，Python 示例', lessons: ['c1', 'c3'], practice: 'lab', practiceLabel: '回实验台比较效果',
    why: '实验台的灰度、Canny、HSV 和轮廓处理，都可以在这里找到对应的算法与示例。',
    prepare: '会运行简单 Python 脚本；先读本平台第 1、3 课。不需要手机。',
    steps: ['从图像读取与显示开始，确认图像尺寸和通道顺序。', '依次尝试灰度转换、Canny 边缘检测与 HSV 颜色筛选。', '换成自己拍摄的照片，记录参数变化对结果的影响。'],
    result: '保存同一张照片的原图、灰度图和边缘图，并能说明 HSV 筛选保留了什么。',
    note: '先学教程中的核心操作和图像处理，不必从编译整个 OpenCV 仓库开始。'
  },
  {
    id: 'sklearn', title: '先弄清楚怎样验证模型', project: 'scikit-learn', category: '数据与验证', level: '基础',
    repo: 'https://github.com/scikit-learn/scikit-learn', entry: 'https://scikit-learn.org/stable/common_pitfalls.html', entryLabel: '数据泄漏与常见问题',
    language: '英文文档，Python 示例', lessons: ['c4', 'c5'], practice: 'dataset', practiceLabel: '回数据集工作区检查划分',
    why: '训练成绩好不等于能识别新照片。先理解数据泄漏，再看平台为什么按采集批次划分数据。',
    prepare: '了解类别、训练集与验证集；先读第 4、5 课。不需要手机。',
    steps: ['阅读 Common pitfalls 中的数据泄漏示例。', '用示例理解先划分数据、再拟合预处理的顺序。', '检查自己的采集批次，避免连续拍摄的近似图片同时进入训练集和验证集。'],
    result: '写下自己数据的划分依据，并指出一次可能导致验证成绩虚高的操作。',
    note: '它是验证方法的学习材料，不是本平台的神经网络训练后端；不要把普通随机划分直接替代批次划分。'
  },
  {
    id: 'transfer', title: '训练一个自己的分类器', project: 'TensorFlow Docs', category: '模型训练', level: '进阶',
    repo: 'https://github.com/tensorflow/docs', entry: 'https://www.tensorflow.org/tutorials/images/transfer_learning?hl=zh-cn', entryLabel: '中文迁移学习教程',
    language: '中文教程，Python Notebook', lessons: ['c4', 'c5'], practice: 'train', practiceLabel: '回模型训练页做实验',
    why: '从预训练网络提取特征，再训练分类层，和本平台训练轻量分类模型的思路相通。',
    prepare: '会运行 Python，理解训练集与验证集；准备独立的 TensorFlow 学习环境。',
    steps: ['先阅读特征提取与微调的区别，再运行官方 Notebook。', '观察冻结基础模型时，哪些参数参与训练。', '对照平台中的训练结果，记录训练与验证表现的差别。'],
    result: '能解释冻结层、数据增强和过拟合，并保存一次训练曲线及自己的分析。',
    note: '教程以 MobileNetV2 为例，本平台使用 MobileNetV3Small；预处理和导出方式不能直接照搬。下载数据与权重需要网络。'
  },
  {
    id: 'tflite', title: '读懂手机上的分类推理', project: 'TensorFlow Examples', category: '手机部署', level: '进阶',
    repo: 'https://github.com/tensorflow/examples', entry: 'https://github.com/tensorflow/examples/blob/master/lite/examples/image_classification/android/README.md', entryLabel: 'Android 图像分类示例',
    language: '英文说明，Kotlin 示例', lessons: ['c6', 'c8'], practice: 'deploy', practiceLabel: '回手机部署页核对模型包',
    why: '沿着摄像头输入、图像预处理、模型调用和分类结果，理解手机离线推理的完整路径。',
    prepare: '了解模型输入尺寸与类别标签；具备 Kotlin 基础并能使用 Android Studio。',
    steps: ['从 README 了解运行条件，再找摄像头图像进入分类器的位置。', '核对输入尺寸、颜色顺序、归一化与输出标签。', '对照平台模型包的参数说明，区分预处理耗时和推理耗时。'],
    result: '画出一次手机分类推理的数据流，列出导入自己模型前必须核对的参数。',
    note: '该示例保留旧版 Android Studio / TFLite 工具链说明，README 要求 Android 6.0+。先作为源码阅读材料；不承诺直接适配本平台 Android 5.0 旧手机或模型包。'
  },
  {
    id: 'esp32', title: '让一次请求驱动硬件', project: 'ESP-IDF', category: '硬件联动', level: '进阶',
    repo: 'https://github.com/espressif/esp-idf', entry: 'https://github.com/espressif/esp-idf/blob/master/examples/protocols/http_server/simple/README.md', entryLabel: 'Simple HTTP Server 示例',
    language: '英文说明，C 示例', lessons: ['c7', 'c8'], practice: 'hardware', practiceLabel: '回硬件页查看命令回执',
    why: '先理解设备怎样接收 HTTP 请求，再思考如何把手机的识别结果变成可靠的 LED 控制。',
    prepare: '有 ESP32 开发板、USB 数据线和 ESP-IDF 环境；先读本平台第 7 课。',
    steps: ['按官方说明运行 HTTP Server 示例，先确认网络和请求响应。', '阅读 URI 处理函数，理解请求内容怎样变成设备操作。', '对照平台的硬件协议，区分请求发出、收到回执与动作执行。'],
    result: '能解释网络响应为什么不等于 LED 已执行，并列出控制命令需要的回执信息。',
    note: '官方示例演示 HTTP 服务，不直接实现本平台的 LED 控制协议。需要额外编写 GPIO 动作、命令去重和执行回执。'
  },
  {
    id: 'camera', title: '支线：自己写手机相机采集', project: 'Android Camera Samples', category: '相机开发', level: '选学',
    repo: 'https://github.com/android/camera-samples', entry: 'https://github.com/android/camera-samples/blob/main/README.md', entryLabel: '当前相机示例目录',
    language: '英文说明，Kotlin / Compose 示例', lessons: ['c2', 'c6'], practice: 'lab', practiceLabel: '回视觉实验台连接手机',
    why: '如果想改造手机端，可从官方相机示例学习预览、拍照与帧处理，而不只把手机当作现成摄像头。',
    prepare: '具备 Kotlin 和 Android 开发基础。仅使用本平台手机 App 的用户可以跳过。',
    steps: ['阅读当前 README 的 Samples 列表，先选 Take a Photo。', '比较 Camera2 和 CameraX 的采集流程，再看帧处理相关示例。', '对照本平台的相机采集与 JPEG 推流职责，列出需要增加的网络发送环节。'],
    result: '能区分相机采集、图像处理和网络推流，并说明一帧图像从哪里产生。',
    note: 'main 分支已改为统一示例目录，旧教程中的 Camera2Basic 路径不再适用。现代示例的设备要求不等于本平台旧手机兼容范围，修改前需查看对应模块配置。'
  }
];

// Reading pointers reference upstream documents; practice briefs are designed for this platform.
const PVL_SOURCE_GUIDES = {
  opencv: {
    equipment: '电脑即可', focus: '看懂像素、颜色与边缘',
    concepts: [['通道顺序', 'OpenCV 读入的彩色图通常是 BGR，转换颜色前先确认输入。'], ['灰度', '把颜色信息转为亮度，方便观察结构和对比。'], ['阈值', '筛选规则的参数；改变它会改变留下来的区域。']],
    reading: [
      ['颜色空间转换', 'https://docs.opencv.org/4.x/df/d9d/tutorial_py_colorspaces.html', '先看 cvtColor，再看 inRange 如何生成颜色掩膜。'],
      ['Canny 边缘检测', 'https://docs.opencv.org/4.x/da/d22/tutorial_py_canny.html', '观察双阈值怎样影响细碎边缘，不必一开始推导全部公式。']
    ],
    workshop: { title: '从桌面照片中找出一个彩色物体', brief: '拍一张有彩色杯子或笔的桌面照片，保留其他背景。用同一张图比较不同处理方法。', tasks: ['记录图像尺寸与通道数，保存一份灰度图。', '用两组不同阈值生成 Canny 图，圈出差异最明显的位置。', '调节 HSV 范围，让目标物体尽量保留、背景尽量排除。'], outputs: ['原图与灰度图', '两组阈值对应的边缘图', 'HSV 参数及一段效果说明'] },
    checks: ['把同一组 HSV 参数用于不同光照，结果是否还稳定？', '你找到的是物体类别，还是满足颜色条件的像素？', '哪些细节在灰度图里仍然保留？'],
    pitfalls: [['颜色看起来不对', '先核对 BGR / RGB 顺序，再检查转换代码。'], ['边缘太碎或几乎为空', '固定照片，一次只改一组阈值；同时观察噪点与光照。']]
  },
  sklearn: {
    equipment: '电脑即可', focus: '让验证结果经得起换一批照片',
    concepts: [['数据泄漏', '验证信息提前参与训练，会让成绩偏乐观。'], ['采集批次', '同一次连续拍摄的相近照片，需要作为相关样本看待。'], ['独立验证', '留出的数据应模拟下一次真实使用，而不是重复训练照片。']],
    reading: [
      ['常见问题与数据泄漏', 'https://scikit-learn.org/stable/common_pitfalls.html', '重点看预处理为什么应先划分、再拟合。'],
      ['按组进行交叉验证', 'https://scikit-learn.org/stable/modules/cross_validation.html#cross-validation-iterators-for-grouped-data', '理解组之间隔离的理由，再联系本平台的采集批次。']
    ],
    workshop: { title: '给自己的数据做一次划分审计', brief: '选两个准备识别的类别。把拍摄时间或场景接近的照片标为同一个批次，先检查分组，再讨论模型成绩。', tasks: ['列出每个类别的采集批次，并标出连拍得到的近似图片。', '在数据集工作区按批次划分，检查训练集与验证集是否共享批次。', '预留一次新的拍摄场景，写下用它检验模型的计划。'], outputs: ['类别与批次清单', '训练 / 验证划分记录', '一次新场景验证计划'] },
    checks: ['同一段连拍进入两个集合，会影响什么？', '为什么不能先用所有数据拟合预处理？', '新拍摄的数据能否暴露原验证集没有覆盖的问题？'],
    pitfalls: [['验证成绩很好，换场景就失效', '检查近似照片、背景和光照是否过于一致。'], ['把分组方法直接当作平台实现', '学习隔离原则即可；平台仍使用自己的批次划分逻辑。']]
  },
  transfer: {
    equipment: '电脑与训练环境', focus: '理解迁移学习，而不是只按开始训练',
    concepts: [['特征提取', '利用预训练网络的表示，为自己的类别训练分类层。'], ['冻结与微调', '冻结时不更新基础模型权重；微调时开放部分层继续学习。'], ['过拟合', '训练表现改善，并不保证新数据上的表现同步改善。']],
    reading: [
      ['中文迁移学习教程', 'https://www.tensorflow.org/tutorials/images/transfer_learning?hl=zh-cn', '按数据准备、冻结、训练、微调的顺序读。'],
      ['官方 Notebook 源码', 'https://github.com/tensorflow/docs/blob/master/site/en/tutorials/images/transfer_learning.ipynb', '定位基础模型、trainable 设置与训练曲线对应的单元格。']
    ],
    workshop: { title: '写一份两类分类实验记录', brief: '使用按批次划分的数据，先完成一次平台训练。记录真实配置与结果，再用官方教程解释训练时发生了什么。', tasks: ['记录类别、批次、划分和训练参数，保留这次实验的配置。', '观察训练与验证曲线，选出二者开始明显分离的位置。', '提出一个下一轮实验假设，例如更换拍摄背景；一次只改一个因素。'], outputs: ['训练配置记录', '实际曲线或结果截图', '下一轮实验假设'] },
    checks: ['这次训练中哪些层的权重可以改变？', '验证表现变差时，继续增加训练轮数一定有用吗？', '示例模型与平台模型的预处理有什么需要分别核对？'],
    pitfalls: [['直接套用教程的输入缩放', '先查模型预处理要求；MobileNetV2 与平台模型不能据名称推断相同。'], ['反复调参直到验证集好看', '保留独立新数据，避免把验证集也变成调参记忆。']]
  },
  tflite: {
    equipment: 'Android 真机与开发环境', focus: '核对从摄像头到分类结果的数据契约',
    concepts: [['预处理', '输入尺寸、裁剪、颜色顺序和数值缩放必须与训练约定一致。'], ['标签映射', '输出索引只有按正确标签顺序解释，才得到正确类别。'], ['阶段耗时', '图像准备、模型运行和结果展示的耗时应分别理解。']],
    reading: [
      ['示例运行条件', 'https://github.com/tensorflow/examples/blob/master/lite/examples/image_classification/android/README.md', '先核对旧版工具链和 Android 版本要求。'],
      ['CameraFragment.kt', 'https://github.com/tensorflow/examples/blob/master/lite/examples/image_classification/android/app/src/main/java/org/tensorflow/lite/examples/imageclassification/fragments/CameraFragment.kt', '沿摄像头分析回调找到图像送入分类逻辑的位置。']
    ],
    workshop: { title: '为模型包写一张输入输出核对表', brief: '从平台导出的模型包说明入手，再阅读 Android 示例。先理解数据流，不要求把外部示例直接接入平台。', tasks: ['列出输入尺寸、颜色顺序、缩放、裁剪和输出标签顺序。', '在示例中找到对应处理环节，标出仍无法确认的项目。', '部署到兼容手机后记录真实表现；没有设备时保留待验证项。'], outputs: ['输入输出核对表', '摄像头到结果的数据流图', '实测记录或明确的待验证清单'] },
    checks: ['输入形状相同，是否代表预处理一定相同？', '类别名称都存在但顺序不同，会产生什么问题？', '推理耗时为什么不能直接当作整条链路的帧率？'],
    pitfalls: [['导入模型后标签错位', '先比对输出索引与 labels 顺序，再怀疑模型精度。'], ['把外部示例当成旧手机兼容保证', '按示例自身要求检查工具链与设备，不替代平台的兼容性说明。']]
  },
  esp32: {
    equipment: 'ESP32 与 USB 数据线', focus: '把网络请求和实际执行区分开',
    concepts: [['请求处理', 'HTTP 服务按 URI 找到处理函数，再生成响应。'], ['执行回执', '收到请求不代表物理动作已经完成。'], ['幂等与去重', '重试同一条命令时，应避免重复触发不希望发生的动作。']],
    reading: [
      ['Simple HTTP Server 的 main.c', 'https://github.com/espressif/esp-idf/blob/master/examples/protocols/http_server/simple/main/main.c', '看 URI 注册、请求内容读取和响应的连接关系。'],
      ['HTTP Server API 指南', 'https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/protocols/esp_http_server.html', '遇到 API 再查说明，先不扩展到完整联网系统。']
    ],
    workshop: { title: '画出一条 LED 控制命令的生命周期', brief: '先让官方 HTTP 示例完成一次请求响应，再对照平台协议设计控制流程；GPIO 动作和回执需要自己实现。', tasks: ['确认开发板可联网，并记录一次实际请求和响应。', '写出命令标识、目标状态与执行回执分别承担的职责。', '设计重复请求、设备断线和执行失败时应显示的状态。'], outputs: ['实际请求 / 响应记录', '命令生命周期图', '三种异常情况的处理说明'] },
    checks: ['HTTP 返回成功时，怎样确认 LED 真的执行了？', '重复收到同一命令，设备该如何处理？', '停止自动控制后，是否还可能有排队动作需要处理？'],
    pitfalls: [['把网络成功当作物理执行成功', '让设备在动作完成后返回执行结果，并区分状态。'], ['失败就无条件重发命令', '先判断动作能否安全重试，再考虑去重和重试策略。']]
  },
  camera: {
    equipment: 'Android 开发环境，选学', focus: '理解相机生命周期与帧处理职责',
    concepts: [['相机采集', '相机设备和捕获会话负责提供预览或图像数据。'], ['帧处理', '消费图像数据的环节应考虑速度、资源释放与排队。'], ['网络推流', '把编码后的图像送到电脑，是相机采集之外的职责。']],
    reading: [
      ['当前示例目录', 'https://github.com/android/camera-samples/blob/main/README.md', '先选 Take a Photo，再根据需要看 Camera2 与图像处理示例。'],
      ['Camera2 中文概览', 'https://developer.android.com/media/camera/camera2?hl=zh-cn', '明确 Camera2 的低层控制定位，再比较 CameraX。']
    ],
    workshop: { title: '为手机采集端画一张职责图', brief: '选择一个基础拍照示例阅读。把本平台需要的 JPEG 编码与网络发送单独标出，避免把相机和网络逻辑混在一起。', tasks: ['找出权限获取、打开相机与关闭资源的时机。', '区分预览、单张拍摄和逐帧分析的输入输出。', '画出采集、编码、发送三个环节，说明处理变慢时准备怎样应对。'], outputs: ['相机生命周期笔记', '采集 / 编码 / 发送职责图', '旧设备能力核对清单'] },
    checks: ['页面退出或相机切后台时，哪些资源需要释放？', '处理一帧变慢，积压每一帧是否合理？', 'Camera2 API 支持范围与示例 App 的最低版本为什么不能混为一谈？'],
    pitfalls: [['沿用旧教程的目录路径', '以 main 分支当前 README 为入口，再找具体模块。'], ['把所有帧都塞进等待队列', '先明确延迟目标，再设计丢帧、节流与资源释放策略。']]
  }
};
window.PVL_OPEN_SOURCE.forEach(function (project) { project.guide = PVL_SOURCE_GUIDES[project.id]; });
