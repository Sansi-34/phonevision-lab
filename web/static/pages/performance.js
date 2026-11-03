/**
 * PhoneVision Lab Web — 性能分析页。
 *
 * 目标：只报告真实采集到的指标。这一页是"诚实"最容易被破坏的地方，规则写死在组件里：
 *   - null ≠ 0：没采到的数据统一显示"— 未采集"，绝不用 0 或示例值填充；
 *   - 只统计电脑实测到的传输指标（采集帧率来自手机 /ping 自报，接收/显示帧率与丢帧来自电脑）；
 *   - 手机推理、各阶段耗时、硬件命令耗时没有数据来源 → 全部"未采集"并说明原因；
 *   - 功耗固定"不支持"：电脑端不测量手机功耗。
 *
 * 数据来源：
 *   POST /api/perf/start  {warmup, duration}
 *   POST /api/perf/stop
 *   GET  /api/perf/status {running,has_record,phase,elapsed,total,metrics,exports}
 *   GET  /api/perf/export?kind=csv|json|txt → {path}
 */
window.PVL_PAGES = window.PVL_PAGES || {};

window.PVL_PAGES.performance = {
  render: async function (root) {
    const POLL_MS = 1000;
    const UNAVAILABLE = "未采集";

    let disposed = false;
    let status = null;
    let timer = null;

    // ------------------------------------------------------------------
    // 小工具
    // ------------------------------------------------------------------

    function metricTile(label, value, unit, note) {
      return (
        '<div class="metric-tile">' +
        '<span class="metric-label">' + PVL.escapeHtml(label) + "</span>" +
        PVL.metricValue(value, unit || "", UNAVAILABLE) +
        (note ? '<span class="metric-note">' + PVL.escapeHtml(note) + "</span>" : "") +
        "</div>"
      );
    }

    /** 把 {mean,p50,p95,count} 渲染成"均值 / P50 / P95"三段，未采集显示"— 未采集"。 */
    function stageTile(label, stats, note) {
      let value = null;
      let unit = " ms";
      if (stats && typeof stats === "object") {
        if (stats.mean !== null && stats.mean !== undefined) value = stats.mean;
        else if (stats.p50 !== null && stats.p50 !== undefined) value = stats.p50;
      }
      const detail = stats && typeof stats === "object"
        ? ("P50 " + PVL.metricValue(stats.p50, " ms", UNAVAILABLE) +
           " · P95 " + PVL.metricValue(stats.p95, " ms", UNAVAILABLE) +
           " · 样本 " + PVL.metricValue(stats.count, "", UNAVAILABLE))
        : "";
      return (
        '<div class="metric-tile">' +
        '<span class="metric-label">' + PVL.escapeHtml(label) + "</span>" +
        PVL.metricValue(value, unit, UNAVAILABLE) +
        (detail ? '<span class="metric-note">' + detail + "</span>" : "") +
        (note ? '<span class="metric-note">' + PVL.escapeHtml(note) + "</span>" : "") +
        "</div>"
      );
    }

    function mmss(seconds) {
      const total = Math.max(0, Math.round(Number(seconds) || 0));
      const m = Math.floor(total / 60);
      const s = total % 60;
      return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
    }

    // ------------------------------------------------------------------
    // 页面骨架
    // ------------------------------------------------------------------

    root.appendChild(PVL.el(
      '<section class="page-head">' +
        "<h1>性能分析</h1>" +
        '<p class="page-lede">' +
          "按固定流程（预热 → 定时长采样）记录真实传输指标，并导出成 CSV / 摘要 / JSON。" +
          "只统计真实采集到的数据，没有接入的项一律显示“未采集”。" +
        "</p>" +
      "</section>"
    ));

    root.appendChild(PVL.el(
      '<div class="banner banner-info">' +
        "<strong>本页只使用真实采集数据</strong>" +
        "<p>性能图表与报告中的每个数字都来自本次采样的真实测量，本页不显示任何示例数据、预填值或演示曲线。</p>" +
        "<p>没有采集到的指标显示“— 未采集”，它不代表 0；功耗在本页固定为“不支持”。</p>" +
      "</div>"
    ));

    // ---- 测试控制条 ----
    const controlBar = PVL.el(
      '<section class="card">' +
        '<div class="card-header">' +
          '<h2 class="card-title">测试控制</h2>' +
          '<span id="perf-phase-badge"></span>' +
        "</div>" +
        '<div class="card-body">' +
          '<div class="field-grid">' +
            '<div class="field">' +
              '<label class="field-label" for="perf-warmup">预热秒数</label>' +
              '<input class="field-input" id="perf-warmup" type="number" min="0" max="60" step="1" value="3">' +
              '<p class="field-hint">预热期不计入统计，用于让链路进入稳定状态。</p>' +
            "</div>" +
            '<div class="field">' +
              '<label class="field-label" for="perf-duration">时长秒数</label>' +
              '<input class="field-input" id="perf-duration" type="number" min="1" max="3600" step="1" value="60">' +
              '<p class="field-hint">默认 60 秒；短于 10 秒的采样不建议用于汇报。</p>' +
            "</div>" +
          '</div>' +
          '<div class="banner-actions">' +
            '<button class="btn btn-primary" type="button" id="perf-start">开始测试</button>' +
            '<button class="btn btn-secondary" type="button" id="perf-stop" disabled>停止测试</button>' +
            '<span class="field-hint" id="perf-control-reason"></span>' +
          '</div>' +
          '<p class="field-hint" id="perf-progress-text">尚未开始测试。</p>' +
        '</div>' +
      '</section>'
    );
    root.appendChild(controlBar);

    // ---- 采集与传输 ----
    const transportCard = PVL.el(
      '<section class="card">' +
        '<div class="card-header">' +
          '<h2 class="card-title">采集与传输</h2>' +
          '<span class="badge badge-success">电脑实测</span>' +
        "</div>" +
        '<div class="card-body"><div class="metric-grid" id="perf-transport"></div></div>' +
      "</section>"
    );
    root.appendChild(transportCard);

    // ---- 手机推理 ----
    const inferenceCard = PVL.el(
      '<section class="card">' +
        '<div class="card-header">' +
          '<h2 class="card-title">手机推理</h2>' +
          '<span class="badge badge-warning">未接入</span>' +
        "</div>" +
        '<div class="card-body">' +
          '<div class="metric-grid" id="perf-inference"></div>' +
          '<p class="field-hint">手机端尚未向电脑上报推理数据，因此以上各项均为“未采集”。</p>' +
        '</div>' +
      "</section>"
    );
    root.appendChild(inferenceCard);

    // ---- 硬件联动 ----
    const hardwareCard = PVL.el(
      '<section class="card">' +
        '<div class="card-header">' +
          '<h2 class="card-title">硬件联动</h2>' +
          '<span class="badge badge-warning">未接入</span>' +
        "</div>" +
        '<div class="card-body">' +
          '<div class="metric-grid" id="perf-hardware"></div>' +
          '<p class="field-hint">硬件命令事件尚未进入本服务的性能记录，因此以上各项均为“未采集”。</p>' +
        '</div>' +
      '</section>'
    );
    root.appendChild(hardwareCard);

    // ---- 功耗 ----
    const powerCard = PVL.el(
      '<section class="card">' +
        '<div class="card-header">' +
          '<h2 class="card-title">功耗</h2>' +
          '<span class="badge badge-neutral">不支持</span>' +
        '</div>' +
        '<div class="card-body">' +
          '<p class="metric-big">不支持</p>' +
          '<p class="field-hint">' +
          "电脑端不测量手机功耗，也不把电量百分比变化当成功率。" +
          "只有设备提供真实电流 / 电压数据源时才显示，并且必须区分“实测 / 估算 / 电量变化”。</p>" +
        '</div>' +
      '</section>'
    );
    root.appendChild(powerCard);

    // ---- 测试流程与环境 ----
    const procedureCard = PVL.el(
      '<section class="card">' +
        '<div class="card-header"><h2 class="card-title">测试流程与环境</h2></div>' +
        '<div class="card-body" id="perf-procedure">' +
          '<div class="skeleton skeleton-block"></div>' +
        "</div>" +
      "</section>"
    );
    root.appendChild(procedureCard);

    // ---- 导出 ----
    const exportCard = PVL.el(
      '<section class="card">' +
        '<div class="card-header"><h2 class="card-title">导出报告</h2></div>' +
        '<div class="card-body">' +
          '<div class="banner-actions">' +
            '<button class="btn btn-secondary" type="button" id="perf-export-csv">导出 CSV</button>' +
            '<button class="btn btn-secondary" type="button" id="perf-export-txt">导出摘要 txt</button>' +
            '<button class="btn btn-secondary" type="button" id="perf-export-json">导出 JSON</button>' +
            '<span class="field-hint" id="perf-export-reason"></span>' +
          '</div>' +
          '<p class="field-hint">导出成功后会用提示框显示真实文件路径。' +
          '报告只包含电脑端已采集到的指标，未采集项在报告中为空值。</p>' +
        '</div>' +
      "</section>"
    );
    root.appendChild(exportCard);

    root.appendChild(PVL.el(
      '<div class="banner banner-info">' +
        "<strong>图例</strong>" +
        "<p>“— 未采集”表示该项没有采集到真实数据，不代表 0；" +
        "没有接入的指标不会用估算值或示例值填充。</p>" +
      "</div>"
    ));

    const phaseBadge = controlBar.querySelector("#perf-phase-badge");
    const warmupInput = controlBar.querySelector("#perf-warmup");
    const durationInput = controlBar.querySelector("#perf-duration");
    const startBtn = controlBar.querySelector("#perf-start");
    const stopBtn = controlBar.querySelector("#perf-stop");
    const controlReason = controlBar.querySelector("#perf-control-reason");
    const progressText = controlBar.querySelector("#perf-progress-text");
    const transportEl = transportCard.querySelector("#perf-transport");
    const inferenceEl = inferenceCard.querySelector("#perf-inference");
    const hardwareEl = hardwareCard.querySelector("#perf-hardware");
    const procedureEl = procedureCard.querySelector("#perf-procedure");
    const exportReason = exportCard.querySelector("#perf-export-reason");
    const exportButtons = {
      csv: exportCard.querySelector("#perf-export-csv"),
      txt: exportCard.querySelector("#perf-export-txt"),
      json: exportCard.querySelector("#perf-export-json"),
    };

    // ------------------------------------------------------------------
    // 渲染
    // ------------------------------------------------------------------

    function renderTransport(metrics) {
      const t = (metrics && metrics.capture_and_transport) || {};
      const notes = {
        phone_capture_fps: "口径：手机 /ping 自报的采集帧率（手机侧测得）",
        pc_receive_fps: "口径：电脑每秒成功解析的帧数",
        pc_display_fps: "口径：电脑实际绘制的帧数",
        dropped_frames: "口径：手机上报帧号增量 − 电脑实际解析增量（被丢弃的旧帧，不是坏帧）",
        sample_count: "口径：采样窗口内的有效采样次数",
      };
      transportEl.innerHTML =
        metricTile("手机采集帧率", t.phone_capture_fps, " fps", notes.phone_capture_fps) +
        metricTile("电脑接收帧率", t.pc_receive_fps, " fps", notes.pc_receive_fps) +
        metricTile("电脑显示帧率", t.pc_display_fps, " fps", notes.pc_display_fps) +
        metricTile("丢帧", t.dropped_frames, "", notes.dropped_frames) +
        metricTile("采样次数", t.sample_count, "", notes.sample_count);
    }

    function renderInference(metrics) {
      const i = (metrics && metrics.inference) || {};
      inferenceEl.innerHTML =
        metricTile("推理帧率", i.phone_inference_fps, " fps",
          "口径：手机端实测的推理帧率（本服务未接入）") +
        metricTile("完成帧", i.completed, "", "口径：手机端完成推理的帧数（本服务未接入）") +
        metricTile("跳过帧", i.skipped, "", "口径：手机端来不及推理而跳过的帧数（本服务未接入）") +
        stageTile("预处理", i.preprocess, "口径：手机端单帧预处理耗时（本服务未接入）") +
        stageTile("模型执行", i.model, "口径：手机端单帧模型执行耗时（本服务未接入）") +
        stageTile("后处理", i.postprocess, "口径：手机端单帧后处理耗时（本服务未接入）");
    }

    function renderHardware(metrics) {
      const h = (metrics && metrics.hardware) || {};
      hardwareEl.innerHTML =
        metricTile("命令数", h.commands_sent, "", "口径：测试期间发送的命令总数（未接入）") +
        metricTile("已执行", h.commands_executed, "", "口径：控制器确认已执行的命令数（未接入）") +
        stageTile("命令确认耗时", h.command_ack,
          "口径：命令发送到控制器确认的耗时；设备只确认接收时不等于机械动作完成");
    }

    function renderProcedure(metrics) {
      const p = (metrics && metrics.procedure) || {};
      const env = (metrics && metrics.environment) || {};
      procedureEl.innerHTML =
        '<ul class="kv-list">' +
        "<li><span>预热秒数</span><span>" +
        PVL.metricValue(p.warmup_seconds, " s", UNAVAILABLE) + "</span></li>" +
        "<li><span>实际采样时长</span><span>" +
        PVL.metricValue(p.duration_seconds, " s", UNAVAILABLE) + "</span></li>" +
        "<li><span>客户端版本</span><span>" +
        PVL.escapeHtml(env.client_version || "未记录") + "</span></li>" +
        "<li><span>设备型号</span><span>" +
        PVL.escapeHtml(env.device_model || "未记录") + "</span></li>" +
        "<li><span>系统版本</span><span>" +
        PVL.escapeHtml(env.os_version || "未记录") + "</span></li>" +
        "<li><span>备注</span><span>" + PVL.escapeHtml(p.notes || "（无）") + "</span></li>" +
        '</ul>' +
        '<p class="field-hint">预热不计入统计；提前停止时备注里会记录实际采样时长。</p>';
    }

    function renderControls() {
      const running = Boolean(status && status.running);
      const hasRecord = Boolean(status && status.has_record);
      const phase = (status && status.phase) || "idle";

      const phaseMap = {
        idle: ["badge-neutral", "空闲"],
        warmup: ["badge-info", "预热中"],
        sampling: ["badge-success", "采样中"],
        finished: ["badge-success", "已完成"],
      };
      const found = phaseMap[phase] || ["badge-neutral", phase];
      phaseBadge.innerHTML =
        '<span class="badge ' + found[0] + '">' + PVL.escapeHtml(found[1]) + "</span>";

      warmupInput.disabled = running;
      durationInput.disabled = running;
      startBtn.disabled = running;
      startBtn.textContent = running ? "测试中…" : "开始测试";
      stopBtn.disabled = !running;

      Object.keys(exportButtons).forEach(function (kind) {
        exportButtons[kind].disabled = !hasRecord;
      });

      let reason = "";
      if (!hasRecord) {
        reason = "还没有测试记录：先运行一次性能测试，报告需要至少 1 秒有效数据。";
      } else if (running) {
        reason = "测试进行中：预热与时长已锁定，避免口径漂移。";
      } else if (phase === "finished") {
        const transport = (status.metrics && status.metrics.capture_and_transport) || {};
        if (transport.phone_capture_fps === null || transport.phone_capture_fps === undefined) {
          reason = "本次测试没有采集到帧，导出报告里传输指标会是空值。";
        } else {
          reason = "本次测试已结束，可以导出报告（产物保存在本机 exports 目录）。";
        }
      }
      exportReason.textContent = reason;

      if (running) {
        if (phase === "warmup") {
          const warmup = Number(status.warmup_seconds) || 0;
          // elapsed 在预热期从 0 开始累加，因此"已预热 = warmup - elapsed"
          const warmed = Math.max(0, Math.min(warmup, warmup - (Number(status.elapsed) || 0)));
          progressText.textContent =
            "预热中（不计入统计）：已预热 " + mmss(warmed) +
            " / " + mmss(warmup) + "。预热数据不计入最终统计。";
        } else {
          progressText.textContent =
            "采样中 " + mmss(status.elapsed) + " / " + mmss(status.total) +
            "（预热 " + mmss(status.warmup_seconds) + " 已结束，预热数据不计入统计）。";
        }
      } else if (hasRecord) {
        progressText.textContent =
          "测试已结束：实际采样 " + mmss(status.elapsed) + " / 计划 " + mmss(status.total) +
          "。导出后可用表格软件复核。";
      } else {
        progressText.textContent = "尚未开始测试。";
      }

      // 开始测试的前置条件说明（未连接手机时禁用并说明原因）
      if (running) {
        controlReason.textContent = "测试进行中，可以随时提前停止。";
      } else {
        controlReason.textContent =
          "开始测试需要先连接手机：性能测试只统计真实推流数据，没有连接时采不到任何帧。";
      }
    }

    function renderMetrics() {
      const metrics = (status && status.metrics) || null;
      if (!metrics) {
        transportEl.innerHTML =
          metricTile("手机采集帧率", null, " fps", "口径：手机 /ping 自报的采集帧率") +
          metricTile("电脑接收帧率", null, " fps", "口径：电脑每秒成功解析的帧数") +
          metricTile("电脑显示帧率", null, " fps", "口径：电脑实际绘制的帧数") +
          metricTile("丢帧", null, "", "口径：被丢弃的旧帧，不是坏帧") +
          metricTile("采样次数", null, "", "口径：采样窗口内的有效采样次数");
        inferenceEl.innerHTML =
          metricTile("推理帧率", null, " fps", "口径：手机端实测（本服务未接入）") +
          metricTile("完成帧", null, "", "口径：手机端完成推理的帧数（未接入）") +
          metricTile("跳过帧", null, "", "口径：来不及推理而跳过的帧数（未接入）") +
          stageTile("预处理", null, "口径：手机端单帧预处理耗时（未接入）") +
          stageTile("模型执行", null, "口径：手机端单帧模型执行耗时（未接入）") +
          stageTile("后处理", null, "口径：手机端单帧后处理耗时（未接入）");
        hardwareEl.innerHTML =
          metricTile("命令数", null, "", "口径：测试期间发送的命令总数（未接入）") +
          metricTile("已执行", null, "", "口径：控制器确认已执行的命令数（未接入）") +
          stageTile("命令确认耗时", null, "口径：命令发送到控制器确认的耗时（未接入）");
        procedureEl.innerHTML =
          '<ul class="kv-list">' +
          "<li><span>预热秒数</span><span>" + PVL.metricValue(null, " s", UNAVAILABLE) + "</span></li>" +
          "<li><span>实际采样时长</span><span>" + PVL.metricValue(null, " s", UNAVAILABLE) + "</span></li>" +
          "<li><span>客户端版本</span><span>未记录</span></li>" +
          "<li><span>设备型号</span><span>未记录</span></li>" +
          "<li><span>系统版本</span><span>未记录</span></li>" +
          "</ul>";
        return;
      }
      renderTransport(metrics);
      renderInference(metrics);
      renderHardware(metrics);
      renderProcedure(metrics);
    }

    // ------------------------------------------------------------------
    // 数据加载
    // ------------------------------------------------------------------

    async function refreshStatus() {
      if (disposed) return;
      try {
        status = await PVL.api("/api/perf/status");
      } catch (error) {
        if (disposed) return;
        const info = PVL.describeError(error);
        progressText.textContent = "无法读取性能状态：" + info.message;
        return;
      }
      if (disposed) return;
      renderControls();
      renderMetrics();
    }

    async function runExport(kind) {
      const button = exportButtons[kind];
      const idleText = { csv: "导出 CSV", txt: "导出摘要 txt", json: "导出 JSON" }[kind];
      button.disabled = true;
      button.textContent = "导出中…";
      try {
        const data = await PVL.api("/api/perf/export?kind=" + encodeURIComponent(kind));
        const path = (data && data.path) || "";
        if (path) {
          PVL.toast("已导出：" + path, "success");
        } else {
          PVL.toast("导出完成，但服务端没有返回文件路径", "warning");
        }
      } catch (error) {
        const info = PVL.describeError(error);
        PVL.toast("导出失败：" + info.message, "danger");
      } finally {
        button.textContent = idleText;
        renderControls();
      }
    }

    // ------------------------------------------------------------------
    // 事件绑定
    // ------------------------------------------------------------------

    startBtn.addEventListener("click", async function () {
      const warmup = parseFloat(warmupInput.value);
      const duration = parseFloat(durationInput.value);
      if (!(warmup >= 0 && warmup <= 60)) {
        PVL.toast("预热秒数需要在 0–60 之间", "warning");
        return;
      }
      if (!(duration >= 1 && duration <= 3600)) {
        PVL.toast("时长秒数需要在 1–3600 之间", "warning");
        return;
      }
      startBtn.disabled = true;
      startBtn.textContent = "启动中…";
      try {
        status = await PVL.api("/api/perf/start", {
          method: "POST",
          body: { warmup: warmup, duration: duration },
        });
        PVL.toast("性能测试已开始，正在预热", "success");
        await refreshStatus();
      } catch (error) {
        const info = PVL.describeError(error);
        // 未连接手机时把真实原因显示在控制条上，同时弹出提示
        controlReason.textContent = "无法开始测试：" + info.message +
          (info.hint ? "（" + info.hint + "）" : "");
        PVL.toast("无法开始测试：" + info.message, "danger");
        await refreshStatus();
      } finally {
        renderControls();
      }
    });

    stopBtn.addEventListener("click", async function () {
      stopBtn.disabled = true;
      stopBtn.textContent = "停止中…";
      try {
        status = await PVL.api("/api/perf/stop", { method: "POST" });
        PVL.toast("测试已停止，可以导出报告", "info");
        await refreshStatus();
      } catch (error) {
        const info = PVL.describeError(error);
        PVL.toast("停止失败：" + info.message, "danger");
        await refreshStatus();
      } finally {
        renderControls();
      }
    });

    Object.keys(exportButtons).forEach(function (kind) {
      exportButtons[kind].addEventListener("click", function () { runExport(kind); });
    });

    // ------------------------------------------------------------------
    // 启动
    // ------------------------------------------------------------------

    renderControls();
    renderMetrics();
    await refreshStatus();

    timer = setInterval(function () {
      refreshStatus();
    }, POLL_MS);

    return function cleanup() {
      disposed = true;
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };
  },
};
