/**
 * PhoneVision Lab Web — 模型训练页。
 *
 * 目标：把"等待型任务"的三个阶段讲清楚——
 *   开始前：环境是否就绪、数据集是否已划分（缺什么就写什么，不只灰掉按钮）；
 *   训练中：真实进度（epoch/step/percent）、真实指标（没有就显示"— 未采集"）、真实日志；
 *   结束后：能否导出的明确结论，以及一致性校验的真实结果。
 *
 * 数据来源（全部来自后端，前端不缓存、不推算）：
 *   GET  /api/train/environment  训练环境检测（TensorFlow / GPU / 缺失原因）
 *   POST /api/train/start        启动训练（后台线程，页面不阻塞）
 *   GET  /api/train/status       进度快照（每 1.5 秒轮询）
 *   POST /api/train/cancel       协作式取消
 *   POST /api/train/export       导出模型包（后台线程）
 *
 * 诚实边界：
 *   - 未安装 TensorFlow → 环境卡显示 reason + fix_command，开始训练禁用并写明原因；
 *   - 指标为 null → PVL.metricValue(null) 显示"— 未采集"，绝不用 0 或示例值填充；
 *   - 训练未成功完成（state !== done）→ 不显示"导出成功"，导出按钮禁用；
 *   - 导出一致性校验只展示后端回传的 max_abs_error / top1_agreement / passed，不自行判定。
 */
window.PVL_PAGES = window.PVL_PAGES || {};

