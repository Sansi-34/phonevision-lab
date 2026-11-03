/**
 * PhoneVision Lab Web — 硬件联动页。
 *
 * 目标：把"命令四态"做成可核对的时序，而不是一个成功/失败开关。
 *   先手动验证（LED 开 / 关 / 亮度），再看事件记录，最后理解自动控制为什么在手机端。
 *
 * 数据来源（全部来自后端真实回执）：
 *   GET  /api/hardware/status   连接状态 / LED 状态 / 最近验证时间 / 可用动作
 *   POST /api/hardware/connect  连接（真实控制器或模拟设备）
 *   POST /api/hardware/disconnect
 *   POST /api/hardware/send     发送命令 → 返回 {event:{time,action,status,rtt_ms,message,simulated}}
 *   GET  /api/hardware/events   事件记录（每 2 秒轮询）
 *
 * 诚实边界（这一页最容易造假，逐条写死）：
 *   - 命令四态严格按回执分级：已发送(info) / 已接收(primary) / 已执行(success) / 失败(danger)；
 *     没有 received 回执时绝不显示"已执行"。
 *   - LED 固件只回 received，不确认灯是否真的发光：此时 LED 状态区显示
 *     "设备未确认执行，请目视确认"，绝不显示"LED 已点亮"。
 *   - 只有 led_state_known && led_on 才显示"已点亮"；否则"状态未知/已熄灭"。
 *   - 自动控制不放假开关：规则在手机端执行，电脑端没有分类结果来源。
 *   - 未连接时所有控制按钮禁用，并同时写明原因。
 */
window.PVL_PAGES = window.PVL_PAGES || {};

