/**
 * PhoneVision Lab Web — 学习进度、使用帮助、关于与能力清单。
 *
 * 第一版不做账号与云同步：进度只保存在本机浏览器 localStorage。
 * "关于"页如实列出能力状态（现有 / 需连接 / 需依赖 / 未验证 / 规划中），
 * 这是产品"不虚构能力"的核心页面之一。
 */
window.PVL_PAGES = window.PVL_PAGES || {};

window.PVL_PAGES.progress = {
  render: async function (root) {
    const order = PVL.lessonOrder();
    const courses = PVL.courses();
    const completed = PVL.store.completedLessons || [];
    const doneCount = order.filter(function (id) {
      return completed.includes(id);
    }).length;
    const percent = order.length ? Math.round(doneCount / order.length * 100) : 0;
    const recent = PVL.store.lastVisited || [];

    root.appendChild(PVL.el(
      '<section class="page-head"><h1>学习进度</h1>' +
        '<p class="page-lede">进度保存在本机浏览器中，不会上传。清除浏览器数据会重置进度。</p>' +
      '</section>'
    ));

    root.appendChild(PVL.el(
      '<section class="card"><div class="card-header">' +
        '<h2 class="card-title">总体进度</h2></div><div class="card-body">' +
        '<p class="metric-big">' + doneCount + ' / ' + order.length + ' 课</p>' +
        '<div class="progress" role="progressbar" aria-valuenow="' + percent +
          '" aria-valuemin="0" aria-valuemax="100">' +
          '<div class="progress-bar" style="width:' + percent + '%"></div></div>' +
        '<p class="field-hint">' + percent + '% 完成</p>' +
        '</div></section>'
    ));

    const rows = order.map(function (id, index) {
      const course = courses[id] || {};
      const isDone = completed.includes(id);
      return (
        '<tr>' +
          '<td>' + (index + 1) + '</td>' +
          '<td><a href="#/learn/' + id + '">' + PVL.escapeHtml(course.title || id) + '</a></td>' +
          '<td>' + PVL.escapeHtml(course.minutes || 10) + ' 分钟</td>' +
          '<td><span class="badge ' + (isDone ? 'badge-success' : 'badge-neutral') + '">' +
            (isDone ? '已完成' : '未完成') + '</span></td>' +
          '<td><a class="btn btn-ghost btn-sm" href="#/learn/' + id + '">' +
            (isDone ? '复习' : '开始') + '</a></td>' +
        '</tr>'
      );
    }).join("");

    root.appendChild(PVL.el(
      '<section class="card"><div class="card-header">' +
        '<h2 class="card-title">课程完成情况</h2></div><div class="card-body">' +
        '<table class="table"><thead><tr><th>#</th><th>课程</th><th>时长</th>' +
        '<th>状态</th><th></th></tr></thead><tbody>' + rows + '</tbody></table>' +
        '</div></section>'
    ));

    const pageNames = {
      lab: "实验台 · 手机与实时视觉",
      dataset: "数据集工作区",
      train: "模型训练",
      deploy: "手机部署与推理",
      hardware: "硬件联动",
      performance: "性能分析",
    };
    const recentHtml = recent.length
      ? recent.map(function (item) {
          const when = item.at ? new Date(item.at) : null;
          const stamp = when && !isNaN(when.getTime())
            ? when.toLocaleString("zh-CN", { hour12: false }) : "";
          return '<li><a href="#/' + PVL.escapeHtml(item.page) + '">' +
            PVL.escapeHtml(pageNames[item.page] || item.page) + '</a>' +
            '<span class="kv-hint">' + PVL.escapeHtml(stamp) + '</span></li>';
        }).join("")
      : '<li class="kv-hint">还没有访问过实验页面</li>';

    root.appendChild(PVL.el(
      '<section class="card"><div class="card-header">' +
        '<h2 class="card-title">最近访问的实验</h2></div><div class="card-body">' +
        '<ul class="kv-list">' + recentHtml + '</ul>' +
        '</div></section>'
    ));

    root.appendChild(PVL.el(
      '<section class="card"><div class="card-header">' +
        '<h2 class="card-title">后续规划（第一版不做）</h2></div><div class="card-body">' +
        '<ul class="goal-list">' +
          '<li>账号系统与云端同步（需要服务器，与"完全本地"定位冲突）</li>' +
          '<li>班级与教师管理（需要后端与权限体系）</li>' +
          '<li>多设备同时连接（当前一次连接一部手机）</li>' +
          '<li>目标检测、图像分割（当前只做图像分类）</li>' +
        '</ul>' +
        '<p class="field-hint">这些能力不影响第一版落地，列入后续版本评估。</p>' +
        '</div></section>'
    ));
  },
};

