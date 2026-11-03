/**
 * PhoneVision Lab Web — 手机部署与推理（操作指南页）。
 *
 * 这一页刻意**不做自动部署**：
 *   - 没有可靠的"网页 → 手机"模型传输接口（手机 App 不接收网页推送，
 *     浏览器也无法直接写手机存储）；
 *   - 因此任何"一键部署成功"的按钮都是伪造的。
 * 本页只做三件真实的事：
 *   1. 读出最近一次训练的真实产物（GET /api/train/last-run），有就显示真实文件名与路径；
 *   2. 讲清"导出 → 传到手机 → App 导入 → 本机推理"每一步该做什么、在哪一端做；
 *   3. 给出手动导入的常见问题排查表，让失败有下一步。
 *
 * 诚实边界：
 *   - 未导出时明确写"尚未导出"，并给跳到 #/train 的按钮，不显示任何示例模型包；
 *   - 只有 export_result.package_path 是真实路径时才启用"复制模型包路径"；
 *   - 导入、推理、预测结果全部发生在手机端，网页端只做说明与对照。
 */
window.PVL_PAGES = window.PVL_PAGES || {};

window.PVL_PAGES.deploy = {
  render: async function (root) {
    let disposed = false;

    function copyText(text, okMessage) {
      if (!text) {
        PVL.toast("没有可复制的内容", "warning");
        return;
      }
      const done = function () { PVL.toast(okMessage || "已复制", "success"); };
      const failed = function () {
        PVL.toast("浏览器不允许自动复制，请手动选中复制", "warning");
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, failed);
        return;
      }
      try {
        const area = document.createElement("textarea");
        area.value = text;
        area.setAttribute("readonly", "");
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
        done();
      } catch (error) {
        failed();
      }
    }

    root.appendChild(PVL.el(
      '<section class="page-head">' +
        "<h1>手机部署与推理</h1>" +
        '<p class="page-lede">' +
          "把训练好的模型包放进旧手机，让它在本地离线推理。这条链路跨两台设备，" +
          "网页端只提供操作指南与真实产物路径，手机上的导入与推理需要你手动完成。" +
        "</p>" +
      "</section>"
    ));

    root.appendChild(PVL.el(
      '<div class="banner banner-warning">' +
        "<strong>完整流程尚未在真实手机上完成全面验收</strong>" +
        "<p>协议、固件与模型包格式已经实现并通过一致性校验，但“网页导出 → 传到手机 → App 导入 → 推理”" +
        "这条完整链路还没有在足够多的真实机型上逐台验证。</p>" +
        "<p>因此本页只提供操作指南与产物路径，不提供“一键部署到手机”，也不会显示任何未经真实验证的成功状态。</p>" +
      "</div>"
    ));

    // ---- 产物状态卡（真实数据） ----
    const artifactCard = PVL.el(
      '<section class="card">' +
        '<div class="card-header">' +
          '<h2 class="card-title">模型包产物</h2>' +
          '<span id="deploy-artifact-badge"></span>' +
        "</div>" +
        '<div class="card-body" id="deploy-artifact-body">' +
          '<div class="skeleton skeleton-block"></div>' +
        "</div>" +
      "</section>"
    );
    root.appendChild(artifactCard);

    // ---- 步骤清单 ----
    const stepsCard = PVL.el(
      '<section class="card">' +
        '<div class="card-header"><h2 class="card-title">完整操作步骤</h2></div>' +
        '<div class="card-body">' +
          '<ol class="step-list" id="deploy-steps"></ol>' +
        "</div>" +
      "</section>"
    );
    root.appendChild(stepsCard);

    // ---- 能力边界卡 ----
    root.appendChild(PVL.el(
      '<section class="card">' +
        '<div class="card-header"><h2 class="card-title">能力边界（哪些做不到，为什么）</h2></div>' +
        '<div class="card-body">' +
          '<table class="table">' +
            "<thead><tr><th>能力</th><th>状态</th><th>真实说明</th></tr></thead><tbody>" +
            "<tr><td>网页端推送模型到手机</td>" +
              '<td><span class="badge badge-danger">做不到</span></td>' +
              "<td>没有可靠的自动传输接口：手机 App 不接收网页推送，浏览器也不能直接写手机存储。" +
              "模型包需要你手动用数据线、文件传输工具或 adb 拷过去。</td></tr>" +
            "<tr><td>手机本机推理</td>" +
              '<td><span class="badge badge-warning">Android 端实现</span></td>' +
              "<td>在 Android App 里用 TFLite 运行，默认仅使用 CPU。NNAPI / GPU 委派需要逐台真机验证，" +
              "未验证前不启用，也不声称支持。</td></tr>" +
            "<tr><td>推理联网依赖</td>" +
              '<td><span class="badge badge-success">完全离线</span></td>' +
              "<td>模型导入后推理完全在本机完成，不依赖电脑、不依赖网络。需要联网的只有向控制器发命令那一段。</td></tr>" +
            "<tr><td>网页端查看推理结果</td>" +
              '<td><span class="badge badge-danger">做不到</span></td>' +
              "<td>预测类别与置信度显示在手机 App 屏幕上。手机端尚未向电脑上报推理数据，" +
              "因此性能分析页对应字段显示“未采集”。</td></tr>" +
            "</tbody>" +
          "</table>" +
        "</div>" +
      "</section>"
    ));

    // ---- 常见问题表 ----
    root.appendChild(PVL.el(
      '<section class="card">' +
        '<div class="card-header"><h2 class="card-title">手动导入的常见问题</h2></div>' +
        '<div class="card-body">' +
          '<table class="table">' +
            "<thead><tr><th>现象</th><th>排查方向</th></tr></thead><tbody>" +
            "<tr><td>导入被拒</td><td>App 会给出被拒原因，按原因逐项核对：" +
              "① 模型包格式版本是否被当前 App 支持；② 输入尺寸是否与模型声明一致；" +
              "③ 颜色顺序（RGB / BGR）是否匹配；④ 归一化规则（unit / imagenet / raw）是否一致；" +
              "⑤ 必需文件是否齐全（model.tflite / manifest.json / labels.json）。" +
              "同时确认文件没有被改名或解压——必须是原始的 .pvlmodel.zip。</td></tr>" +
            "<tr><td>预测不准</td><td>先确认导入的模型包就是最近一次训练导出的那个；" +
              "检查拍摄时的光照、角度、距离与训练数据是否一致；" +
              "若怀疑预处理流程与训练时不同，重新训练并导出，再用新包验证。</td></tr>" +
            "<tr><td>手机无反应 / 不显示预测</td><td>确认 App 已获得相机权限；" +
              "确认摄像头没有被其他应用占用；旧手机性能过低时可以降低采集帧率或换更小的输入尺寸重训；" +
              "若完全没画面，回到<a href=\"#/lab\">实验台</a>确认推流与链路是否正常。</td></tr>" +
            "<tr><td>导入后崩溃</td><td>确认手机 ABI 在支持列表内（arm64-v8a / armeabi-v7a / x86 / x86_64），" +
              "并确认 Android 版本 ≥ 21。</td></tr>" +
            "</tbody>" +
          "</table>" +
        "</div>" +
      "</section>"
    ));

    const artifactBadge = artifactCard.querySelector("#deploy-artifact-badge");
    const artifactBody = artifactCard.querySelector("#deploy-artifact-body");
    const stepsEl = stepsCard.querySelector("#deploy-steps");

    // ------------------------------------------------------------------
    // 读取最近一次训练的真实产物
    // ------------------------------------------------------------------

    function renderArtifact(lastRun, loadError) {
      if (loadError) {
        artifactBadge.innerHTML = '<span class="badge badge-danger">读取失败</span>';
        artifactBody.innerHTML =
          '<div class="banner banner-danger"><strong>无法读取训练产物</strong>' +
          "<p>" + PVL.escapeHtml(loadError) + "</p>" +
          "<p>请确认本地服务正在运行，然后刷新页面。</p></div>";
        return;
      }

      const exportState = (lastRun && lastRun.export_state) || "idle";
      const result = (lastRun && lastRun.export_result) || null;
      const packagePath = (result && result.package_path) || "";
      const packageName = packagePath ? packagePath.replace(/\\/g, "/").split("/").pop() : "";

      if (exportState !== "done" || !packagePath) {
        artifactBadge.innerHTML = '<span class="badge badge-neutral">尚未导出</span>';
        let detail = '<p>还没有可用的模型包。</p>';
        if (exportState === "running") {
          detail = "<p>导出正在进行中，完成后这里会显示真实文件路径。</p>";
        } else if (exportState === "error") {
          detail =
            "<p>最近一次导出失败，没有产出模型包。</p>" +
            "<p>原因：" + PVL.escapeHtml(
              (result && result.error) || "后端未返回具体原因") + "</p>";
        } else if (lastRun && lastRun.state === "running") {
          detail = "<p>训练正在进行中，训练成功完成后才能导出。</p>";
        }
        artifactBody.innerHTML =
          '<div class="banner banner-warning"><strong>尚未导出模型包</strong>' +
          detail +
          '<div class="banner-actions">' +
          '<a class="btn btn-primary btn-sm" href="#/train">去模型训练页导出</a>' +
          "</div></div>";
        return;
      }

      artifactBadge.innerHTML = '<span class="badge badge-success">已导出</span>';
      const consistency = result.consistency || {};
      const manifest = result.manifest || {};
      const modelInfo = manifest.model || {};
      const inputInfo = modelInfo.input || {};
      const preprocess = manifest.preprocess || {};

      artifactBody.innerHTML =
        '<ul class="kv-list">' +
        "<li><span>文件名</span><span class=\"mono\">" + PVL.escapeHtml(packageName) + "</span></li>" +
        "<li><span>完整路径</span><span class=\"mono\">" + PVL.escapeHtml(packagePath) + "</span></li>" +
        "<li><span>数据集</span><span>" + PVL.escapeHtml(
          (lastRun && lastRun.dataset_name) || "未记录") + "</span></li>" +
        "<li><span>输入尺寸</span><span>" + PVL.escapeHtml(
          String(inputInfo.shape ? inputInfo.shape.join(" × ") : (preprocess.input_size || "未记录"))) +
        "</span></li>" +
        "<li><span>颜色顺序 / 归一化</span><span>" + PVL.escapeHtml(
          (inputInfo.color_order || preprocess.color_order || "未记录") + " / " +
          (preprocess.normalization || "未记录")) + "</span></li>" +
        "<li><span>类别数</span><span>" + PVL.escapeHtml(
          String((manifest.labels && manifest.labels.count) || "未记录")) + "</span></li>" +
        "<li><span>一致性校验</span><span>" +
        (consistency.passed
          ? '<span class="badge badge-success">通过</span>'
          : '<span class="badge badge-danger">未通过</span>') +
        "（最大绝对误差 " + PVL.metricValue(consistency.max_abs_error, "", "未采集") +
        "，Top-1 一致率 " + PVL.metricValue(consistency.top1_agreement, "", "未采集") +
        "）</span></li>" +
        "</ul>" +
        '<div class="banner-actions">' +
        '<button class="btn btn-secondary btn-sm" type="button" id="deploy-copy-path">复制模型包路径</button>' +
        '<a class="btn btn-ghost btn-sm" href="#/train">回到模型训练页</a>' +
        "</div>";

      const copyBtn = artifactBody.querySelector("#deploy-copy-path");
      if (copyBtn) {
        copyBtn.addEventListener("click", function () {
          copyText(packagePath, "模型包路径已复制");
        });
      }
    }

    function renderSteps(lastRun) {
      const exportState = (lastRun && lastRun.export_state) || "idle";
      const result = (lastRun && lastRun.export_result) || null;
      const packagePath = (result && result.package_path) || "";
      const packageName = packagePath
        ? packagePath.replace(/\\/g, "/").split("/").pop()
        : "";
      const exported = exportState === "done" && packagePath;

      const stepOne = exported
        ? "在电脑上导出模型包。" +
          "<strong>已完成</strong>：文件 " +
          "<span class=\"mono\">" + PVL.escapeHtml(packageName) + "</span>，" +
          "位于 <span class=\"mono\">" + PVL.escapeHtml(packagePath) + "</span>。" +
          "请保持原样，不要改名、不要解压。"
        : "在电脑上导出模型包。当前<strong>尚未导出</strong>：" +
          "先到 <a href=\"#/train\">模型训练</a> 页完成一次训练并导出，" +
          "导出一致性校验通过后才会生成 .pvlmodel.zip。";

      stepsEl.innerHTML =
        '<li class="step-item">' +
          '<span class="step-num">1</span>' +
          "<div><p>" + stepOne + "</p></div>" +
        "</li>" +
        '<li class="step-item">' +
          '<span class="step-num">2</span>' +
          "<div><strong>把 .pvlmodel.zip 传到手机</strong>" +
          "<p>三条可选路径，任选其一：</p>" +
          "<ul>" +
          "<li><strong>USB 数据线</strong>：手机插到电脑，在文件管理器里把文件复制到手机存储；最稳，不依赖网络。</li>" +
          "<li><strong>微信 / 文件传输助手</strong>：把文件发到手机，再在手机上保存到本地；注意微信可能压缩重编码，务必确认文件大小与电脑上一致。</li>" +
          "<li><strong>adb push</strong>：装好 Android 平台工具后执行 " +
          "<span class=\"mono\">adb push &lt;模型包路径&gt; /sdcard/Download/</span>；适合重复部署。</li>" +
          "</ul>" +
          "<p>传完后记住文件在手机上的位置（通常是“下载”或“文件管理”目录）。</p>" +
          "</div>" +
        "</li>" +
        '<li class="step-item">' +
          '<span class="step-num">3</span>' +
          "<div><strong>手机打开 App 的“本机 AI 推理”模式</strong>" +
          "<p>在旧手机上启动 PhoneVision Lab App，进入本机推理界面，先授予相机权限。</p>" +
          "</div>" +
        "</li>" +
        '<li class="step-item">' +
          '<span class="step-num">4</span>' +
          "<div><strong>点“导入模型”，选择刚才那个文件</strong>" +
          "<p>选择第 2 步传到手机上的 .pvlmodel.zip。导入时 App 会校验格式版本、必需文件、" +
          "输入形状、颜色顺序与归一化规则；被拒时会说明原因，按上面常见问题表排查。</p>" +
          "</div>" +
        "</li>" +
        '<li class="step-item">' +
          '<span class="step-num">5</span>' +
          "<div><strong>看到预测类别与置信度即成功</strong>" +
          "<p>把摄像头对准你训练时的目标物体，界面出现预测类别与置信度，就说明模型在手机上跑起来了。</p>" +
          "<p>此时可以断开电脑、关掉 Wi-Fi，推理仍然继续——它完全在本机运行。</p>" +
          "</div>" +
        "</li>";
    }

    let lastRun = null;
    let loadError = "";

    try {
      lastRun = await PVL.api("/api/train/last-run");
    } catch (error) {
      const info = PVL.describeError(error);
      loadError = info.message;
    }

    if (disposed) return function () {};
    renderArtifact(lastRun, loadError);
    renderSteps(lastRun);

    return function cleanup() {
      disposed = true;
    };
  },
};
