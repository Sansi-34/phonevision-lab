/**
 * PhoneVision Lab Web — 实验台页面（手机与实时视觉）。
 *
 * 职责：
 *   - 连接 / 断开 / 重连手机（局域网 MJPEG 推流），展示真实连接状态；
 *   - 用 <img> 轮询 /api/vision/frame 显示手机画面（画面由本地服务解析 MJPEG 流后提供）；
 *   - 切换 5 种视觉模式、按模式调整参数（滑块 + 300ms 防抖）；
 *   - 展示真实传输指标（采集/接收/显示帧率、丢帧、带宽、分辨率、无效帧），
 *     每项都写口径；未连接时一律 "— 未采集"，不用 0 填充；
 *   - 截图、跳转数据集工作区。
 *
 * 诚实边界（本页最容易造假的地方）：
 *   - 浏览器不能直接读取手机的 multipart MJPEG 流（<img> 只认单张 JPEG，
 *     且手机没有 CORS 头），所以画面一定来自本地服务解析后的单帧接口；
 *   - "从未连接"与"连接过但画面中断"是两种状态，文案分开写，不混为一谈；
 *   - 显示帧率由前端"每显示一帧"回调 POST /api/vision/displayed 累加，
 *     节流到每秒最多 1 次，避免把统计请求打成请求风暴；
 *   - 取帧失败时保留最近一次成功帧并标注"画面已中断"，绝不显示裂图。
 *
 * 样式约定（web/static/styles.css，不新增任何类）：
 *   .app-split--left 承载「连接卡 300px | 主区」，主区内再套 .app-split
 *   承载「画面 + 指标 | 检查器 360px」；<1100px 自动变单列。
 *   画面容器用 .stage（4:3 深底）+ 四角 .stage__tag；中断态用 .stage.is-stale。
 */