window.PVL_PAGES.help = {
  render: async function (root) {
    root.appendChild(PVL.el(
      '<section class="page-head"><h1>使用帮助</h1>' +
        '<p class="page-lede">按顺序做，遇到问题先看对应的排查表。</p></section>'
    ));

    root.appendChild(PVL.el(
      '<section class="card"><div class="card-header">' +
        '<h2 class="card-title">第一次使用：五步走</h2></div><div class="card-body">' +
        '<ol class="step-list">' +
          '<li class="step-item"><span class="step-num">1</span><span>' +
            '确认电脑与旧手机在<strong>同一个 Wi-Fi</strong> 下（不是 4G/5G，也不是访客网络隔离）。</span></li>' +
          '<li class="step-item"><span class="step-num">2</span><span>' +
            '手机打开 PhoneVision Lab App，点击<strong>开始推流</strong>，记下界面上显示的 IP（默认端口 8080）。</span></li>' +
          '<li class="step-item"><span class="step-num">3</span><span>' +
            '在<a href="#/lab">实验台</a>填入该 IP 与端口，点击连接。连接成功后会看到实时画面与三个帧率。</span></li>' +
          '<li class="step-item"><span class="step-num">4</span><span>' +
            '在<a href="#/dataset">数据集工作区</a>创建数据集与类别，回到实验台或数据集页采集图片；每个类别至少拍 2 个批次。</span></li>' +
          '<li class="step-item"><span class="step-num">5</span><span>' +
            '执行数据体检与划分，然后到<a href="#/train">模型训练</a>开始训练，训练完成后导出模型包。</span></li>' +
        '</ol></div></section>'
    ));

    root.appendChild(PVL.el(
      '<section class="card"><div class="card-header">' +
        '<h2 class="card-title">常见问题</h2></div><div class="card-body">' +
        '<table class="table"><thead><tr><th>现象</th><th>原因与处理</th></tr></thead><tbody>' +
        '<tr><td>连接提示"无法连接手机"</td>' +
        '<td>依次检查：手机是否已点开始推流；IP 是否填成示例 IP；电脑与手机是否同一网段；Windows 防火墙是否拦截了 Python。</td></tr>' +
        '<tr><td>连接成功但画面不动</td>' +
        '<td>看状态是否变成"重连中"：手机可能停止推流或被系统杀掉后台，回 App 重新开始推流。</td></tr>' +
        '<tr><td>采集提示"摄像头还没有送出新的画面"</td>' +
        '<td>手机帧率较低时连续点击会取到同一帧，稍等再点；这是为了避免同一帧重复入库。</td></tr>' +
        '<tr><td>训练按钮不可用</td>' +
        '<td>页面会显示缺少什么：通常是未安装训练依赖（requirements-train.txt）或数据集尚未划分。按页面提示处理。</td></tr>' +
        '<tr><td>导出一致性校验不通过</td>' +
        '<td>说明量化或转换出了问题，系统会拒绝导出。可尝试调整输入尺寸后重新训练导出。</td></tr>' +
        '<tr><td>硬件命令显示"已接收"但灯不亮</td>' +
        '<td>"已接收"只代表控制器收到命令，不代表执行完成。请目视确认；需要"已执行"回执才会显示已执行。</td></tr>' +
        '<tr><td>性能页很多项目显示"—"</td>' +
        '<td>"—"表示未采集，不代表 0。手机推理与功耗数据尚未接入电脑端，因此不显示数值。</td></tr>' +
        '</tbody></table></div></section>'
    ));

    root.appendChild(PVL.el(
      '<div class="banner banner-warning">' +
        '<strong>网络边界说明</strong>' +
        '<p>手机推流没有身份认证，同一局域网内任何人都能拉流；网页服务默认只监听本机 127.0.0.1。' +
        '如需同一 Wi-Fi 下的其他设备访问网页，需要显式以 0.0.0.0 启动，并只在可信网络中使用。</p>' +
      '</div>'
    ));
  },
};