window.PVL_PAGES.train = {
  render: async function (root, params) {
    const POLL_MS = 1500;
    const LOG_LIMIT = 200;
    const DEFAULT_PARAMS = {
      epochs: 15,
      batch_size: 16,
      input_size: 224,
      learning_rate: 0.001,
      fine_tune_last_n: 20,
      seed: 1234,
      device: "cpu",
    };
    const INPUT_SIZES = [160, 192, 224];

    // 页面级可变状态：离开页面时由 cleanup 置位，避免定时器回调再写 DOM
    let disposed = false;
    let env = null;
    let envLoadError = "";
    let status = null;
    let renderedLogCount = 0;
    let logPinnedToBottom = true;
    let timer = null;

    // ------------------------------------------------------------------
    // 小工具
    // ------------------------------------------------------------------

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

    function stateBadge(state) {
      const map = {
        idle: ["badge-neutral", "未开始"],
        running: ["badge-info", "训练中"],
        cancelling: ["badge-warning", "正在取消"],
        done: ["badge-success", "训练完成"],
        cancelled: ["badge-warning", "已取消"],
        error: ["badge-danger", "训练失败"],
      };
      const found = map[state] || ["badge-neutral", state || "未知"];
      return '<span class="badge ' + found[0] + '">' + PVL.escapeHtml(found[1]) + "</span>";
    }

    function exportStateBadge(state) {
      const map = {
        idle: ["badge-neutral", "未导出"],
        running: ["badge-info", "导出中…"],
        done: ["badge-success", "已导出"],
        error: ["badge-danger", "导出失败"],
      };
      const found = map[state] || ["badge-neutral", state || "未知"];
      return '<span class="badge ' + found[0] + '">' + PVL.escapeHtml(found[1]) + "</span>";
    }

    function setBusy(node, busy, busyText, idleText) {
      if (!node) return;
      node.disabled = busy;
      node.textContent = busy ? busyText : idleText;
    }

    // ------------------------------------------------------------------
    // 页面骨架
    // ------------------------------------------------------------------

    root.appendChild(PVL.el(
      '<section class="page-head">' +
        "<h1>模型训练</h1>" +
        '<p class="page-lede">' +
          "用迁移学习把一个轻量图像分类模型训出来，再导出成手机可导入的模型包。" +
          "训练跑在本地服务后台线程里，本页面可以关闭或切走，不影响训练继续。" +
        "</p>" +
      "</section>"
    ));

    root.appendChild(PVL.el(
      '<div class="banner banner-info">' +
        "<strong>训练在哪里运行</strong>" +
        "<p>训练由本地服务在后台线程执行，不阻塞页面：你可以切到其他页面，训练与导出都会继续。</p>" +
        "<p>未安装 TensorFlow 时无法训练。本页会显示缺少什么、怎么安装，而不是留一个不能点的按钮。</p>" +
      "</div>"
    ));

    // ---- 环境卡片 ----
    const envCard = PVL.el(
      '<section class="card">' +
        '<div class="card-header">' +
          '<h2 class="card-title">训练环境</h2>' +
          '<span id="train-env-badge"></span>' +
        "</div>" +
        '<div class="card-body" id="train-env-body">' +
          '<div class="skeleton skeleton-block"></div>' +
        "</div>" +
      "</section>"
    );
    root.appendChild(envCard);

    // ---- 数据集前置条件 ----
    const preCard = PVL.el(
      '<section class="card">' +
        '<div class="card-header"><h2 class="card-title">训练前置条件</h2></div>' +
        '<div class="card-body" id="train-pre-body">' +
          '<div class="skeleton skeleton-block"></div>' +
        "</div>" +
      "</section>"
    );
    root.appendChild(preCard);

    // ---- 参数卡片 ----
    const paramsCard = PVL.el(
      '<section class="card">' +
        '<div class="card-header"><h2 class="card-title">训练参数</h2></div>' +
        '<div class="card-body">' +
          '<div class="field-grid">' +
            '<div class="field">' +
              '<label class="field-label" for="train-epochs">Epochs（训练轮数）</label>' +
              '<input class="field-input" id="train-epochs" type="number" min="1" max="50" step="1" value="15">' +
              '<p class="field-hint">样本少时 10–15 足够，过多容易过拟合。</p>' +
            "</div>" +
            '<div class="field">' +
              '<label class="field-label" for="train-batch">Batch（每批样本数）</label>' +
              '<input class="field-input" id="train-batch" type="number" min="4" max="64" step="4" value="16">' +
              '<p class="field-hint">内存不够就调小；太小会让训练变慢且不稳定。</p>' +
            "</div>" +
            '<div class="field">' +
              '<label class="field-label" for="train-input">Input（输入尺寸）</label>' +
              '<select class="field-select" id="train-input">' +
                '<option value="160">160 px</option>' +
                '<option value="192">192 px</option>' +
                '<option value="224" selected>224 px</option>' +
              "</select>" +
              '<p class="field-hint">旧手机建议 160–192；224 兼容 ImageNet 预训练权重。</p>' +
            "</div>" +
            "</div>" +
            '<div class="field">' +
              '<button class="btn btn-ghost btn-sm" type="button" id="train-advanced-toggle" ' +
              'aria-expanded="false" aria-controls="train-advanced">高级设置 ▾</button>' +
          "</div>" +
          '<div id="train-advanced" hidden>' +
            '<div class="field-grid">' +
              '<div class="field">' +
                '<label class="field-label" for="train-lr">学习率（learning rate）</label>' +
                '<input class="field-input" id="train-lr" type="number" min="0.00001" max="0.1" step="0.0001" value="0.001">' +
                '<p class="field-hint">默认 1e-3。调大可能不收敛，调小会变慢。</p>' +
              "</div>" +
              '<div class="field">' +
                '<label class="field-label" for="train-finetune">微调最后 N 层</label>' +
                '<input class="field-input" id="train-finetune" type="number" min="0" max="200" step="1" value="20">' +
                '<p class="field-hint">解冻骨干网最后若干层做微调；0 表示只训练分类头。</p>' +
              "</div>" +
              '<div class="field">' +
                '<label class="field-label" for="train-seed">随机种子</label>' +
                '<input class="field-input" id="train-seed" type="number" min="0" max="999999" step="1" value="1234">' +
                '<p class="field-hint">固定种子保证训练可复现（CPU 路径完整）。</p>' +
              "</div>" +
              '<div class="field">' +
                '<label class="field-label" for="train-device">训练设备</label>' +
                '<select class="field-select" id="train-device">' +
                  '<option value="cpu" selected>CPU</option>' +
                "</select>" +
                '<p class="field-hint" id="train-device-hint">正在检测 GPU…</p>' +
              '</div>' +
            '</div>' +
          '</div>' +
          '<div class="card-footer">' +
            '<button class="btn btn-primary" type="button" id="train-start">开始训练</button>' +
            '<button class="btn btn-secondary" type="button" id="train-cancel" hidden>取消训练</button>' +
            '<span class="field-hint" id="train-start-reason"></span>' +
          '</div>' +
        '</section>'
    );
    root.appendChild(paramsCard);

    // ---- 进度卡片 ----
    const progressCard = PVL.el(
      '<section class="card">' +
        '<div class="card-header">' +
          '<h2 class="card-title">训练进度</h2>' +
          '<span id="train-state-badge"></span>' +
        "</div>" +
        '<div class="card-body">' +
          '<div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" ' +
            'aria-valuenow="0" aria-label="训练进度" id="train-progress">' +
            '<div class="progress-bar" id="train-progress-bar" style="width:0%"></div>' +
          "</div>" +
          '<p class="field-hint" id="train-progress-text">尚未开始训练。</p>' +
          '<div class="metric-grid" id="train-metrics"></div>' +
          '<h3 class="card-subtitle">训练日志</h3>' +
          '<div class="log-console" id="train-log" role="log" aria-live="off" ' +
            'aria-label="训练日志">还没有开始训练。</div>' +
          '</div>' +
        '</section>'
    );
    root.appendChild(progressCard);

    // ---- 导出卡片 ----
    const exportCard = PVL.el(
      '<section class="card">' +
        '<div class="card-header">' +
          '<h2 class="card-title">导出模型包</h2>' +
          '<span id="train-export-badge"></span>' +
        "</div>" +
        '<div class="card-body" id="train-export-body"></div>' +
        '<div class="card-footer">' +
          '<button class="btn btn-primary" type="button" id="train-export">导出模型包</button>' +
          '<button class="btn btn-ghost btn-sm" type="button" id="train-export-copy" hidden>复制模型包路径</button>' +
          '<span class="field-hint" id="train-export-reason"></span>' +
        '</div>' +
      '</section>'
    );
    root.appendChild(exportCard);

    const envBadge = envCard.querySelector("#train-env-badge");
    const envBody = envCard.querySelector("#train-env-body");
    const preBody = preCard.querySelector("#train-pre-body");
    const advancedToggle = paramsCard.querySelector("#train-advanced-toggle");
    const advancedPanel = paramsCard.querySelector("#train-advanced");
    const deviceSelect = paramsCard.querySelector("#train-device");
    const deviceHint = paramsCard.querySelector("#train-device-hint");
    const startBtn = paramsCard.querySelector("#train-start");
    const cancelBtn = paramsCard.querySelector("#train-cancel");
    const startReason = paramsCard.querySelector("#train-start-reason");
    const stateBadgeEl = progressCard.querySelector("#train-state-badge");
    const progressEl = progressCard.querySelector("#train-progress");
    const progressBar = progressCard.querySelector("#train-progress-bar");
    const progressText = progressCard.querySelector("#train-progress-text");
    const metricsEl = progressCard.querySelector("#train-metrics");
    const logEl = progressCard.querySelector("#train-log");
    const exportBadge = exportCard.querySelector("#train-export-badge");
    const exportBody = exportCard.querySelector("#train-export-body");
    const exportBtn = exportCard.querySelector("#train-export");
    const exportCopyBtn = exportCard.querySelector("#train-export-copy");
    const exportReasonEl = exportCard.querySelector("#train-export-reason");

    // ------------------------------------------------------------------
    // 环境卡片
    // ------------------------------------------------------------------

    function renderEnvironment() {
      if (envLoadError) {
        envBadge.innerHTML = '<span class="badge badge-danger">检测失败</span>';
        envBody.innerHTML =
          '<div class="banner banner-danger"><strong>无法读取训练环境</strong>' +
          "<p>" + PVL.escapeHtml(envLoadError) + "</p>" +
          "<p>请确认本地服务正在运行，然后刷新页面重试。</p></div>";
        return;
      }
      if (!env) {
        envBadge.innerHTML = '<span class="badge badge-neutral">检测中…</span>';
        return;
      }

      envBadge.innerHTML = env.ready
        ? '<span class="badge badge-success">环境就绪</span>'
        : '<span class="badge badge-danger">环境不可用</span>';

      const missing = (env.missing || []).join("、");
      let html =
        '<ul class="kv-list">' +
        "<li><span>TensorFlow</span><span>" +
        (env.tensorflow
          ? PVL.escapeHtml(env.tensorflow_version || "已安装（版本未知）")
          : '<span class="badge badge-danger">未检测到</span>') +
        "</span></li>" +
        "<li><span>GPU</span><span>" +
        (env.gpu
          ? ("已检测到 " + PVL.escapeHtml((env.gpu_devices || []).join("、") || "GPU"))
          : '<span class="badge badge-neutral">未检测到</span>') +
        "</span></li>" +
        "</ul>" +
        '<p class="field-hint">' + PVL.escapeHtml(env.reason || "") + "</p>";

      if (!env.ready) {
        html +=
          '<div class="banner banner-warning">' +
          "<strong>当前无法训练</strong>" +
          "<p>原因：" + PVL.escapeHtml(env.reason || "训练环境不可用") + "</p>" +
          (missing ? "<p>缺失组件：" + PVL.escapeHtml(missing) + "</p>" : "") +
          '<p class="field-hint">安装命令（在仓库根目录执行）：</p>' +
          '<div class="log-console" id="train-fix-command">' +
          PVL.escapeHtml(env.fix_command || "") + "</div>" +
          '<div class="banner-actions">' +
          '<button class="btn btn-secondary btn-sm" type="button" id="train-copy-fix">复制命令</button>' +
          "</div>" +
          "</div>";
      }

      envBody.innerHTML = html;
      const copyBtn = envBody.querySelector("#train-copy-fix");
      if (copyBtn) {
        copyBtn.addEventListener("click", function () {
          copyText(env.fix_command || "", "安装命令已复制");
        });
      }

      // 设备选项：只有真的检测到 GPU 才允许选 GPU
      deviceSelect.innerHTML = '<option value="cpu" selected>CPU</option>';
      if (env.gpu && (env.gpu_devices || []).length) {
        const option = document.createElement("option");
        option.value = "gpu";
        option.textContent = "GPU（" + env.gpu_devices.join("、") + "）";
        deviceSelect.appendChild(option);
        deviceHint.textContent =
          "已检测到 GPU。注意：TensorFlow 在原生 Windows 上默认不支持 GPU，选 GPU 时服务端会实测，无 GPU 则回落到 CPU 并说明。";
      } else {
        deviceHint.textContent =
          "未检测到可用 GPU，因此只提供 CPU。TensorFlow 在原生 Windows 上默认不支持 GPU；" +
          "没有 GPU 不代表不能训练，只是更慢。";
      }
    }

    // ------------------------------------------------------------------
    // 前置条件（数据集 / 划分）：读真实状态，缺哪步就写哪步
    // ------------------------------------------------------------------

    // 初始值必须带 classes 数组：renderPreconditions/renderActions 会在数据到达前被调用
    let preconditions = { opened: false, splitExists: false, classes: [], datasetName: "" };

    async function loadPreconditions() {
      let current = null;
      try {
        current = await PVL.api("/api/datasets/current");
      } catch (error) {
        current = null;
      }
      let split = null;
      try {
        split = await PVL.api("/api/datasets/split");
      } catch (error) {
        split = null;
      }
      preconditions = {
        opened: Boolean(current && current.opened),
        datasetName: (current && current.name) || "",
        classes: (current && current.classes) || [],
        splitExists: Boolean(split && split.exists),
        train: split && split.exists ? split.train : null,
        val: split && split.exists ? split.val : null,
      };
    }

    function renderPreconditions() {
      const items = [];
      if (!preconditions.opened) {
        items.push({
          done: false,
          text: "还没有打开数据集——请先在数据集工作区创建或选择一个数据集。",
        });
      } else {
        items.push({
          done: true,
          text: "已打开数据集 " + preconditions.datasetName +
            "（" + preconditions.classes.length + " 个类别）。",
        });
        if (preconditions.classes.length < 2) {
          items.push({
            done: false,
            text: "分类模型至少需要 2 个类别，当前只有 " + preconditions.classes.length + " 个。",
          });
        } else {
          items.push({ done: true, text: "类别数 ≥ 2（当前 " + preconditions.classes.length + "）。" });
        }
      }
      if (!preconditions.splitExists) {
        items.push({
          done: false,
          text: "数据集还没有划分训练/验证集——请先执行“数据体检并划分”，训练需要一个独立的验证集。",
        });
      } else {
        items.push({
          done: true,
          text: "已划分：训练集 " + preconditions.train + " 张 / 验证集 " + preconditions.val + " 张。",
        });
      }

      preBody.innerHTML =
        '<ol class="step-list">' +
        items.map(function (item) {
          return '<li class="step-item' + (item.done ? " is-done" : "") + '">' +
            "<span>" + PVL.escapeHtml(item.text) + "</span></li>";
        }).join("") +
        "</ol>" +
        '<p class="field-hint">前置条件不满足时，“开始训练”会保持禁用，并在这里说明缺哪一步。</p>';
    }

    // ------------------------------------------------------------------
    // 进度与指标
    // ------------------------------------------------------------------

    function renderMetrics() {
      const s = status;
      if (!s) {
        metricsEl.innerHTML =
          '<div class="metric-tile"><span class="metric-label">状态</span>' +
          '<span class="metric-value">读取中…</span></div>';
        return;
      }
      const tiles = [
        { label: "Loss", value: s.loss, unit: "" },
        { label: "准确率（训练集）", value: s.accuracy, unit: "" },
        { label: "验证损失", value: s.val_loss, unit: "" },
        { label: "验证准确率", value: s.val_accuracy, unit: "" },
        { label: "最佳验证准确率", value: s.best_val_accuracy, unit: "" },
      ];
      metricsEl.innerHTML = tiles.map(function (tile) {
        return '<div class="metric-tile"><span class="metric-label">' +
          PVL.escapeHtml(tile.label) + "</span>" +
          PVL.metricValue(tile.value, tile.unit, "未采集") + "</div>";
      }).join("");
    }

    function renderProgress() {
      const s = status;
      if (!s) {
        stateBadgeEl.innerHTML = stateBadge("idle");
        progressText.textContent = "正在读取训练状态…";
        return;
      }

      stateBadgeEl.innerHTML = stateBadge(s.state);
      const percent = Math.max(0, Math.min(100, Number(s.percent) || 0));
      progressBar.style.width = percent + "%";
      progressEl.setAttribute("aria-valuenow", String(percent));

      const epochText = s.total_epochs
        ? ("Epoch " + s.epoch + " / " + s.total_epochs)
        : "Epoch —";
      const stepText = s.total_steps
        ? ("Step " + s.step + " / " + s.total_steps)
        : "Step —";
      progressText.textContent =
        epochText + " · " + stepText + " · " + percent + "% · 已用 " +
        PVL.formatTime(s.elapsed_seconds) +
        (s.message ? " · " + s.message : "");

      renderMetrics();
    }

    function appendLogs() {
      const s = status;
      const logs = (s && s.logs) || [];
      if (!logs.length) {
        if (renderedLogCount === 0) {
          logEl.textContent = s && s.state === "error"
            ? "训练失败，但没有收到日志输出。"
            : "还没有开始训练。";
        }
        return;
      }
      if (logs.length < renderedLogCount) {
        // 重新开始了一次训练：日志被清空，重置渲染基准
        logEl.textContent = "";
        renderedLogCount = 0;
        logPinnedToBottom = true;
      }
      const nearBottom =
        logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 40;
      if (renderedLogCount === 0) logEl.textContent = "";
      for (let i = renderedLogCount; i < logs.length; i += 1) {
        const line = document.createElement("div");
        line.className = "log-line";
        const text = String(logs[i] || "");
        if (/失败|错误|Error|Traceback|异常/i.test(text)) {
          line.classList.add("log-line--error");
        } else if (/警告|Warning/i.test(text)) {
          line.classList.add("log-line--warn");
        }
        line.textContent = text;
        logEl.appendChild(line);
      }
      renderedLogCount = Math.min(logs.length, LOG_LIMIT);
      // 自动滚底：只在用户本来就在底部时跟随，不抢夺滚动位置
      if (logPinnedToBottom || nearBottom) {
        logEl.scrollTop = logEl.scrollHeight;
        logPinnedToBottom = true;
      }
    }

    logEl.addEventListener("scroll", function () {
      const nearBottom = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 40;
      logPinnedToBottom = nearBottom;
    });

    // ------------------------------------------------------------------
    // 导出
    // ------------------------------------------------------------------

    function renderExport() {
      const s = status;
      const state = (s && s.export_state) || "idle";
      exportBadge.innerHTML = exportStateBadge(state);

      const trainState = (s && s.state) || "idle";
      const canExport = trainState === "done" && state !== "running";
      exportBtn.disabled = !canExport;
      exportBtn.textContent = state === "running" ? "导出中…" : "导出模型包";

      // 导出不可用时，把真实原因写在导出卡片里（不只灰掉按钮）
      let reason = "";
      if (state === "running") {
        reason = "正在后台导出，请稍候（页面可以切走，导出会继续）。";
      } else if (trainState === "running" || trainState === "cancelling") {
        reason = "训练尚未完成：导出需要一次成功完成的训练，避免导出没训练完的模型。";
      } else if (trainState === "cancelled") {
        reason = "训练已被取消，没有可导出的模型。";
      } else if (trainState === "error") {
        reason = "训练失败，没有可导出的模型。";
      } else if (trainState === "idle") {
        reason = "还没有成功完成的训练记录。";
      }
      if (reason) {
        exportReasonEl.textContent = reason;
      }

      let html = "";
      if (state === "error") {
        html +=
          '<div class="banner banner-danger"><strong>导出失败</strong>' +
          "<p>" + PVL.escapeHtml((s && s.export_error) || "后端未返回具体原因") + "</p>" +
          "<p>一致性校验不通过时系统会拒绝产出模型包。可尝试调整输入尺寸或重新训练后再次导出。</p>" +
          "</div>";
      } else if (state === "running") {
        html +=
          '<div class="banner banner-info"><strong>正在导出</strong>' +
          "<p>正在转换 TFLite 并用固定样本做一致性校验，完成后这里会显示真实结果。</p></div>";
      } else if (state === "done" && s.export_result) {
        const result = s.export_result;
        const consistency = result.consistency || {};
        const passed = Boolean(consistency.passed);
        html +=
          '<div class="banner ' + (passed ? "banner-success" : "banner-danger") + '">' +
          "<strong>" + (passed ? "一致性校验通过，已生成模型包" : "一致性校验未通过，已拒绝导出") + "</strong>" +
          "<p>最大绝对误差 " + PVL.metricValue(consistency.max_abs_error, "", "未采集") +
          "（允许 ≤ " + PVL.escapeHtml(String(consistency.tolerance ?? "0.05")) + "）</p>" +
          "<p>Top-1 一致率 " + PVL.metricValue(consistency.top1_agreement, "", "未采集") +
          "（要求 ≥ " + PVL.escapeHtml(String(consistency.min_top1_agreement ?? "0.98")) + "）</p>" +
          "<p>校验样本数：" + PVL.metricValue(consistency.samples, "", "未采集") + "</p>" +
          "</div>";

        if (result.package_path) {
          html +=
            '<ul class="kv-list">' +
            "<li><span>模型包路径</span><span class=\"mono\">" +
            PVL.escapeHtml(result.package_path) + "</span></li>" +
            "<li><span>TFLite 路径</span><span class=\"mono\">" +
            PVL.escapeHtml(result.tflite_path || "未记录") + "</span></li>" +
            "</ul>";
          exportCopyBtn.hidden = false;
          exportCopyBtn.onclick = function () {
            copyText(result.package_path, "模型包路径已复制");
          };
        } else {
          exportCopyBtn.hidden = true;
        }

        if ((result.warnings || []).length) {
          html +=
            '<div class="banner banner-warning"><strong>导出警告</strong><ul>' +
            result.warnings.map(function (w) {
              return "<li>" + PVL.escapeHtml(w) + "</li>";
            }).join("") +
            "</ul></div>";
        }

        html +=
          '<p class="field-hint">' +
          "下一步：把这个 .pvlmodel.zip 传到手机，在 App 里导入。" +
          '<a href="#/deploy">查看手机部署步骤</a>。' +
          "</p>";
      } else if (state === "idle") {
        html +=
          '<p class="field-hint">' +
          "训练成功完成后才能导出。导出会把 Keras 模型转成 TFLite（float16），" +
          "并用固定样本比对导出前后的输出：最大绝对误差 ≤ 0.05 且 Top-1 一致率 ≥ 98% 才放行，" +
          "否则拒绝产出模型包。" +
          "</p>";
      }

      // 导出可用时清掉原因文字，避免上次的"训练中"残留
      if (!reason) exportReasonEl.textContent = "";

      exportBody.innerHTML = html;
    }

    // ------------------------------------------------------------------
    // 按钮状态
    // ------------------------------------------------------------------

    function renderActions() {
      const s = status;
      const trainState = (s && s.state) || "idle";
      const running = trainState === "running" || trainState === "cancelling";
      const busy = trainState === "running" || trainState === "cancelling" ||
        (s && s.export_state === "running");

      const envReady = Boolean(env && env.ready);
      const preReady = preconditions.opened && preconditions.splitExists &&
        preconditions.classes.length >= 2;

      startBtn.disabled = busy || !envReady || !preReady;
      cancelBtn.hidden = !running;

      let reason = "";
      if (!envReady) {
        reason = "训练环境不可用：请先按上方安装命令安装训练依赖。";
      } else if (!preconditions.opened) {
        reason = "还没有打开数据集：请先在数据集工作区创建或选择数据集。";
      } else if (!preconditions.splitExists) {
        reason = "数据集尚未划分训练/验证集：请先执行“数据体检并划分”。";
      } else if (preconditions.classes.length < 2) {
        reason = "至少需要 2 个类别才能训练分类模型。";
      } else if (trainState === "running") {
        reason = "训练中…可以取消后重新配置参数。";
      } else if (trainState === "cancelling") {
        reason = "正在取消，请等待当前安全停止完成。";
      } else if (s && s.export_state === "running") {
        reason = "正在导出模型包，导出完成后才能再次开始训练。";
      }
      startReason.textContent = reason;
    }

    // ------------------------------------------------------------------
    // 数据加载
    // ------------------------------------------------------------------

    async function loadEnvironment() {
      try {
        env = await PVL.api("/api/train/environment");
        envLoadError = "";
      } catch (error) {
        env = null;
        const info = PVL.describeError(error);
        envLoadError = info.message;
      }
      renderEnvironment();
    }

    async function refreshStatus() {
      if (disposed) return;
      try {
        status = await PVL.api("/api/train/status");
      } catch (error) {
        if (disposed) return;
        const info = PVL.describeError(error);
        progressText.textContent = "无法读取训练状态：" + info.message;
        return;
      }
      if (disposed) return;
      renderProgress();
      appendLogs();
      renderExport();
      renderActions();
    }

    // ------------------------------------------------------------------
    // 事件
    // ------------------------------------------------------------------

    advancedToggle.addEventListener("click", function () {
      const expanded = advancedToggle.getAttribute("aria-expanded") === "true";
      advancedToggle.setAttribute("aria-expanded", expanded ? "false" : "true");
      advancedPanel.hidden = expanded;
      advancedToggle.textContent = expanded ? "高级设置 ▾" : "高级设置 ▴";
    });

    startBtn.addEventListener("click", async function () {
      const epochs = parseInt(paramsCard.querySelector("#train-epochs").value, 10);
      const batch = parseInt(paramsCard.querySelector("#train-batch").value, 10);
      const inputSize = parseInt(paramsCard.querySelector("#train-input").value, 10);
      const lr = parseFloat(paramsCard.querySelector("#train-lr").value);
      const fineTune = parseInt(paramsCard.querySelector("#train-finetune").value, 10);
      const seed = parseInt(paramsCard.querySelector("#train-seed").value, 10);
      const device = deviceSelect.value;

      if (!(epochs >= 1 && epochs <= 50)) {
        PVL.toast("Epochs 需要在 1–50 之间", "warning");
        return;
      }
      if (!(batch >= 4 && batch <= 64)) {
        PVL.toast("Batch 需要在 4–64 之间", "warning");
        return;
      }
      if (INPUT_SIZES.indexOf(inputSize) === -1) {
        PVL.toast("输入尺寸只能是 160 / 192 / 224", "warning");
        return;
      }
      if (!(lr > 0 && lr < 1)) {
        PVL.toast("学习率需要在 0 到 1 之间", "warning");
        return;
      }

      setBusy(startBtn, true, "启动中…", "开始训练");
      try {
        status = await PVL.api("/api/train/start", {
          method: "POST",
          body: {
            epochs: epochs,
            batch_size: batch,
            input_size: inputSize,
            learning_rate: lr,
            fine_tune_last_n: fineTune,
            seed: seed,
            device: device,
          },
        });
        logEl.textContent = "";
        renderedLogCount = 0;
        logPinnedToBottom = true;
        PVL.toast("训练已启动，正在后台运行", "success");
        await refreshStatus();
      } catch (error) {
        const info = PVL.describeError(error);
        PVL.toast("无法开始训练：" + info.message, "danger");
        progressText.textContent = "无法开始训练：" + info.message +
          (info.hint ? "（" + info.hint + "）" : "");
        await refreshStatus();
      } finally {
        setBusy(startBtn, false, "", "开始训练");
      }
    });

    cancelBtn.addEventListener("click", async function () {
      const ok = window.confirm(
        "确定取消这次训练吗？\n" +
        "取消会在当前这一步安全停止，已产生的中间产物会保留，但不会得到最终模型。"
      );
      if (!ok) return;
      setBusy(cancelBtn, true, "取消中…", "取消训练");
      try {
        status = await PVL.api("/api/train/cancel", { method: "POST" });
        PVL.toast("已请求取消，正在安全停止", "info");
        await refreshStatus();
      } catch (error) {
        const info = PVL.describeError(error);
        PVL.toast("取消失败：" + info.message, "danger");
      } finally {
        setBusy(cancelBtn, false, "", "取消训练");
      }
    });

    exportBtn.addEventListener("click", async function () {
      setBusy(exportBtn, true, "导出中…", "导出模型包");
      try {
        status = await PVL.api("/api/train/export", { method: "POST" });
        PVL.toast("导出已开始，正在后台转换与校验", "info");
        await refreshStatus();
      } catch (error) {
        const info = PVL.describeError(error);
        PVL.toast("无法导出：" + info.message, "danger");
        await refreshStatus();
      } finally {
        setBusy(exportBtn, false, "", "导出模型包");
      }
    });

    // ------------------------------------------------------------------
    // 启动
    // ------------------------------------------------------------------

    renderEnvironment();
    renderPreconditions();
    renderProgress();
    renderExport();
    renderActions();

    await loadEnvironment();
    await loadPreconditions();
    renderPreconditions();
    renderActions();
    await refreshStatus();

    timer = setInterval(function () {
      refreshStatus();
    }, POLL_MS);

    // 清理函数：离开页面时停掉轮询，并阻止进行中的回调再写 DOM
    return function cleanup() {
      disposed = true;
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };
  },
};