(function () {
  "use strict";

  // 画面轮询间隔：200ms 一次（约 5 帧/秒上限，够看且不压满本地服务）。
  var FRAME_INTERVAL_MS = 200;
  // 连接状态轮询间隔：断流检测靠它，1 秒足够及时又不吵闹。
  var STATUS_INTERVAL_MS = 1000;
  // 参数滑块防抖：拖动时不要每个 input 事件都打后端。
  var PARAM_DEBOUNCE_MS = 300;
  // "已显示一帧"回调节流：1 秒 1 次（后端只按秒累计显示帧数）。
  var DISPLAYED_THROTTLE_MS = 1000;
  // 轮询帧质量（snapshot 接口自带固定高质量，与这里无关）。
  var FRAME_QUALITY = 82;

  var page = {
    render: function (root) {
      root.innerHTML =
        '<details class="lab-explainer"><summary>画面从哪来</summary><div class="banner banner-info">' +
          '<div class="banner__content">' +
            '<span class="banner__body">手机推送的是 MJPEG 流，浏览器不能直接读取' +
            "（<code>&lt;img&gt;</code> 只认单张 JPEG，且手机没有跨域头）。" +
            "因此由本机服务解析这条流，页面只取服务端给出的单帧；" +
            "断开连接后画面会立即停更，不会播放缓存视频。</span>" +
          "</div>" +
        "</div></details>" +

        '<div class="app-split app-split--left">' +

          // ---- 左栏 300px：连接 ---- //
          '<section class="card" id="lab-connect-card" aria-labelledby="lab-connect-title">' +
            '<div class="card-header">' +
              '<h2 class="card-title" id="lab-connect-title">连接手机</h2>' +
              '<span class="pill pill-neutral" id="lab-state-pill">' +
                '<span class="pill-dot" aria-hidden="true"></span>' +
                '<span id="lab-state-pill-text">未连接</span>' +
              "</span>" +
            "</div>" +
            '<div class="card-body">' +
              '<div class="field">' +
                '<label class="field-label" for="lab-host">手机 IP 地址</label>' +
                '<input class="field-input" id="lab-host" type="text" inputmode="decimal" ' +
                  'autocomplete="off" spellcheck="false" placeholder="192.168.2.14">' +
                '<p class="field-hint">以手机 App 屏幕上显示的地址为准；换了 Wi-Fi 会变。</p>' +
              "</div>" +
              '<div class="field">' +
                '<label class="field-label" for="lab-port">端口</label>' +
                '<input class="field-input" id="lab-port" type="text" inputmode="numeric" ' +
                  'autocomplete="off" value="8080">' +
                '<p class="field-hint">手机 App 默认推流端口 8080。</p>' +
              "</div>" +
              '<div class="actions">' +
                '<button class="btn btn-primary" type="button" id="lab-connect-btn">连接</button>' +
                '<button class="btn btn-secondary" type="button" id="lab-disconnect-btn" disabled>' +
                  "断开</button>" +
                '<button class="btn btn-ghost" type="button" id="lab-reconnect-btn" disabled>' +
                  "重新连接</button>" +
              "</div>" +
              '<div class="banner banner-danger" id="lab-connect-error" hidden></div>' +

              '<ol class="step-list" id="lab-steps">' +
                '<li class="step-item is-active" id="lab-step-wifi">' +
                  '<span class="step-item__index" aria-hidden="true">1</span>' +
                  '<span class="step-item__content">' +
                    '<span class="step-item__title">连同一个 Wi-Fi</span>' +
                    '<span class="step-item__desc">手机和电脑必须在同一局域网，不要用手机热点做桥接。</span>' +
                  "</span>" +
                "</li>" +
                '<li class="step-item" id="lab-step-app">' +
                  '<span class="step-item__index" aria-hidden="true">2</span>' +
                  '<span class="step-item__content">' +
                    '<span class="step-item__title">手机 App 点开始推流</span>' +
                    '<span class="step-item__desc">屏幕上会显示地址，例如 192.168.2.14:8080。</span>' +
                  "</span>" +
                "</li>" +
                '<li class="step-item" id="lab-step-ip">' +
                  '<span class="step-item__index" aria-hidden="true">3</span>' +
                  '<span class="step-item__content">' +
                    '<span class="step-item__title">把 IP 填到上面并连接</span>' +
                    '<span class="step-item__desc">服务会先请求 /ping 确认手机在线，再开始接收画面。</span>' +
                  "</span>" +
                "</li>" +
              "</ol>" +
            "</div>" +
          "</section>" +

          // ---- 主区 ---- //
          '<div class="app-split__main">' +
            '<div class="app-split">' +

              // ---- 画面 + 指标 ---- //
              '<div class="app-split__main">' +
                '<section class="card" aria-labelledby="lab-stage-title">' +
                  '<div class="card-header">' +
                    '<h2 class="card-title" id="lab-stage-title">实时画面</h2>' +
                    '<span class="badge badge-neutral" id="lab-mode-badge">原始</span>' +
                  "</div>" +
                  '<div class="card-body">' +
                    '<div class="stage" id="lab-stage" hidden>' +
                      '<img id="lab-frame" alt="手机摄像头当前画面，由本地服务解析 MJPEG 流后提供" hidden>' +
                      '<span class="stage__tag stage__tag--tl" id="lab-tag-mode">原始</span>' +
                      '<span class="stage__tag stage__tag--tr" id="lab-tag-res">分辨率 —</span>' +
                      '<span class="stage__tag stage__tag--bl">本地服务解析 MJPEG 流</span>' +
                      '<span class="stage__tag stage__tag--br" id="lab-tag-state">未连接</span>' +
                    "</div>" +
                    '<div class="empty-state" id="lab-empty">' +
                      '<h3 id="lab-empty-title">还没有画面</h3>' +
                      '<p id="lab-empty-desc">先在左边填手机 IP 并连接。连接成功后这里会显示摄像头实时画面。</p>' +
                    "</div>" +
                    '<div class="metric-strip" id="lab-metrics">' +
                      '<div class="metric-tile metric-tile--empty" ' +
                        'title="口径：手机 /ping 自报的采集帧率（手机侧测得）">' +
                        '<span class="metric-tile__label">手机采集帧率</span>' +
                        '<span class="metric-tile__value" id="lab-m-phone">—</span>' +
                        '<span class="metric-tile__note">口径：手机自报</span>' +
                      "</div>" +
                      '<div class="metric-tile metric-tile--empty" ' +
                        'title="口径：电脑每秒成功解析的帧数">' +
                        '<span class="metric-tile__label">接收帧率</span>' +
                        '<span class="metric-tile__value" id="lab-m-receive">—</span>' +
                        '<span class="metric-tile__note">口径：电脑解析成功</span>' +
                      "</div>" +
                      '<div class="metric-tile metric-tile--empty" ' +
                        'title="口径：电脑实际绘制到屏幕的帧数，由本页每显示一帧回调累加">' +
                        '<span class="metric-tile__label">显示帧率</span>' +
                        '<span class="metric-tile__value" id="lab-m-display">—</span>' +
                        '<span class="metric-tile__note">口径：电脑实际绘制</span>' +
                      "</div>" +
                      '<div class="metric-tile metric-tile--empty" ' +
                        'title="口径：手机送出但电脑来不及消费而被丢弃的旧帧，不是坏帧">' +
                        '<span class="metric-tile__label">丢帧</span>' +
                        '<span class="metric-tile__value" id="lab-m-dropped">—</span>' +
                        '<span class="metric-tile__note">口径：被丢弃的旧帧</span>' +
                      "</div>" +
                      '<div class="metric-tile metric-tile--empty" ' +
                        'title="口径：电脑每秒收到的 JPEG 字节数换算">' +
                        '<span class="metric-tile__label">带宽</span>' +
                        '<span class="metric-tile__value" id="lab-m-bandwidth">—</span>' +
                        '<span class="metric-tile__note">口径：下行 Mbps</span>' +
                      "</div>" +
                      '<div class="metric-tile metric-tile--empty" ' +
                        'title="口径：手机 /ping 自报的摄像头分辨率">' +
                        '<span class="metric-tile__label">分辨率</span>' +
                        '<span class="metric-tile__value" id="lab-m-resolution">—</span>' +
                        '<span class="metric-tile__note">口径：手机自报</span>' +
                      "</div>" +
                      '<div class="metric-tile metric-tile--empty" ' +
                        'title="口径：电脑收到的字节中无法解析成 JPEG 的帧数">' +
                        '<span class="metric-tile__label">无效帧</span>' +
                        '<span class="metric-tile__value" id="lab-m-invalid">—</span>' +
                        '<span class="metric-tile__note">口径：解析失败的帧</span>' +
                      "</div>" +
                    "</div>" +
                    '<p class="field-hint">以上都是传输指标。手机推理帧率与各阶段耗时在手机端，' +
                      "电脑未接入，因此本页不显示。</p>" +
                  "</div>" +
                "</section>" +
              "</div>" +

              // ---- 右栏 360px：检查器 ---- //
              '<div class="app-split__aside">' +
                '<section class="card" aria-labelledby="lab-inspector-title">' +
                  '<div class="card-header">' +
                    '<h2 class="card-title" id="lab-inspector-title">视觉检查器</h2>' +
                  "</div>" +
                  '<div class="card-body">' +
                    '<div class="mode-segment mode-segment--block" id="lab-mode-segment" ' +
                      'role="group" aria-label="视觉模式">' +
                      '<span class="skeleton skeleton--text"></span>' +
                    "</div>" +
                    '<div id="lab-params"></div>' +
                    '<div class="banner banner-info" id="lab-mode-hint">' +
                      '<div class="banner__content"><p></p></div>' +
                    "</div>" +
                    '<hr class="divider">' +
                    '<div class="actions">' +
                      '<button class="btn btn-secondary" type="button" id="lab-snapshot-btn" disabled>' +
                        "保存截图</button>" +
                      '<span class="btn-reason" id="lab-snapshot-reason">' +
                        "未连接手机：没有画面可截图。</span>" +
                    "</div>" +
                    '<div class="actions">' +
                      '<a class="btn btn-primary" href="#/dataset" id="lab-goto-dataset">去采集数据</a>' +
                      '<span class="btn-reason" id="lab-goto-dataset-reason">' +
                        "正在检测数据集状态…</span>" +
                    "</div>" +
                  "</div>" +
                "</section>" +
              "</div>" +

            "</div>" +
          "</div>" +

        "</div>";

      // ---- DOM 引用 ----
      var frameImg = root.querySelector("#lab-frame");
      var stage = root.querySelector("#lab-stage");
      var emptyBox = root.querySelector("#lab-empty");
      var emptyTitle = root.querySelector("#lab-empty-title");
      var emptyDesc = root.querySelector("#lab-empty-desc");
      var hostInput = root.querySelector("#lab-host");
      var portInput = root.querySelector("#lab-port");
      var connectBtn = root.querySelector("#lab-connect-btn");
      var disconnectBtn = root.querySelector("#lab-disconnect-btn");
      var reconnectBtn = root.querySelector("#lab-reconnect-btn");
      var statePill = root.querySelector("#lab-state-pill");
      var statePillText = root.querySelector("#lab-state-pill-text");
      var connectError = root.querySelector("#lab-connect-error");
      var steps = {
        wifi: root.querySelector("#lab-step-wifi"),
        app: root.querySelector("#lab-step-app"),
        ip: root.querySelector("#lab-step-ip"),
      };
      var modeSegment = root.querySelector("#lab-mode-segment");
      var paramsBox = root.querySelector("#lab-params");
      var modeHint = root.querySelector("#lab-mode-hint");
      var modeBadge = root.querySelector("#lab-mode-badge");
      var tagMode = root.querySelector("#lab-tag-mode");
      var tagRes = root.querySelector("#lab-tag-res");
      var tagState = root.querySelector("#lab-tag-state");
      var snapshotBtn = root.querySelector("#lab-snapshot-btn");
      var snapshotReason = root.querySelector("#lab-snapshot-reason");
      var gotoReason = root.querySelector("#lab-goto-dataset-reason");

      var metricTiles = {
        phone: root.querySelector("#lab-m-phone").closest(".metric-tile"),
        receive: root.querySelector("#lab-m-receive").closest(".metric-tile"),
        display: root.querySelector("#lab-m-display").closest(".metric-tile"),
        dropped: root.querySelector("#lab-m-dropped").closest(".metric-tile"),
        bandwidth: root.querySelector("#lab-m-bandwidth").closest(".metric-tile"),
        resolution: root.querySelector("#lab-m-resolution").closest(".metric-tile"),
        invalid: root.querySelector("#lab-m-invalid").closest(".metric-tile"),
      };
      var metricNodes = {
        phone: root.querySelector("#lab-m-phone"),
        receive: root.querySelector("#lab-m-receive"),
        display: root.querySelector("#lab-m-display"),
        dropped: root.querySelector("#lab-m-dropped"),
        bandwidth: root.querySelector("#lab-m-bandwidth"),
        resolution: root.querySelector("#lab-m-resolution"),
        invalid: root.querySelector("#lab-m-invalid"),
      };

      // ---- 页面状态 ----
      var timers = { frame: null, status: null };
      var paramDebounce = null;
      var pendingParams = {};
      var lastDisplayedAt = 0;
      var frameRequestSeq = 0;     // 只接受最新一次取帧结果，避免乱序覆盖
      var lastGoodUrl = "";        // 最近一次成功加载的帧（中断时保留它，不显示裂图）
      var everHadFrame = false;    // 区分"从未有过画面"与"有过但中断"
      var destroyed = false;
      var lastStatus = null;

      // ---- 小工具 ----
      function setMetric(key, value, unit) {
        var node = metricNodes[key];
        var tile = metricTiles[key];
        node.innerHTML = PVL.metricValue(value, unit, "未采集");
        var empty = (value === null || value === undefined || value === "");
        if (tile) tile.classList.toggle("metric-tile--empty", empty);
      }

      function showConnectError(code, message) {
        var info = PVL.describeError({ code: code, message: message });
        connectError.hidden = false;
        connectError.className = "banner banner-danger";
        connectError.innerHTML =
          '<div class="banner__content">' +
          '<span class="banner__title">没有连上</span>' +
          '<span class="banner__body">' + PVL.escapeHtml(info.message) + "</span>" +
          (info.hint
            ? '<span class="banner__body">' + PVL.escapeHtml(info.hint) + "</span>"
            : "") +
          "</div>";
      }

      function clearConnectError() {
        connectError.hidden = true;
        connectError.innerHTML = "";
      }

      function markSteps(state) {
        // state: idle | connected | error —— 三步说明随真实状态点亮。
        steps.wifi.classList.toggle("is-active", state === "idle");
        steps.wifi.classList.toggle("is-done", state !== "idle");
        steps.app.classList.toggle("is-active", state === "connected");
        steps.app.classList.toggle("is-done", state === "error");
        steps.ip.classList.toggle("is-active", state === "error");
        steps.ip.classList.toggle("is-done", state === "connected");
      }

      function setPill(kind, text, title) {
        statePill.classList.remove("pill-neutral", "pill-success", "pill-warning",
                                   "pill-danger", "pill-live");
        statePill.classList.add("pill-" + kind);
        statePillText.textContent = text;
        if (title) statePill.title = title;
      }

      // ---- 画面：空态分三种说清 ----
      function showEmpty(kind) {
        stage.classList.remove("is-stale");
        if (kind === "not_connected" || kind === "never_streamed") {
          // 从未有过画面：不摆一个空画布，直接给空状态与下一步。
          stage.hidden = true;
          frameImg.hidden = true;
          emptyBox.hidden = false;
          if (kind === "not_connected") {
            emptyTitle.textContent = "还没有画面";
            emptyDesc.textContent =
              "手机未连接：在左边填 IP 并点“连接”。连接成功后这里显示摄像头实时画面。";
          } else {
            emptyTitle.textContent = "已连接，但还没有收到画面";
            emptyDesc.textContent =
              "连接本身是通的（手机应答了 /ping），但还没有解析出任何一帧。" +
              "请确认手机 App 已经点了“开始推流”，且与电脑在同一局域网。";
          }
          return;
        }
        // 有过画面但中断 / 重连：保留最后一帧（标注中断），不假装还在播放。
        stage.hidden = false;
        emptyBox.hidden = false;
        if (everHadFrame) {
          frameImg.hidden = false;
          stage.classList.add("is-stale");
          emptyTitle.textContent = kind === "reconnecting" ? "正在重连" : "画面已中断";
          emptyDesc.textContent = kind === "reconnecting"
            ? "服务正在自动重连手机推流。重连成功前画面不会更新，上面是中断前的最后一帧。"
            : "已经很久没有收到新帧。请检查手机是否退出推流、Wi-Fi 是否切换，然后点“重新连接”。" +
              "上面是中断前的最后一帧（已降饱和），指标保留最后一次真实值，不会清零假装正常。";
        } else {
          frameImg.hidden = true;
          emptyTitle.textContent = kind === "reconnecting" ? "正在重连" : "画面中断";
          emptyDesc.textContent = kind === "reconnecting"
            ? "服务正在自动重连手机推流，重连成功后会自动开始显示画面。"
            : "画面已中断。请检查手机是否退出推流、Wi-Fi 是否切换，然后点“重新连接”。";
        }
      }

      function showStage() {
        stage.hidden = false;
        emptyBox.hidden = true;
        stage.classList.remove("is-stale");
        frameImg.hidden = false;
      }

      // ---- 指标 ----
      function renderMetrics(metrics, status) {
        var connected = !!(status && status.connected);
        if (!connected) {
          Object.keys(metricNodes).forEach(function (key) {
            setMetric(key, null, "");
          });
          tagRes.textContent = "分辨率 —";
          return;
        }
        var m = metrics || {};
        setMetric("phone", m.phone_capture_fps, "fps");
        setMetric("receive", m.pc_receive_fps, "fps");
        setMetric("display", m.pc_display_fps, "fps");
        setMetric("dropped", m.dropped_frames, "帧");
        setMetric("bandwidth", m.bandwidth_mbps, "Mbps");
        setMetric("invalid", m.invalid_frames, "帧");
        setMetric("resolution", m.resolution || null, "");
        tagRes.textContent = "分辨率 " + (m.resolution || "—");
      }

      // ---- 视觉模式 ----
      function renderModes(state) {
        var modes = state.modes || [];
        modeSegment.innerHTML = modes.map(function (mode) {
          var active = mode.id === state.mode;
          return '<button class="' + (active ? "is-active" : "") + '" type="button" ' +
            'data-mode="' + PVL.escapeHtml(mode.id) + '" ' +
            'aria-pressed="' + (active ? "true" : "false") + '">' +
            PVL.escapeHtml(mode.label) + "</button>";
        }).join("");
        modeSegment.classList.add("is-active");
        var label = state.mode_label || state.mode;
        modeBadge.textContent = label;
        modeBadge.className = "badge " + (state.mode === "original"
          ? "badge-neutral" : "badge-info");
        tagMode.textContent = label;
      }

      function renderParams(state) {
        var params = state.params || [];
        if (!params.length) {
          paramsBox.innerHTML =
            '<p class="field-hint">该模式没有可调参数，只做帧直通。' +
            "切换到“Canny 边缘 / HSV 颜色 / 轮廓”会出现阈值滑块。</p>";
          return;
        }
        paramsBox.innerHTML = params.map(function (param) {
          var key = PVL.escapeHtml(param.key);
          return '<div class="field" data-param="' + key + '">' +
            '<div class="slider-row">' +
              '<label class="field-label" for="lab-param-' + key + '">' +
                PVL.escapeHtml(param.label) + "</label>" +
              '<output class="field-value" id="lab-out-' + key + '" ' +
                'for="lab-param-' + key + '">' + PVL.escapeHtml(String(param.value)) +
              "</output>" +
              '<input class="slider" type="range" id="lab-param-' + key + '" min="' +
                PVL.escapeHtml(String(param.min)) + '" max="' +
                PVL.escapeHtml(String(param.max)) + '" step="1" value="' +
                PVL.escapeHtml(String(param.value)) + '">' +
            "</div>" +
          "</div>";
        }).join("");
      }

      function renderVisionState(state) {
        renderModes(state);
        renderParams(state);
        modeHint.querySelector("p").textContent = state.hint || "";
      }

      async function loadVisionState() {
        try {
          renderVisionState(await PVL.api("/api/vision/state"));
        } catch (error) {
          // 模式列表拉不到不影响看画面：保持现有按钮，说明真实原因。
          modeSegment.innerHTML =
            '<p class="field-hint">视觉模式列表加载失败：' +
            PVL.escapeHtml(PVL.describeError(error).message) + "</p>";
        }
      }

      async function selectMode(modeId) {
        var buttons = modeSegment.querySelectorAll("[data-mode]");
        buttons.forEach(function (button) {
          var active = button.getAttribute("data-mode") === modeId;
          button.classList.toggle("is-active", active);
          button.setAttribute("aria-pressed", active ? "true" : "false");
        });
        try {
          var state = await PVL.api("/api/vision/mode", {
            method: "POST", body: { mode: modeId },
          });
          renderVisionState(state);
          PVL.toast("已切换到" + (state.mode_label || modeId) + "模式", "success");
        } catch (error) {
          var info = PVL.describeError(error);
          PVL.toast("切换模式失败：" + info.message, "danger");
          loadVisionState();   // 回滚到后端真实状态，不留下假装成功的界面
        }
      }

      function queueParams(key, value) {
        pendingParams[key] = value;
        var output = root.querySelector("#lab-out-" + key);
        if (output) output.textContent = String(value);
        if (paramDebounce) clearTimeout(paramDebounce);
        paramDebounce = setTimeout(flushParams, PARAM_DEBOUNCE_MS);
      }

      async function flushParams() {
        if (destroyed) return;
        var body = pendingParams;
        pendingParams = {};
        var keys = Object.keys(body);
        if (!keys.length) return;
        try {
          var state = await PVL.api("/api/vision/params", {
            method: "POST", body: { params: body },
          });
          // 只回填数值，不重建滑块（重建会打断拖动）。
          (state.params || []).forEach(function (param) {
            var input = root.querySelector("#lab-param-" + param.key);
            if (input && document.activeElement !== input) {
              input.value = String(param.value);
            }
            var output = root.querySelector("#lab-out-" + param.key);
            if (output) output.textContent = String(param.value);
          });
        } catch (error) {
          PVL.toast("参数没有生效：" + PVL.describeError(error).message, "danger");
        }
      }

      // ---- 画面轮询 ----
      function refreshFrame() {
        if (destroyed || !lastStatus || !lastStatus.connected) return;
        var seq = ++frameRequestSeq;
        // 时间戳参数防缓存：同一 URL 浏览器不会重新请求。
        var url = "/api/vision/frame?quality=" + FRAME_QUALITY + "&t=" + Date.now();

        frameImg.onload = function () {
          if (destroyed || seq !== frameRequestSeq) return;   // 过期响应，丢弃
          lastGoodUrl = url;
          everHadFrame = true;
          showStage();
          notifyDisplayed();
        };
        frameImg.onerror = function () {
          if (destroyed || seq !== frameRequestSeq) return;
          // 取帧失败：回到最近一次成功加载的帧，交给状态轮询说明真实原因。
          // 绝不把 <img> 留在坏 src 上（那会显示裂图）。
          if (lastGoodUrl && frameImg.getAttribute("src") !== lastGoodUrl) {
            frameImg.src = lastGoodUrl;
          } else if (!lastGoodUrl) {
            frameImg.removeAttribute("src");
          }
          frameImg.hidden = !lastGoodUrl;
        };
        frameImg.src = url;
      }

      function notifyDisplayed() {
        var now = Date.now();
        if (now - lastDisplayedAt < DISPLAYED_THROTTLE_MS) return;
        lastDisplayedAt = now;
        // 节流到每秒 1 次；失败只影响显示帧率统计，不影响画面。
        PVL.api("/api/vision/displayed", { method: "POST", body: {} })
          .catch(function () { /* 显示帧率统计失败不影响画面 */ });
      }

      // ---- 连接状态轮询 ----
      async function pollStatus() {
        if (destroyed) return;
        var status;
        try {
          status = await PVL.api("/api/device/status");
        } catch (error) {
          // 本地服务本身不可达：不假装连接，也不假装断开，直接说明。
          if (!destroyed) showConnectError("network_error", "无法读取设备状态");
          return;
        }
        if (destroyed) return;
        lastStatus = status;
        renderStatus(status);
        try {
          renderMetrics(await PVL.api("/api/vision/metrics"), status);
        } catch (error) {
          renderMetrics(null, status);
        }
      }

      function renderStatus(status) {
        var connected = !!status.connected;
        connectBtn.textContent = connected ? "重新连接" : "连接";
        disconnectBtn.disabled = !connected;
        reconnectBtn.disabled = !connected;

        if (!connected) {
          setPill("neutral", "未连接", "填写手机 IP 后点“连接”");
          markSteps("idle");
          showEmpty("not_connected");
          tagState.textContent = "未连接";
          snapshotBtn.disabled = true;
          snapshotReason.textContent = "未连接手机：没有画面可截图。";
          return;
        }

        if (status.state === "Streaming") {
          setPill("live", "已连接 · " + (status.device || "手机"), "手机正在推流");
          markSteps("connected");
          tagState.textContent = status.frame_stale ? "画面已中断" : "推流中";
          if (status.frame_stale) {
            showEmpty("interrupted");
          } else if (!everHadFrame) {
            showEmpty("never_streamed");
          } else {
            showStage();
          }
          snapshotBtn.disabled = status.frame_stale;
          snapshotReason.textContent = status.frame_stale
            ? "当前没有新画面：请确认手机仍在推流，再截图。"
            : "截图保存的是原始画面（不叠加当前视觉模式）。";
          return;
        }
        if (status.state === "Reconnecting") {
          setPill("warning", "重连中 · " + (status.host || ""), "服务正在自动重连");
          markSteps("error");
          tagState.textContent = "重连中";
          showEmpty("reconnecting");
          snapshotBtn.disabled = true;
          snapshotReason.textContent = "正在重连：重连成功前不能保证取到画面。";
          return;
        }
        if (status.state === "Error") {
          setPill("danger", "连接错误", "连接出错，请重新连接");
          markSteps("error");
          tagState.textContent = "连接错误";
          showEmpty("interrupted");
          snapshotBtn.disabled = true;
          snapshotReason.textContent =
            "连接出错：" + (status.last_error || "请重新连接") + "。";
          return;
        }
        // Connecting / Stopped 等中间态
        setPill("warning", status.state_label || status.state, "连接中");
        markSteps("error");
        tagState.textContent = status.state_label || status.state;
        showEmpty("reconnecting");
        snapshotBtn.disabled = true;
        snapshotReason.textContent = "连接尚未就绪：请等待状态变为“已连接 · 正在推流”。";
      }

      // ---- 事件 ----
      connectBtn.addEventListener("click", async function () {
        var host = hostInput.value.trim();
        var port = parseInt(portInput.value.trim() || "8080", 10);
        if (!host) {
          showConnectError("bad_request", "请填写手机 IP 地址");
          hostInput.focus();
          return;
        }
        if (!(port >= 1 && port <= 65535)) {
          showConnectError("bad_request", "端口必须在 1-65535 之间");
          portInput.focus();
          return;
        }
        clearConnectError();
        connectBtn.disabled = true;
        connectBtn.textContent = "连接中…";
        setPill("warning", "连接中", "正在请求手机 /ping");
        try {
          var status = await PVL.api("/api/device/connect", {
            method: "POST", body: { host: host, port: port },
          });
          PVL.store.lastPhoneAddress = host + ":" + port;
          PVL.saveStore();
          PVL.toast("已连接 " + host + ":" + port, "success");
          PVL.refreshGlobalStatus();
          lastStatus = status;
          renderStatus(status);
          loadVisionState();
        } catch (error) {
          var info = PVL.describeError(error);
          showConnectError(info.code, info.message);
          setPill("neutral", "未连接", "填写手机 IP 后点“连接”");
          markSteps("idle");
          showEmpty("not_connected");
          PVL.toast("连接失败：" + info.message, "danger");
        } finally {
          if (!destroyed) {
            connectBtn.disabled = false;
            connectBtn.textContent = "连接";
          }
        }
      });

      disconnectBtn.addEventListener("click", async function () {
        try {
          await PVL.api("/api/device/disconnect", { method: "POST", body: {} });
          PVL.toast("已断开手机", "info");
          PVL.refreshGlobalStatus();
          lastStatus = { connected: false, state: "disconnected", state_label: "未连接" };
          renderStatus(lastStatus);
        } catch (error) {
          PVL.toast("断开失败：" + PVL.describeError(error).message, "danger");
        }
      });

      reconnectBtn.addEventListener("click", async function () {
        reconnectBtn.disabled = true;
        try {
          var status = await PVL.api("/api/device/reconnect", { method: "POST", body: {} });
          PVL.toast("已请求重新连接", "info");
          lastStatus = status;
          renderStatus(status);
        } catch (error) {
          PVL.toast("重新连接失败：" + PVL.describeError(error).message, "danger");
          reconnectBtn.disabled = !(lastStatus && lastStatus.connected);
        }
      });

      modeSegment.addEventListener("click", function (event) {
        var button = event.target.closest("[data-mode]");
        if (!button) return;
        selectMode(button.getAttribute("data-mode"));
      });

      paramsBox.addEventListener("input", function (event) {
        var input = event.target;
        if (!input || input.type !== "range") return;
        var field = input.closest("[data-param]");
        if (!field) return;
        queueParams(field.getAttribute("data-param"), parseInt(input.value, 10));
      });

      snapshotBtn.addEventListener("click", function () {
        // 截图走独立高质量接口（原始画面，不叠加当前模式）。
        var link = document.createElement("a");
        link.href = "/api/vision/snapshot?t=" + Date.now();
        link.download = "phonevision-snapshot-" +
          new Date().toISOString().replace(/[:.]/g, "-") + ".jpg";
        document.body.appendChild(link);
        link.click();
        link.remove();
        PVL.toast("已请求保存截图（原始画面，未叠加视觉模式）", "success");
      });

      // ---- 数据集就绪提示（"去采集数据"的前置说明） ----
      async function checkDatasetReady() {
        try {
          var current = await PVL.api("/api/datasets/current");
          var count = (current.classes || []).length;
          gotoReason.textContent = count
            ? "将进入数据集 " + current.name + "（" + count + " 个类别），可以直接开始采集。"
            : "数据集 " + current.name + " 还没有类别：进入后先添加至少 2 个类别。";
        } catch (error) {
          var info = PVL.describeError(error);
          gotoReason.textContent = info.code === "no_dataset"
            ? "当前还没有打开数据集：进入数据集工作区后需要先创建一个（至少 2 个类别）。"
            : "读取数据集状态失败：" + info.message;
        }
      }

      // ---- 启动 ----
      if (PVL.store && PVL.store.lastPhoneAddress) {
        var parts = String(PVL.store.lastPhoneAddress).split(":");
        if (parts[0]) hostInput.value = parts[0];
        if (parts[1]) portInput.value = parts[1];
      }
      markSteps("idle");
      showEmpty("not_connected");
      renderMetrics(null, null);
      loadVisionState();
      checkDatasetReady();
      pollStatus();
      timers.status = setInterval(pollStatus, STATUS_INTERVAL_MS);
      timers.frame = setInterval(refreshFrame, FRAME_INTERVAL_MS);

      // ---- 清理：路由离开时停掉所有轮询与防抖 ----
      return function cleanup() {
        destroyed = true;
        if (timers.frame) { clearInterval(timers.frame); timers.frame = null; }
        if (timers.status) { clearInterval(timers.status); timers.status = null; }
        if (paramDebounce) { clearTimeout(paramDebounce); paramDebounce = null; }
        frameImg.onload = null;
        frameImg.onerror = null;
        frameImg.removeAttribute("src");
      };
    },
  };

  window.PVL_PAGES = window.PVL_PAGES || {};
  window.PVL_PAGES.lab = page;
})();