window.PVL_PAGES.about = {
  render: async function (root) {
    let env = null;
    try {
      env = await PVL.api("/api/train/environment");
    } catch (error) {
      env = null;
    }

    root.appendChild(PVL.el(
      '<section class="page-head"><h1>关于与能力清单</h1>' +
        '<p class="page-lede">这一页如实说明每个能力的真实状态，不把未验证的功能说成可用。</p>' +
      '</section>'
    ));

    root.appendChild(PVL.el(
      '<section class="card"><div class="card-header">' +
        '<h2 class="card-title">能力状态</h2></div><div class="card-body">' +
        '<table class="table"><thead><tr><th>模块</th><th>状态</th><th>真实说明</th></tr></thead><tbody>' +
        capabilityRow("手机推流与实时画面", "需连接手机",
          "Android App 通过局域网推送 MJPEG 流，本地服务解析后提供单帧画面。尚未在全部机型上验收。") +
        capabilityRow("五种视觉模式", "现有",
          "原始 / 灰度 / Canny / HSV / 轮廓，复用桌面客户端同一套 OpenCV 实现。") +
        capabilityRow("数据集管理", "现有",
          "创建/打开、类别管理、按批次采集、体检、按批次划分训练/验证集。") +
        capabilityRow("模型训练", env && env.ready ? "环境可用" : "需训练依赖",
          env && env.ready
            ? ("已检测到 TensorFlow " + PVL.escapeHtml(env.tensorflow_version || "") +
               (env.gpu ? "，检测到 GPU" : "，未检测到 GPU（将使用 CPU，不承诺加速）"))
            : "未检测到 TensorFlow，无法训练。安装后刷新页面即可。") +
        capabilityRow("模型导出", "需训练依赖",
          "Keras 转 TFLite float16，并用固定样本做一致性校验；不通过则拒绝导出。") +
        capabilityRow("手机本机推理", "手机端操作",
          "在 Android App 导入 .pvlmodel.zip 后离线推理。网页端不能自动推送模型。") +
        capabilityRow("硬件联动", "未全面验证",
          "可连接 ESP32 控制器发送 LED 命令并查看四态回执；真机端到端链路尚未完成全面验收。舵机/电机未实现。") +
        capabilityRow("自动控制", "手机端执行",
          "自动联动规则在手机端运行；电脑端没有分类结果来源，因此网页端不提供开关。") +
        capabilityRow("性能分析", "部分接入",
          "采集/接收/显示帧率与丢帧为真实数据；手机推理帧率、各阶段耗时、硬件耗时、功耗均未接入，显示“未采集”。") +
        '</tbody></table></div></section>'
    ));

    root.appendChild(PVL.el(
      '<section class="card"><div class="card-header">' +
        '<h2 class="card-title">运行环境</h2></div><div class="card-body">' +
        '<ul class="kv-list">' +
          '<li><span>界面语言</span><span class="kv-hint">简体中文（英文结构已预留）</span></li>' +
          '<li><span>数据存储</span><span class="kv-hint">本机浏览器 localStorage + 本地数据集目录</span></li>' +
          '<li><span>账号与遥测</span><span class="kv-hint">无账号、无云端、无遥测</span></li>' +
          '<li><span>训练依赖</span><span class="kv-hint">' +
            (env && env.ready ? '已就绪' : '未安装（requirements-train.txt）') + '</span></li>' +
        '</ul></div></section>'
    ));

    root.appendChild(PVL.el(
      '<div class="banner banner-info">' +
        '<strong>与现有项目的关系</strong>' +
        '<p>网页版是 PhoneVision Lab 的新客户端，与 PySide6 桌面客户端、Android App 并列。' +
        '训练、数据集、硬件与性能逻辑都直接调用 pc-client 中已有的 Python 模块，不复制第二套实现。</p>' +
      '</div>'
    ));
  },
};

function capabilityRow(name, status, description) {
  const badge = {
    "现有": "badge-success",
    "环境可用": "badge-success",
    "需连接手机": "badge-info",
    "需训练依赖": "badge-warning",
    "手机端操作": "badge-warning",
    "手机端执行": "badge-warning",
    "未全面验证": "badge-warning",
    "部分接入": "badge-warning",
  }[status] || "badge-neutral";
  return (
    '<tr><td>' + PVL.escapeHtml(name) + '</td>' +
    '<td><span class="badge ' + badge + '">' + PVL.escapeHtml(status) + '</span></td>' +
    '<td>' + PVL.escapeHtml(description) + '</td></tr>'
  );
}