window.PVL_PAGES.hardware = {
  render: async function (root) {
    const POLL_MS = 2000;
    const MIN_SEND_MS = 400;          // "发送中"最短停留时间，避免闪烁
    const DEFAULT_PORT = 8081;

    // 命令四态 → 徽标类名（文字 + 色块同时出现，绝不只放色点）
    const STATUS_BADGE = {
      sent: "badge-info",
      received: "badge-primary",
      executed: "badge-success",
      failed: "badge-danger",
    };
    const STATUS_LABELS = {
      sent: "已发送",
      received: "已接收",
      executed: "已执行",
      failed: "失败",
      info: "信息",
      warning: "注意",
      error: "错误",
    };

    let disposed = false;
    let status = null;
    let events = [];
    let simulatedBanner = null;
    let renderedEventCount = 0;
    let timer = null;
    const sending = {};               // action → true 时按钮显示"发送中"

    // ------------------------------------------------------------------
    // 小工具
    // ------------------------------------------------------------------

    function statusBadge(statusValue) {
      const cls = STATUS_BADGE[statusValue] || "badge-neutral";
      const label = STATUS_LABELS[statusValue] || statusValue || "未知";
      return '<span class="badge ' + cls + '">' + PVL.escapeHtml(label) + "</span>";
    }

    function formatRtt(value) {
      if (value === null || value === undefined) return "—";
      return PVL.escapeHtml(String(value)) + '<span class="metric-unit"> ms</span>';
    }

    // ------------------------------------------------------------------
    // 页面骨架
    // ------------------------------------------------------------------

    root.appendChild(PVL.el(
      '<section class="page-head">' +
        "<h1>硬件联动</h1>" +
        '<p class="page-lede">' +
          "用电脑端手动发送命令，验证 ESP32 控制器与 LED 的链路是否通。" +
          "命令有四种状态，界面只显示控制器真实回执的那一档。" +
        "</p>" +
      "</section>"
    ));

    // 顶部常驻警告：真机链路未完成端到端验证
    root.appendChild(PVL.el(
      '<div class="banner banner-warning" id="hw-warning">' +
        "<strong>ESP32 / LED 真机链路尚未完成端到端验证</strong>" +
        "<p>控制协议与固件已经实现，网页端可以连接控制器并发送命令、查看四态回执，" +
        "但“网页发命令 → 控制器执行 → LED 物理点亮”这条完整链路还没有在真实硬件上全面验收。</p>" +
        "<p>本页不代替真机验收：请按事件记录里的真实状态判断，不要假设命令一定生效。</p>" +
      "</div>"
    ));

    // 模拟设备警示（勾选模拟时插入到警告横幅之后）
    simulatedBanner = PVL.el(
      '<div class="banner banner-danger" id="hw-simulated-banner" hidden>' +
        "<strong>模拟设备 · 不会驱动真实硬件</strong>" +
        "<p>当前连接的是软件模拟设备，只验证命令链路与界面逻辑，LED 不会亮，也不代表真机可用。</p>" +
        '<div class="banner-actions">' +
        '<button class="btn btn-secondary btn-sm" type="button" id="hw-back-to-real">切回真实设备</button>' +
        "</div>" +
      "</div>"
    );
    root.appendChild(simulatedBanner);

    // ---- 连接卡片 ----
    const connectCard = PVL.el(
      '<section class="card">' +
        '<div class="card-header">' +
          '<h2 class="card-title">控制器连接</h2>' +
          '<span id="hw-conn-badge"></span>' +
        "</div>" +
        '<div class="card-body">' +
          '<div class="field-grid">' +
            '<div class="field">' +
              '<label class="field-label" for="hw-host">控制器地址（ESP32 的 IP）</label>' +
              '<input class="field-input" id="hw-host" type="text" placeholder="例如 192.168.1.50" ' +
                'autocomplete="off" spellcheck="false">' +
              '<p class="field-hint">ESP32 需要先烧录固件，并与电脑连同一个 Wi-Fi。</p>' +
            "</div>" +
            '<div class="field">' +
              '<label class="field-label" for="hw-port">端口</label>' +
              '<input class="field-input" id="hw-port" type="number" min="1" max="65535" step="1" value="8081">' +
              '<p class="field-hint">默认 8081。</p>' +
            "</div>" +
          "</div>" +
          '<div class="field">' +
            '<label class="field-check">' +
              '<input type="checkbox" id="hw-simulated">' +
              "<span>使用模拟设备演练（不驱动真实硬件）</span>" +
            '</label>' +
            '<p class="field-hint">勾选后只走软件链路：可以练习命令四态与事件记录，但 LED 不会亮。</p>' +
          '</div>' +
          '<div class="banner-actions">' +
            '<button class="btn btn-primary" type="button" id="hw-connect">连接</button>' +
            '<button class="btn btn-secondary" type="button" id="hw-disconnect" disabled>断开</button>' +
            '<span class="field-hint" id="hw-conn-reason"></span>' +
          "</div>" +
        '</div>' +
      "</section>"
    );
    root.appendChild(connectCard);

    // ---- LED 当前状态 ----
    const ledCard = PVL.el(
      '<section class="card">' +
        '<div class="card-header">' +
          '<h2 class="card-title">LED 当前状态</h2>' +
          '<span id="hw-led-badge"></span>' +
        "</div>" +
        '<div class="card-body">' +
          '<p id="hw-led-text" class="kv-text">正在读取状态…</p>' +
          '<ul class="kv-list">' +
            "<li><span>最近一次手动验证</span><span id=\"hw-verified\">—</span></li>" +
            "<li><span>控制目标</span><span id=\"hw-target\">—</span></li>" +
          '</ul>' +
        '</div>' +
      '</section>'
    );
    root.appendChild(ledCard);

    // ---- 手动控制 ----
    const controlCard = PVL.el(
      '<section class="card">' +
        '<div class="card-header"><h2 class="card-title">手动控制</h2></div>' +
        '<div class="card-body">' +
          '<div class="banner-actions">' +
            '<button class="btn btn-primary" type="button" id="hw-led-on">LED 开</button>' +
            '<button class="btn btn-secondary" type="button" id="hw-led-off">LED 关</button>' +
            '<button class="btn btn-secondary" type="button" id="hw-stop">停止</button>' +
            '<span class="field-hint" id="hw-control-reason"></span>' +
          "</div>" +
          '<div class="field">' +
            '<label class="field-label" for="hw-brightness">亮度（0–255）</label>' +
            '<div class="slider-row">' +
              '<input class="slider" id="hw-brightness" type="range" min="0" max="255" step="1" value="128">' +
              '<output class="mono" id="hw-brightness-value" for="hw-brightness">128</output>' +
            "</div>" +
            '<p class="field-hint">0 = 熄灭，255 = 最亮。发送后按回执更新状态。</p>' +
          '</div>' +
          '<div class="banner-actions">' +
            '<button class="btn btn-secondary" type="button" id="hw-set-led">发送亮度</button>' +
            '<span class="field-hint" id="hw-brightness-reason"></span>' +
          '</div>' +
        '</div>' +
      '</section>'
    );
    root.appendChild(controlCard);

    // ---- 自动联动说明卡（不放假开关） ----
    root.appendChild(PVL.el(
      '<section class="card">' +
        '<div class="card-header">' +
          '<h2 class="card-title">自动联动（手机端执行）</h2>' +
          '<span class="badge badge-warning">网页端不提供开关</span>' +
        "</div>" +
        '<div class="card-body">' +
          '<div class="banner banner-info">' +
            "<strong>为什么这里没有自动控制开关</strong>" +
            "<p>自动联动需要“分类结果”作为输入，而分类在手机端本机完成；" +
            "电脑端没有分类结果来源，因此网页端做一个开关也永远不会动作。</p>" +
            "<p>自动控制规则在手机 App 中执行。按下面四步在手机上开启。</p>" +
          '</div>' +
          '<ol class="step-list">' +
            '<li class="step-item"><span class="step-num">1</span>' +
              "<span>确认手机与 ESP32 控制器在<strong>同一个 Wi-Fi</strong> 下。</span></li>" +
            '<li class="step-item"><span class="step-num">2</span>' +
              "<span>在手机推理界面填写<strong>控制器 IP 与端口（默认 8081）</strong>并连接。" +
              "连接成功会显示一次只读状态查询的回执。</span></li>" +
            '<li class="step-item"><span class="step-num">3</span>' +
              "<span><strong>先手动验证</strong>：在手机上手动发一次 LED 开 / LED 关，" +
              "目视确认灯真的亮灭，再谈自动。</span></li>" +
            '<li class="step-item"><span class="step-num">4</span>' +
              "<span>确认无误后，再在手机上<strong>开启自动控制</strong>；" +
              "规则含连续确认、滞回与冷却，避免灯光抖动。</span></li>" +
          '</ol>' +
        '</div>' +
      '</section>'
    ));

    // ---- 四态图例 ----
    root.appendChild(PVL.el(
      '<section class="card">' +
        '<div class="card-header"><h2 class="card-title">命令状态图例</h2></div>' +
        '<div class="card-body">' +
          '<ul class="kv-list">' +
            "<li><span>" + statusBadge("sent") + "</span>" +
            "<span>命令已从电脑发出，还没有收到控制器回应。</span></li>" +
            "<li><span>" + statusBadge("received") + "</span>" +
            "<span>控制器确认收到了命令。<strong>不代表动作已完成</strong>；" +
            "LED 固件只回到这一档。</span></li>" +
            "<li><span>" + statusBadge("executed") + "</span>" +
            "<span>控制器确认已执行（仅当设备真能确认动作完成时才可能出现）。</span></li>" +
            "<li><span>" + statusBadge("failed") + "</span>" +
            "<span>超时、失败或连接中断。命令不会被缓存重放。</span></li>" +
          '</ul>' +
          '<p class="field-hint">LED 没有传感器确认是否真的发光，因此“已执行”这一档在 LED 命令里不会出现；' +
          '最多显示“已接收”，并请目视确认。</p>' +
        '</div>' +
      '</section>'
    ));

    // ---- 事件记录 ----
    const eventsCard = PVL.el(
      '<section class="card">' +
        '<div class="card-header">' +
          '<h2 class="card-title">命令事件记录</h2>' +
          '<span class="field-hint" id="hw-events-count"></span>' +
        "</div>" +
        '<div class="card-body">' +
          '<div class="table-scroll"><table class="table">' +
            "<thead><tr><th>时间</th><th>动作</th><th>状态</th><th>往返耗时</th><th>说明</th></tr></thead>" +
            '<tbody id="hw-events-body"></tbody>' +
          "</table></div>" +
          '<p class="field-hint">事件记录只反映后端收到的真实回执；模拟设备的事件带“模拟”标记。</p>' +
        "</div>" +
      "</section>"
    );
    root.appendChild(eventsCard);

    const connBadge = connectCard.querySelector("#hw-conn-badge");
    const hostInput = connectCard.querySelector("#hw-host");
    const portInput = connectCard.querySelector("#hw-port");
    const simulatedInput = connectCard.querySelector("#hw-simulated");
    const connectBtn = connectCard.querySelector("#hw-connect");
    const disconnectBtn = connectCard.querySelector("#hw-disconnect");
    const connReason = connectCard.querySelector("#hw-conn-reason");
    const ledBadge = ledCard.querySelector("#hw-led-badge");
    const ledText = ledCard.querySelector("#hw-led-text");
    const verifiedEl = ledCard.querySelector("#hw-verified");
    const targetEl = ledCard.querySelector("#hw-target");
    const ledOnBtn = controlCard.querySelector("#hw-led-on");
    const ledOffBtn = controlCard.querySelector("#hw-led-off");
    const stopBtn = controlCard.querySelector("#hw-stop");
    const controlReason = controlCard.querySelector("#hw-control-reason");
    const brightnessSlider = controlCard.querySelector("#hw-brightness");
    const brightnessValue = controlCard.querySelector("#hw-brightness-value");
    const setLedBtn = controlCard.querySelector("#hw-set-led");
    const brightnessReason = controlCard.querySelector("#hw-brightness-reason");
    const eventsBody = eventsCard.querySelector("#hw-events-body");
    const eventsCount = eventsCard.querySelector("#hw-events-count");
    const backToRealBtn = simulatedBanner.querySelector("#hw-back-to-real");

    // ------------------------------------------------------------------
    // 渲染
    // ------------------------------------------------------------------

    function renderConnection() {
      const connected = Boolean(status && status.connected);
      const simulated = Boolean(status && status.simulated);
      connBadge.innerHTML = connected
        ? (simulated
            ? '<span class="badge badge-warning">已连接 · 模拟设备</span>'
            : '<span class="badge badge-success">已连接</span>')
        : '<span class="badge badge-neutral">未连接</span>';

      simulatedBanner.hidden = !simulated;
      connectBtn.disabled = connected;
      disconnectBtn.disabled = !connected;
      simulatedInput.disabled = connected;

      if (connected) {
        const address = simulated
          ? "模拟设备（软件链路）"
          : (status.host + ":" + status.port);
        connReason.textContent = "已连接到 " + address + "。断开后才能修改地址或切换设备类型。";
      } else {
        connReason.textContent =
          "未连接：手动控制全部不可用。填写 ESP32 地址后点“连接”，" +
          "或勾选“使用模拟设备演练”先熟悉命令四态。";
      }

      if (!hostInput.value) {
        const remembered = PVL.store.lastControllerAddress || "";
        if (remembered) hostInput.value = remembered;
      }
    }

    function renderLed() {
      const known = Boolean(status && status.led_state_known);
      const on = Boolean(status && status.led_on);

      if (!status || !status.connected) {
        ledBadge.innerHTML = '<span class="badge badge-neutral">未连接</span>';
        ledText.textContent = "尚未连接控制器，无法读取 LED 状态。";
      } else if (known && on) {
        ledBadge.innerHTML = '<span class="badge badge-success">已点亮</span>';
        ledText.textContent = "LED 已点亮（控制器已确认执行）。";
      } else if (known && !on) {
        ledBadge.innerHTML = '<span class="badge badge-neutral">已熄灭</span>';
        ledText.textContent = "LED 已熄灭（控制器已确认执行）。";
      } else {
        ledBadge.innerHTML = '<span class="badge badge-warning">状态未知</span>';
        ledText.textContent =
          "状态未知：控制器只确认收到命令，没有确认执行。" +
          "LED 是否真的亮灭请目视确认。";
      }

      verifiedEl.innerHTML = status && status.verified_at
        ? PVL.escapeHtml(status.verified_at)
        : '<span class="badge badge-neutral">未验证</span>';
      targetEl.textContent = (status && status.target) || "—";
    }

    function renderControls() {
      const connected = Boolean(status && status.connected);
      const buttons = [
        { el: ledOnBtn, action: "led_on", idle: "LED 开" },
        { el: ledOffBtn, action: "led_off", idle: "LED 关" },
        { el: stopBtn, action: "stop", idle: "停止" },
        { el: setLedBtn, action: "set_led", idle: "发送亮度" },
      ];
      buttons.forEach(function (item) {
        item.el.disabled = !connected || Boolean(sending[item.action]);
        item.el.textContent = sending[item.action] ? "发送中…" : item.idle;
      });
      brightnessSlider.disabled = !connected;

      controlReason.textContent = connected
        ? "点击后按钮进入“发送中”，随后按控制器回执更新状态。"
        : "控制器未连接：先确认 ESP32 已烧录固件、与电脑在同一 Wi-Fi、端口 8081，" +
          "或勾选“使用模拟设备演练”。";
      brightnessReason.textContent = connected
        ? ""
        : "未连接时不能发送亮度命令（原因同上）。";
    }

    function renderEvents() {
      eventsCount.textContent = events.length
        ? ("显示最近 " + events.length + " 条")
        : "";
      if (!events.length) {
        eventsBody.innerHTML =
          '<tr><td colspan="5" class="table-empty">还没有事件记录。</td></tr>';
        renderedEventCount = 0;
        return;
      }
      // 事件为“最新在前”（后端 events() 已反序）：整表重绘，保证状态升级即时可见
      const rows = events.map(function (event) {
        const simulatedTag = event.simulated
          ? ' <span class="badge badge-neutral">模拟</span>'
          : "";
        // info/warning/error 是连接类系统事件，没有 action 字段，用 action_label 展示
        const label = event.action_label || STATUS_LABELS[event.status] || event.action || "—";
        return (
          "<tr>" +
          "<td>" + PVL.escapeHtml(event.time || "—") + "</td>" +
          "<td>" + PVL.escapeHtml(label) + simulatedTag + "</td>" +
          "<td>" + statusBadge(event.status) + "</td>" +
          "<td>" + formatRtt(event.rtt_ms) + "</td>" +
          "<td>" + PVL.escapeHtml(event.message || "—") + "</td>" +
          "</tr>"
        );
      }).join("");
      eventsBody.innerHTML = rows;
      renderedEventCount = events.length;
    }

    // ------------------------------------------------------------------
    // 数据加载
    // ------------------------------------------------------------------

    async function refreshStatus() {
      if (disposed) return;
      try {
        status = await PVL.api("/api/hardware/status");
      } catch (error) {
        if (disposed) return;
        const info = PVL.describeError(error);
        connReason.textContent = "无法读取硬件状态：" + info.message;
        return;
      }
      if (disposed) return;
      renderConnection();
      renderLed();
      renderControls();
    }

    async function refreshEvents() {
      if (disposed) return;
      try {
        const data = await PVL.api("/api/hardware/events");
        events = (data && data.events) || [];
      } catch (error) {
        return; // 轮询失败保留上一次记录，不制造空表
      }
      if (disposed) return;
      renderEvents();
    }

    // ------------------------------------------------------------------
    // 命令发送：四态只看真实回执
    // ------------------------------------------------------------------

    async function sendCommand(action, params) {
      const started = Date.now();
      sending[action] = true;
      renderControls();
      let event = null;
      let failure = "";
      try {
        const data = await PVL.api("/api/hardware/send", {
          method: "POST",
          body: { action: action, params: params || {} },
        });
        event = (data && data.event) || null;
      } catch (error) {
        const info = PVL.describeError(error);
        failure = info.message;
      }
      // "发送中"最短停留 400ms，避免快请求造成按钮闪烁
      const waited = Date.now() - started;
      if (waited < MIN_SEND_MS) {
        await new Promise(function (resolve) { setTimeout(resolve, MIN_SEND_MS - waited); });
      }
      sending[action] = false;
      if (disposed) return;
      renderControls();

      if (failure) {
        PVL.toast("命令失败：" + failure, "danger");
      } else if (event) {
        // 只按回执原样播报，不越级声称执行成功
        if (event.status === "executed") {
          PVL.toast("控制器回执：已执行", "success");
        } else if (event.status === "received") {
          PVL.toast("控制器回执：已接收（未确认执行，请目视确认）", "warning");
        } else if (event.status === "sent") {
          PVL.toast("控制器回执：已发送，等待控制器回应", "info");
        } else {
          PVL.toast("控制器回执：失败", "danger");
        }
      } else {
        PVL.toast("服务端没有返回命令回执", "warning");
      }
      await refreshStatus();
      await refreshEvents();
    }

    // ------------------------------------------------------------------
    // 事件绑定
    // ------------------------------------------------------------------

    brightnessSlider.addEventListener("input", function () {
      brightnessValue.textContent = brightnessSlider.value;
    });

    ledOnBtn.addEventListener("click", function () { sendCommand("led_on", {}); });
    ledOffBtn.addEventListener("click", function () { sendCommand("led_off", {}); });
    stopBtn.addEventListener("click", function () { sendCommand("stop", {}); });
    setLedBtn.addEventListener("click", function () {
      sendCommand("set_led", { brightness: parseInt(brightnessSlider.value, 10) });
    });

    connectBtn.addEventListener("click", async function () {
      const host = hostInput.value.trim();
      const port = parseInt(portInput.value, 10) || DEFAULT_PORT;
      const simulated = simulatedInput.checked;

      if (!simulated && !host) {
        PVL.toast("请先填写控制器 IP 地址", "warning");
        return;
      }
      if (!(port >= 1 && port <= 65535)) {
        PVL.toast("端口需要在 1–65535 之间", "warning");
        return;
      }

      connectBtn.disabled = true;
      connectBtn.textContent = "连接中…";
      try {
        status = await PVL.api("/api/hardware/connect", {
          method: "POST",
          body: { host: host, port: port, simulated: simulated },
        });
        if (host) {
          PVL.store.lastControllerAddress = host;
          PVL.saveStore();
        }
        PVL.toast(simulated ? "已连接模拟设备" : "已连接控制器", "success");
        await refreshStatus();
        await refreshEvents();
      } catch (error) {
        const info = PVL.describeError(error);
        PVL.toast("连接失败：" + info.message, "danger");
        connReason.textContent = "连接失败：" + info.message +
          (info.hint ? "（" + info.hint + "）" : "");
        await refreshStatus();
      } finally {
        connectBtn.disabled = false;
        connectBtn.textContent = "连接";
      }
    });

    disconnectBtn.addEventListener("click", async function () {
      disconnectBtn.disabled = true;
      disconnectBtn.textContent = "断开中…";
      try {
        status = await PVL.api("/api/hardware/disconnect", { method: "POST" });
        PVL.toast("已断开控制器连接", "info");
        await refreshStatus();
        await refreshEvents();
      } catch (error) {
        const info = PVL.describeError(error);
        PVL.toast("断开失败：" + info.message, "danger");
      } finally {
        disconnectBtn.textContent = "断开";
      }
    });

    backToRealBtn.addEventListener("click", async function () {
      try {
        status = await PVL.api("/api/hardware/disconnect", { method: "POST" });
      } catch (error) {
        // 断开失败也要让用户能改回真实设备：只提示，不阻断
        PVL.toast("断开模拟设备失败，你仍可改为真实设备后重新连接", "warning");
      }
      simulatedInput.checked = false;
      await refreshStatus();
      await refreshEvents();
    });

    // ------------------------------------------------------------------
    // 启动
    // ------------------------------------------------------------------

    renderConnection();
    renderLed();
    renderControls();
    renderEvents();

    await refreshStatus();
    await refreshEvents();

    timer = setInterval(function () {
      refreshStatus();
      refreshEvents();
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
