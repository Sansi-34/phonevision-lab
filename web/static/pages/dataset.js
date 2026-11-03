/**
 * PhoneVision Lab Web — 数据集工作区。
 *
 * 职责：
 *   - 数据集列表 / 新建 / 打开（目录与 dataset.json 复用 pvl_dataset，不另建存储）；
 *   - 类别管理（添加 / 重命名 / 删除，删除前二次确认）；
 *   - 样本缩略图网格（按类别筛选、显示批次号、单张删除前二次确认）；
 *   - 采集面板（采集一张 / 连续采集，未连接手机时禁用并说明原因）；
 *   - 数据体检（problems 红 / warnings 黄，逐条列出）；
 *   - 按批次划分训练/验证集，显示 train/val 数量、按类别分布与 split.json 状态。
 *
 * 诚实边界（本页最容易造假的地方）：
 *   - 采集帧来自 DeviceSession 真实手机流；未连接时按钮禁用并写清原因，
 *     不进入假采集态，也不写空图或示例图；
 *   - 连续采集出错立即停止并 toast 真实原因，绝不在失败后继续计数；
 *   - 数据不足的结论直接引用 pvl_split 的 problems/warnings，不自己编阈值；
 *   - 划分结果显示真实 seed 与比例；划分文件不存在就说"未划分"，
 *     不用上一次的结果冒充新划分。
 *
 * 样式约定（web/static/styles.css，不新增任何类）：
 *   外层 .app-split--left（数据集列表 300px | 主区），主区内再套 .app-split--narrow
 *   （类别+样本 | 采集/体检/划分 300px）；<1100px 自动变单列。
 *   缩略图用 .thumb-grid--4 + .thumb-item（角标放删除按钮，底部说明放类别与批次号）；
 *   体检逐条用 .table--stack（td 带 data-label，<640 自动转卡片列表）。
 */
(function () {
  "use strict";

  // 连续采集默认间隔 500ms（与桌面客户端一致；可调，最小 100ms）。
  var CAPTURE_INTERVAL_DEFAULT = 500;
  var CAPTURE_INTERVAL_MIN = 100;
  var CAPTURE_INTERVAL_MAX = 5000;
  // 当前数据集状态轮询：连续采集时用来刷新计数与批次数。
  var CURRENT_POLL_MS = 1000;
  // 设备状态轮询：用来决定采集按钮是否可用。
  var DEVICE_POLL_MS = 3000;
  // 缩略图一次渲染上限：一次渲染太多 <img> 会把本地服务打满。
  var SAMPLE_LIMIT = 120;

  var page = {
    render: function (root) {
      root.innerHTML =
        '<header class="app-header">' +
          '<div class="app-header__titles">' +
            '<span class="app-header__eyebrow">实验台 · 工位 ②</span>' +
            '<h1 class="app-header__title">数据集工作区</h1>' +
            '<p class="app-header__desc">建集 → 采集 → 体检 → 划分。' +
              "每一步都会说清还差什么，不会用示例数据充数。</p>" +
          "</div>" +
          '<div class="app-header__status">' +
            '<span class="pill pill-neutral" id="ds-device-pill">' +
              '<span class="pill-dot" aria-hidden="true"></span>' +
              '<span id="ds-device-pill-text">正在检测手机连接…</span>' +
            "</span>" +
          "</div>" +
        "</header>" +

        '<div class="banner banner-info">' +
          '<div class="banner__content">' +
            '<span class="banner__title">采集需要手机在线</span>' +
            '<span class="banner__body">样本来自实验台正在接收的摄像头画面。' +
            "没有连接手机时采集按钮会保持禁用并说明原因，不会写入空图或示例图。</span>" +
          "</div>" +
        "</div>" +

        '<ol class="step-list step-list--horizontal" id="ds-steps">' +
          '<li class="step-item" id="ds-step-create">' +
            '<span class="step-item__index" aria-hidden="true">1</span>' +
            '<span class="step-item__content">' +
              '<span class="step-item__title">建集</span>' +
              '<span class="step-item__desc">创建数据集与至少 2 个类别</span>' +
            "</span>" +
            '<span class="step-item__meta"><span class="badge badge-neutral" ' +
              'id="ds-step-create-badge">未开始</span></span>' +
          "</li>" +
          '<li class="step-item" id="ds-step-capture">' +
            '<span class="step-item__index" aria-hidden="true">2</span>' +
            '<span class="step-item__content">' +
              '<span class="step-item__title">采集</span>' +
              '<span class="step-item__desc">每类至少 2 个批次</span>' +
            "</span>" +
            '<span class="step-item__meta"><span class="badge badge-neutral" ' +
              'id="ds-step-capture-badge">未开始</span></span>' +
          "</li>" +
          '<li class="step-item" id="ds-step-check">' +
            '<span class="step-item__index" aria-hidden="true">3</span>' +
            '<span class="step-item__content">' +
              '<span class="step-item__title">体检</span>' +
              '<span class="step-item__desc">类别、样本、批次是否够</span>' +
            "</span>" +
            '<span class="step-item__meta"><span class="badge badge-neutral" ' +
              'id="ds-step-check-badge">未开始</span></span>' +
          "</li>" +
          '<li class="step-item" id="ds-step-split">' +
            '<span class="step-item__index" aria-hidden="true">4</span>' +
            '<span class="step-item__content">' +
              '<span class="step-item__title">划分</span>' +
              '<span class="step-item__desc">按批次切训练/验证集</span>' +
            "</span>" +
            '<span class="step-item__meta"><span class="badge badge-neutral" ' +
              'id="ds-step-split-badge">未开始</span></span>' +
          "</li>" +
        "</ol>" +

        '<div class="app-split app-split--left">' +

          // ---- 左栏 300px：数据集列表 + 新建 ---- //
          '<section class="card" aria-labelledby="ds-list-title">' +
            '<div class="card-header">' +
              '<h2 class="card-title" id="ds-list-title">数据集</h2>' +
              '<span class="badge badge-neutral" id="ds-count-badge">0 个</span>' +
            "</div>" +
            '<div class="card-body">' +
              '<ul class="stack stack--sm" id="ds-list" style="list-style:none"></ul>' +
              '<div class="empty-state" id="ds-list-empty" hidden>' +
                "<h3>还没有数据集</h3>" +
                "<p>用下面的表单创建第一个。数据集保存在本机，不上传。</p>" +
              "</div>" +
              '<hr class="divider">' +
              '<form class="stack" id="ds-create-form" novalidate>' +
                '<p class="field-label">新建数据集</p>' +
                '<div class="field">' +
                  '<label class="field-label" for="ds-new-name">名称</label>' +
                  '<input class="field-input" id="ds-new-name" type="text" ' +
                    'autocomplete="off" spellcheck="false" placeholder="my-objects">' +
                  '<p class="field-hint">名称会规范成目录名：只能用字母、数字、' +
                    "<code>_</code>、<code>-</code>、<code>.</code>，最长 64 字符。</p>" +
                "</div>" +
                '<div class="field">' +
                  '<label class="field-label" for="ds-new-classes">初始类别</label>' +
                  '<input class="field-input" id="ds-new-classes" type="text" ' +
                    'autocomplete="off" spellcheck="false" placeholder="apple, banana">' +
                  '<p class="field-hint">用逗号分隔。训练至少需要 2 个类别，建议一次建好。</p>' +
                "</div>" +
                '<button class="btn btn-primary" type="submit" id="ds-create-btn">创建并打开</button>' +
                '<p class="field-error" id="ds-create-error" hidden></p>' +
              "</form>" +
            "</div>" +
          "</section>" +

          // ---- 主区 ---- //
          '<div class="app-split__main">' +
            '<div class="app-split app-split--narrow">' +

              // ---- 类别 + 样本 ---- //
              '<div class="app-split__main">' +

                '<section class="card" aria-labelledby="ds-classes-title">' +
                  '<div class="card-header">' +
                    '<h2 class="card-title" id="ds-classes-title">类别</h2>' +
                    '<span class="badge badge-neutral" id="ds-current-name">未打开数据集</span>' +
                  "</div>" +
                  '<div class="card-body">' +
                    '<div class="empty-state" id="ds-no-dataset">' +
                      "<h3>还没有打开数据集</h3>" +
                      "<p>先在左边创建或打开一个数据集，才能管理类别、采集样本和执行划分。</p>" +
                    "</div>" +
                    '<div class="stack" id="ds-classes" hidden>' +
                      '<ul class="stack stack--sm" id="ds-class-list" style="list-style:none"></ul>' +
                      '<div class="actions">' +
                        '<div class="field grow">' +
                          '<label class="field-label" for="ds-add-class">新增类别</label>' +
                          '<input class="field-input" id="ds-add-class" type="text" ' +
                            'autocomplete="off" spellcheck="false" placeholder="orange">' +
                        "</div>" +
                        '<button class="btn btn-secondary" type="button" id="ds-add-class-btn">' +
                          "添加类别</button>" +
                      "</div>" +
                    "</div>" +
                  "</div>" +
                "</section>" +

                '<section class="card" aria-labelledby="ds-samples-title">' +
                  '<div class="card-header">' +
                    '<h2 class="card-title" id="ds-samples-title">样本</h2>' +
                    '<div class="field" style="min-width:180px">' +
                      '<label class="field-label" for="ds-sample-filter">按类别筛选</label>' +
                      '<select class="field-select" id="ds-sample-filter">' +
                        '<option value="">全部类别</option>' +
                      "</select>" +
                    "</div>" +
                  "</div>" +
                  '<div class="card-body">' +
                    '<p class="field-hint">每张缩略图底部显示类别与采集批次号；' +
                      "删除按钮在右上角，删除前会二次确认。</p>" +
                    '<div class="thumb-grid thumb-grid--4" id="ds-thumbs"></div>' +
                    '<div class="empty-state" id="ds-thumbs-empty" hidden>' +
                      "<h3 id=\"ds-thumbs-empty-title\">这个类别还没有图片</h3>" +
                      '<p id="ds-thumbs-empty-desc">选好类别后点“采集一张”，先拍 20–30 张。</p>' +
                    "</div>" +
                  "</div>" +
                "</section>" +

              "</div>" +

              // ---- 右栏：采集 / 体检 / 划分 ---- //
              '<div class="app-split__aside">' +

                '<section class="card" aria-labelledby="ds-capture-title">' +
                  '<div class="card-header">' +
                    '<h2 class="card-title" id="ds-capture-title">采集</h2>' +
                    '<span class="pill pill-neutral" id="ds-capture-pill">' +
                      '<span class="pill-dot" aria-hidden="true"></span>' +
                      '<span id="ds-capture-pill-text">未采集</span>' +
                    "</span>" +
                  "</div>" +
                  '<div class="card-body">' +
                    '<div class="field">' +
                      '<label class="field-label" for="ds-capture-class">采集类别</label>' +
                      '<select class="field-select" id="ds-capture-class"></select>' +
                      '<p class="field-hint" id="ds-capture-target">正在存入：未选择数据集</p>' +
                    "</div>" +
                    '<div class="field">' +
                      '<label class="field-label" for="ds-interval">连续采集间隔（毫秒）</label>' +
                      '<input class="field-input" id="ds-interval" type="number" ' +
                        'min="' + CAPTURE_INTERVAL_MIN + '" max="' + CAPTURE_INTERVAL_MAX +
                        '" step="50" value="' + CAPTURE_INTERVAL_DEFAULT + '">' +
                      '<p class="field-hint">间隔越小采得越快，但相邻帧越相似。' +
                        "建议 500ms 左右，并分多批拍摄。</p>" +
                    "</div>" +
                    '<div class="actions">' +
                      '<button class="btn btn-secondary" type="button" id="ds-capture-one" disabled>' +
                        "采集一张</button>" +
                      '<button class="btn btn-primary" type="button" id="ds-capture-start" disabled>' +
                        "开始连续采集</button>" +
                      '<button class="btn btn-danger" type="button" id="ds-capture-stop" disabled hidden>' +
                        "停止采集</button>" +
                      '<span class="btn-reason" id="ds-capture-reason">' +
                        "正在检测采集条件…</span>" +
                    "</div>" +
                    '<dl class="kv-list kv-list--rows">' +
                      "<dt>本批次已采</dt><dd id=\"ds-captured-count\">—</dd>" +
                      "<dt>当前批次号</dt><dd id=\"ds-batch-id\">—</dd>" +
                      "<dt>数据集总样本</dt><dd id=\"ds-total-samples\">—</dd>" +
                    "</dl>" +
                    '<p class="field-hint">一次“开始连续采集 → 停止”记为一个批次；' +
                      "划分验证集时同一批次绝不拆开。</p>" +
                  "</div>" +
                "</section>" +

                '<section class="card" aria-labelledby="ds-check-title">' +
                  '<div class="card-header">' +
                    '<h2 class="card-title" id="ds-check-title">数据体检</h2>' +
                    '<button class="btn btn-ghost btn-sm" type="button" id="ds-check-refresh">' +
                      "重新体检</button>" +
                  "</div>" +
                  '<div class="card-body">' +
                    '<div id="ds-check-result"></div>' +
                    '<div class="banner banner-info">' +
                      '<div class="banner__content">' +
                        '<span class="banner__title">为什么要多批次</span>' +
                        '<span class="banner__body">训练/验证集按“批次”划分，' +
                          "同一批次的相邻近似帧绝不拆开。每类至少 2 个采集批次才能划分验证集，" +
                          "否则验证集和训练集来自同一段连续画面，准确率会虚高。" +
                          "做法：拍一会儿、停一下、换个角度再拍。</span>" +
                      "</div>" +
                    "</div>" +
                    '<p class="field-hint">体检结论来自同一套划分实现（pvl_split），' +
                      "与桌面客户端一致。</p>" +
                  "</div>" +
                "</section>" +

                '<section class="card" aria-labelledby="ds-split-title">' +
                  '<div class="card-header">' +
                    '<h2 class="card-title" id="ds-split-title">划分训练 / 验证</h2>' +
                  "</div>" +
                  '<div class="card-body">' +
                    '<div class="field">' +
                      '<label class="field-label" for="ds-val-ratio">验证集比例</label>' +
                      '<input class="field-input" id="ds-val-ratio" type="number" ' +
                        'min="0.05" max="0.5" step="0.05" value="0.2">' +
                      '<p class="field-hint">按批次切分：同一批次要么全进训练、要么全进验证，' +
                        "因此实际比例通常不是精确值。</p>" +
                    "</div>" +
                    '<div class="field">' +
                      '<label class="field-label" for="ds-seed">随机种子</label>' +
                      '<input class="field-input" id="ds-seed" type="number" ' +
                        'min="0" step="1" value="1234">' +
                      '<p class="field-hint">同一个种子与比例会得到同一份划分，便于复现。</p>' +
                    "</div>" +
                    '<div class="actions">' +
                      '<button class="btn btn-primary" type="button" id="ds-split-run" disabled>' +
                        "执行划分</button>" +
                      '<span class="btn-reason" id="ds-split-reason">先打开数据集。</span>' +
                    "</div>" +
                    '<p class="field-error" id="ds-split-error" hidden></p>' +
                    '<div id="ds-split-result"></div>' +
                    '<div class="banner banner-info" id="ds-split-status">' +
                      '<div class="banner__content">' +
                        '<span class="banner__body" id="ds-split-status-text">尚未打开数据集。</span>' +
                      "</div>" +
                    "</div>" +
                    '<div class="actions">' +
                      '<a class="btn btn-primary is-disabled" href="#/train" id="ds-goto-train" ' +
                        'aria-disabled="true">去训练模型</a>' +
                      '<span class="btn-reason" id="ds-goto-train-reason">先完成划分，再进入训练。</span>' +
                    "</div>" +
                  "</div>" +
                "</section>" +

              "</div>" +

            "</div>" +
          "</div>" +

        "</div>";

      // ---- DOM 引用 ----
      var devicePill = root.querySelector("#ds-device-pill");
      var devicePillText = root.querySelector("#ds-device-pill-text");
      var listBox = root.querySelector("#ds-list");
      var listEmpty = root.querySelector("#ds-list-empty");
      var countBadge = root.querySelector("#ds-count-badge");
      var createForm = root.querySelector("#ds-create-form");
      var createError = root.querySelector("#ds-create-error");
      var stepBadges = {
        create: root.querySelector("#ds-step-create-badge"),
        capture: root.querySelector("#ds-step-capture-badge"),
        check: root.querySelector("#ds-step-check-badge"),
        split: root.querySelector("#ds-step-split-badge"),
      };
      var stepItems = {
        create: root.querySelector("#ds-step-create"),
        capture: root.querySelector("#ds-step-capture"),
        check: root.querySelector("#ds-step-check"),
        split: root.querySelector("#ds-step-split"),
      };
      var noDataset = root.querySelector("#ds-no-dataset");
      var classesBox = root.querySelector("#ds-classes");
      var classList = root.querySelector("#ds-class-list");
      var addClassInput = root.querySelector("#ds-add-class");
      var addClassBtn = root.querySelector("#ds-add-class-btn");
      var currentName = root.querySelector("#ds-current-name");
      var filterSelect = root.querySelector("#ds-sample-filter");
      var thumbs = root.querySelector("#ds-thumbs");
      var thumbsEmpty = root.querySelector("#ds-thumbs-empty");
      var thumbsEmptyTitle = root.querySelector("#ds-thumbs-empty-title");
      var thumbsEmptyDesc = root.querySelector("#ds-thumbs-empty-desc");
      var captureClass = root.querySelector("#ds-capture-class");
      var captureTarget = root.querySelector("#ds-capture-target");
      var intervalInput = root.querySelector("#ds-interval");
      var captureOneBtn = root.querySelector("#ds-capture-one");
      var captureStartBtn = root.querySelector("#ds-capture-start");
      var captureStopBtn = root.querySelector("#ds-capture-stop");
      var captureReason = root.querySelector("#ds-capture-reason");
      var capturePill = root.querySelector("#ds-capture-pill");
      var capturePillText = root.querySelector("#ds-capture-pill-text");
      var capturedCount = root.querySelector("#ds-captured-count");
      var batchIdNode = root.querySelector("#ds-batch-id");
      var totalSamples = root.querySelector("#ds-total-samples");
      var checkResult = root.querySelector("#ds-check-result");
      var checkRefresh = root.querySelector("#ds-check-refresh");
      var ratioInput = root.querySelector("#ds-val-ratio");
      var seedInput = root.querySelector("#ds-seed");
      var splitRun = root.querySelector("#ds-split-run");
      var splitReason = root.querySelector("#ds-split-reason");
      var splitError = root.querySelector("#ds-split-error");
      var splitResult = root.querySelector("#ds-split-result");
      var splitStatusBox = root.querySelector("#ds-split-status");
      var splitStatusText = root.querySelector("#ds-split-status-text");
      var gotoTrain = root.querySelector("#ds-goto-train");
      var gotoTrainReason = root.querySelector("#ds-goto-train-reason");

      // ---- 页面状态 ----
      var state = {
        datasets: [],
        current: null,          // /api/datasets/current 快照
        samples: [],
        filterClass: "",
        deviceConnected: false,
        deviceReason: "正在检测手机连接状态…",
        capturing: false,
        captureTimer: null,
        captureBusy: false,
        splitInfo: null,
        checkInfo: null,
      };
      var destroyed = false;
      var timers = { current: null, device: null };

      // ---- 小工具 ----
      function showError(node, message, hint) {
        node.hidden = false;
        node.textContent = hint ? message + " " + hint : message;
      }

      function clearError(node) {
        node.hidden = true;
        node.textContent = "";
      }

      function setBadge(node, text, kind) {
        node.textContent = text;
        node.className = "badge " + (kind || "badge-neutral");
      }

      function setCapturePill(text, kind) {
        capturePill.classList.remove("pill-neutral", "pill-success", "pill-warning",
                                     "pill-danger", "pill-live");
        capturePill.classList.add("pill-" + (kind || "neutral"));
        capturePillText.textContent = text;
      }

      /** 采集不可用的真实原因：按钮禁用时必须同时显示这段文字。 */
      function captureBlockReason() {
        if (!state.current || !state.current.opened) {
          return "还没有打开数据集：先创建或打开一个数据集。";
        }
        if (!state.current.classes || !state.current.classes.length) {
          return "数据集里还没有类别：先添加至少一个类别。";
        }
        if (!state.deviceConnected) {
          return "请先在实验台连接手机：" + state.deviceReason;
        }
        return "";
      }

      function renderCaptureAvailability() {
        var reason = captureBlockReason();
        var blocked = !!reason;
        captureOneBtn.disabled = blocked || state.captureBusy;
        captureStartBtn.disabled = blocked || state.capturing;
        captureStopBtn.disabled = !state.capturing;
        captureStartBtn.hidden = state.capturing;
        captureStopBtn.hidden = !state.capturing;
        if (reason) {
          captureReason.textContent = reason;
        } else if (state.capturing) {
          captureReason.textContent = "正在连续采集：每次停止会结束一个批次。";
        } else {
          captureReason.textContent = "";
        }
      }

      function renderSteps() {
        var opened = !!(state.current && state.current.opened);
        var classes = opened ? (state.current.classes || []).length : 0;
        var total = opened ? state.current.total_samples : 0;
        var ready = !!(state.checkInfo && state.checkInfo.ready);
        var splitOk = !!(state.splitInfo && state.splitInfo.exists);

        setBadge(stepBadges.create, opened ? "已完成" : "未开始",
                 opened ? "badge-success" : "badge-neutral");
        stepItems.create.classList.toggle("is-done", opened);
        stepItems.create.classList.toggle("is-active", !opened);

        setBadge(stepBadges.capture, total > 0 ? total + " 张" : "未开始",
                 total > 0 ? "badge-success" : "badge-neutral");
        stepItems.capture.classList.toggle("is-done", total > 0);
        stepItems.capture.classList.toggle("is-active", opened && classes >= 2 && total === 0);

        setBadge(stepBadges.check, !opened ? "未开始" : (ready ? "通过" : "有问题"),
                 !opened ? "badge-neutral" : (ready ? "badge-success" : "badge-danger"));
        stepItems.check.classList.toggle("is-done", ready);
        stepItems.check.classList.toggle("is-active", opened && total > 0 && !ready);
        stepItems.check.classList.toggle("is-blocked", opened && total > 0 && !ready);

        setBadge(stepBadges.split, splitOk ? "已划分" : "未划分",
                 splitOk ? "badge-success" : "badge-neutral");
        stepItems.split.classList.toggle("is-done", splitOk);
        stepItems.split.classList.toggle("is-active", ready && !splitOk);
      }

      // ---- 数据集列表 ----
      async function loadDatasets() {
        try {
          var data = await PVL.api("/api/datasets");
          state.datasets = data.datasets || [];
          renderDatasetList();
        } catch (error) {
          var info = PVL.describeError(error);
          listEmpty.hidden = false;
          listEmpty.querySelector("h3").textContent = "数据集列表加载失败";
          listEmpty.querySelector("p").textContent = info.message +
            (info.hint ? " " + info.hint : "");
        }
      }

      function renderDatasetList() {
        countBadge.textContent = state.datasets.length + " 个";
        if (!state.datasets.length) {
          listBox.innerHTML = "";
          listEmpty.hidden = false;
          return;
        }
        listEmpty.hidden = true;
        listBox.innerHTML = state.datasets.map(function (item) {
          var active = !!(state.current && state.current.opened &&
                          state.current.root === item.root);
          return '<li class="card card--flat" data-root="' + PVL.escapeHtml(item.root) + '">' +
            '<div class="card-body" style="padding:var(--space-3) var(--space-4)">' +
              '<div class="row row--between">' +
                '<div style="min-width:0">' +
                  '<p class="card-title truncate">' + PVL.escapeHtml(item.name) + "</p>" +
                  '<p class="field-hint">' +
                    PVL.escapeHtml(String(item.classes)) + " 类 · " +
                    PVL.escapeHtml(String(item.samples)) + " 张</p>" +
                "</div>" +
                '<button class="btn btn-secondary btn-sm" type="button" data-open="' +
                  PVL.escapeHtml(item.root) + '"' + (active ? " disabled" : "") + ">" +
                  (active ? "已打开" : "打开") + "</button>" +
              "</div>" +
            "</div>" +
          "</li>";
        }).join("");
      }

      // ---- 当前数据集 ----
      async function loadCurrent(light) {
        try {
          state.current = await PVL.api("/api/datasets/current");
        } catch (error) {
          var info = PVL.describeError(error);
          if (info.code === "no_dataset") {
            state.current = null;
          } else if (!light) {
            PVL.toast("读取当前数据集失败：" + info.message, "danger");
            return;
          }
        }
        if (light) {
          applyCurrentSnapshot();
        } else {
          renderCurrent();
        }
      }

      /** 轮询用的轻量刷新：只改计数与状态，不重建网格（避免缩略图反复重载）。 */
      function applyCurrentSnapshot() {
        var current = state.current;
        if (!current || !current.opened) {
          renderSteps();
          return;
        }
        totalSamples.textContent = String(current.total_samples);
        capturedCount.textContent = String(current.captured_in_batch);
        batchIdNode.textContent = current.current_batch || "—";
        (current.classes || []).forEach(function (item) {
          var node = classList.querySelector(
            '[data-name="' + item.name + '"] .ds-class-meta');
          if (node) {
            node.textContent = item.count + " 张 · " + item.batches + " 个批次";
          }
        });
        if (current.capturing && !state.capturing) {
          state.capturing = true;
          startCaptureTimer();
        } else if (!current.capturing && state.capturing) {
          stopCaptureTimer(false);
        }
        setCapturePill(state.capturing ? "采集中" : "未采集",
                       state.capturing ? "live" : "neutral");
        renderCaptureAvailability();
        renderSteps();
      }

      function renderCurrent() {
        var current = state.current;
        if (!current || !current.opened) {
          noDataset.hidden = false;
          classesBox.hidden = true;
          currentName.textContent = "未打开数据集";
          currentName.className = "badge badge-neutral";
          captureTarget.textContent = "正在存入：未选择数据集";
          setCapturePill("未采集", "neutral");
          capturedCount.textContent = "—";
          batchIdNode.textContent = "—";
          totalSamples.textContent = "—";
          classList.innerHTML = "";
          captureClass.innerHTML = "";
          state.samples = [];
          renderThumbs();
          splitRun.disabled = true;
          splitReason.textContent = "先创建或打开一个数据集。";
          splitStatusText.textContent = "尚未打开数据集，无法划分。";
          splitStatusBox.className = "banner banner-info";
          splitResult.innerHTML = "";
          state.splitInfo = null;
          state.checkInfo = null;
          checkResult.innerHTML = "";
          setTrainLink(false, "先完成划分，再进入训练。");
          renderSteps();
          renderCaptureAvailability();
          return;
        }

        noDataset.hidden = true;
        classesBox.hidden = false;
        currentName.textContent = current.name;
        currentName.className = "badge badge-info";
        var classes = current.classes || [];
        var selected = captureClass.value;
        if (!selected || !classes.some(function (item) { return item.name === selected; })) {
          selected = classes.length ? classes[0].name : "";
        }
        renderClassList(classes, selected);
        renderFilterOptions(classes);
        renderCaptureAvailability();
        setCapturePill(state.capturing ? "采集中" : "未采集",
                       state.capturing ? "live" : "neutral");

        var hasClasses = classes.length > 0;
        splitRun.disabled = !hasClasses;
        splitReason.textContent = hasClasses
          ? "按批次切分，结果写入 split.json。"
          : "先添加至少 2 个类别，再执行划分。";
        if (hasClasses) loadSplitStatus();
        loadCheck();
        loadSamples();
        renderSteps();
      }

      function renderClassList(classes, selected) {
        classList.innerHTML = classes.map(function (item) {
          return '<li class="card card--flat" data-name="' + PVL.escapeHtml(item.name) + '">' +
            '<div class="card-body" style="padding:var(--space-3) var(--space-4)">' +
              '<div class="row row--between">' +
                '<div style="min-width:0">' +
                  '<p class="card-title truncate">' +
                    PVL.escapeHtml(item.display_name) + "</p>" +
                  '<p class="field-hint ds-class-meta">' +
                    PVL.escapeHtml(String(item.count)) + " 张 · " +
                    PVL.escapeHtml(String(item.batches)) + " 个批次</p>" +
                "</div>" +
                '<div class="actions">' +
                  '<button class="btn btn-ghost btn-sm" type="button" data-rename="' +
                    PVL.escapeHtml(item.name) + '">重命名</button>' +
                  '<button class="btn btn-ghost btn-sm" type="button" data-remove="' +
                    PVL.escapeHtml(item.name) + '">删除</button>' +
                "</div>" +
              "</div>" +
            "</div>" +
          "</li>";
        }).join("");
        captureClass.innerHTML = classes.length
          ? classes.map(function (item) {
              var attr = item.name === selected ? " selected" : "";
              return '<option value="' + PVL.escapeHtml(item.name) + '"' + attr + ">" +
                PVL.escapeHtml(item.display_name) + "（" +
                PVL.escapeHtml(String(item.count)) + " 张）</option>";
            }).join("")
          : '<option value="">（还没有类别）</option>';
        var display = selected;
        classes.forEach(function (item) {
          if (item.name === selected) display = item.display_name;
        });
        captureTarget.textContent = "正在存入 " + state.current.name + " → " +
          (display || "（还没有类别）");
      }

      function renderFilterOptions(classes) {
        filterSelect.innerHTML = '<option value="">全部类别（' +
          PVL.escapeHtml(String(state.current ? state.current.total_samples : 0)) +
          " 张）</option>" +
          classes.map(function (item) {
            var attr = item.name === state.filterClass ? " selected" : "";
            return '<option value="' + PVL.escapeHtml(item.name) + '"' + attr + ">" +
              PVL.escapeHtml(item.display_name) + "（" +
              PVL.escapeHtml(String(item.count)) + " 张）</option>";
          }).join("");
      }

      // ---- 样本 ----
      async function loadSamples() {
        if (!state.current || !state.current.opened) {
          state.samples = [];
          renderThumbs();
          return;
        }
        try {
          var data = await PVL.api("/api/datasets/samples" +
            (state.filterClass ? "?class=" + encodeURIComponent(state.filterClass) : ""));
          state.samples = data.samples || [];
        } catch (error) {
          var info = PVL.describeError(error);
          if (info.code !== "no_dataset") {
            PVL.toast("样本列表加载失败：" + info.message, "danger");
          }
          state.samples = [];
        }
        renderThumbs();
      }

      function renderThumbs() {
        var samples = state.samples;
        if (!state.current || !state.current.opened) {
          thumbs.innerHTML = "";
          thumbsEmpty.hidden = false;
          thumbsEmptyTitle.textContent = "还没有打开数据集";
          thumbsEmptyDesc.textContent =
            "先创建或打开一个数据集，这里会显示已采集的样本缩略图。";
          return;
        }
        if (!samples.length) {
          thumbs.innerHTML = "";
          thumbsEmpty.hidden = false;
          if (state.filterClass) {
            thumbsEmptyTitle.textContent = "这个类别还没有图片";
            thumbsEmptyDesc.textContent = "选好类别后点“采集一张”，先拍 20–30 张。";
          } else {
            thumbsEmptyTitle.textContent = "数据集里还没有图片";
            thumbsEmptyDesc.textContent =
              "连接手机后选一个类别，先拍 20–30 张；每类至少 2 个批次才能划分验证集。";
          }
          return;
        }
        thumbsEmpty.hidden = true;
        var shown = samples.slice(0, SAMPLE_LIMIT);
        thumbs.innerHTML = shown.map(function (sample) {
          var cls = sample.class || "";
          var batch = sample.batch || "loose";
          var caption = cls + " · " + batch;
          return '<figure class="thumb-item" data-path="' + PVL.escapeHtml(sample.path) + '">' +
            '<img src="' + PVL.escapeHtml(sample.url) + '" alt="样本 ' +
              PVL.escapeHtml(sample.path) + '" loading="lazy">' +
            '<button class="badge badge-danger thumb-item__badge" type="button" ' +
              'data-delete="' + PVL.escapeHtml(sample.path) + '" ' +
              'aria-label="删除样本 ' + PVL.escapeHtml(sample.path) + '" ' +
              'title="删除这张样本">删除</button>' +
            '<figcaption class="thumb-item__caption" title="' +
              PVL.escapeHtml(caption) + '">' + PVL.escapeHtml(caption) + "</figcaption>" +
          "</figure>";
        }).join("");
        if (samples.length > shown.length) {
          thumbs.innerHTML += '<p class="field-hint">只显示前 ' + shown.length +
            " 张（共 " + samples.length + " 张）。用类别筛选可以看全某一类。</p>";
        }
      }

      // ---- 设备状态 ----
      async function pollDevice() {
        try {
          var status = await PVL.api("/api/device/status");
          if (!status.connected) {
            state.deviceConnected = false;
            state.deviceReason = "尚未连接手机，请到实验台填写手机 IP。";
          } else if (status.state !== "Streaming") {
            state.deviceConnected = false;
            state.deviceReason = "手机未在推流（" +
              (status.state_label || status.state) + "）。";
          } else if (status.frame_stale) {
            state.deviceConnected = false;
            state.deviceReason = "已连接但当前没有新画面，请确认手机仍在推流。";
          } else {
            state.deviceConnected = true;
            state.deviceReason = "";
          }
          devicePill.classList.remove("pill-neutral", "pill-success", "pill-warning",
                                      "pill-danger", "pill-live");
          devicePill.classList.add(state.deviceConnected ? "pill-live" : "pill-warning");
          devicePillText.textContent = state.deviceConnected
            ? "手机已连接 · 正在推流"
            : "手机未就绪：" + state.deviceReason;
        } catch (error) {
          state.deviceConnected = false;
          state.deviceReason = "读取设备状态失败：" + PVL.describeError(error).message;
          devicePill.classList.remove("pill-success", "pill-live");
          devicePill.classList.add("pill-warning");
          devicePillText.textContent = state.deviceReason;
        }
        renderCaptureAvailability();
      }

      // ---- 采集 ----
      async function captureOnce() {
        if (state.captureBusy) return;
        var className = captureClass.value;
        if (!className) {
          PVL.toast("请先添加并选择一个采集类别", "warning");
          return;
        }
        state.captureBusy = true;
        renderCaptureAvailability();
        try {
          var result = await PVL.api("/api/datasets/capture/one", {
            method: "POST", body: { class: className },
          });
          state.current = result.dataset || state.current;
          capturedCount.textContent = String(result.captured);
          batchIdNode.textContent = result.batch_id || "—";
          totalSamples.textContent = String(
            state.current ? state.current.total_samples : "—");
          applyCurrentSnapshot();
          // 连续采集中不重建缩略图网格（每帧重建会反复请求图片）；
          // 单张采集时刷新一次，让用户立刻看到新样本。
          if (!state.capturing) {
            loadSamples();
            loadCheck();
          }
        } catch (error) {
          // 采集中断：toast 真实原因；连续采集立即停止，绝不假装继续。
          var info = PVL.describeError(error);
          PVL.toast("采集失败：" + info.message, "danger");
          if (state.capturing) {
            stopCaptureTimer(true);
            await stopBackendCapture();
          }
        } finally {
          state.captureBusy = false;
          renderCaptureAvailability();
        }
      }

      function startCaptureTimer() {
        stopCaptureTimer(false);
        var interval = parseInt(intervalInput.value || CAPTURE_INTERVAL_DEFAULT, 10);
        if (!(interval >= CAPTURE_INTERVAL_MIN && interval <= CAPTURE_INTERVAL_MAX)) {
          interval = CAPTURE_INTERVAL_DEFAULT;
          intervalInput.value = String(interval);
          PVL.toast("采集间隔已重置为 " + interval + "ms（允许范围 " +
            CAPTURE_INTERVAL_MIN + "–" + CAPTURE_INTERVAL_MAX + "ms）", "warning");
        }
        state.captureTimer = setInterval(function () {
          if (destroyed || !state.capturing) return;
          captureOnce();
        }, interval);
      }

      function stopCaptureTimer(showToast) {
        if (state.captureTimer) {
          clearInterval(state.captureTimer);
          state.captureTimer = null;
        }
        state.capturing = false;
        renderCaptureAvailability();
        if (showToast) setCapturePill("已停止", "warning");
      }

      async function stopBackendCapture() {
        try {
          var data = await PVL.api("/api/datasets/capture/stop", {
            method: "POST", body: {},
          });
          state.current = data;
          applyCurrentSnapshot();
        } catch (error) {
          // 后端可能已经不在采集态：不阻塞界面，只说清原因。
          PVL.toast("结束采集批次失败：" + PVL.describeError(error).message, "warning");
        }
      }

      async function startCapture() {
        var className = captureClass.value;
        if (!className) {
          PVL.toast("请先添加并选择一个采集类别", "warning");
          return;
        }
        captureStartBtn.disabled = true;
        try {
          var data = await PVL.api("/api/datasets/capture/start", {
            method: "POST", body: { class: className },
          });
          state.current = data;
          state.capturing = true;
          setCapturePill("采集中", "live");
          applyCurrentSnapshot();
          startCaptureTimer();
          PVL.toast("开始连续采集：每“开始→停止”记为一个批次", "info");
        } catch (error) {
          var info = PVL.describeError(error);
          PVL.toast("无法开始采集：" + info.message, "danger");
          state.capturing = false;
          renderCaptureAvailability();
          pollDevice();
        }
      }

      async function stopCapture() {
        captureStopBtn.disabled = true;
        stopCaptureTimer(false);
        var saved = capturedCount.textContent;
        await stopBackendCapture();
        loadSamples();
        loadCheck();
        loadSplitStatus();
        setCapturePill("未采集", "neutral");
        PVL.toast("已停止采集，本批次共 " + saved + " 张", "success");
      }

      // ---- 体检 ----
      async function loadCheck() {
        if (!state.current || !state.current.opened) {
          state.checkInfo = null;
          checkResult.innerHTML = "";
          renderSteps();
          return;
        }
        try {
          state.checkInfo = await PVL.api("/api/datasets/check");
          renderCheck(state.checkInfo);
        } catch (error) {
          var info = PVL.describeError(error);
          checkResult.innerHTML =
            '<div class="banner banner-danger"><div class="banner__content">' +
            '<span class="banner__title">体检失败</span>' +
            '<span class="banner__body">' + PVL.escapeHtml(info.message) +
            (info.hint ? " " + PVL.escapeHtml(info.hint) : "") +
            "</span></div></div>";
        }
        renderSteps();
      }

      function renderCheck(info) {
        var problems = info.problems || [];
        var warnings = info.warnings || [];
        var counts = info.class_counts || {};
        var rows = "";
        problems.forEach(function (item) {
          rows += '<tr><td data-label="级别"><span class="badge badge-danger">问题</span></td>' +
            '<td data-label="体检结论">' + PVL.escapeHtml(item) + "</td></tr>";
        });
        warnings.forEach(function (item) {
          rows += '<tr><td data-label="级别"><span class="badge badge-warning">提醒</span></td>' +
            '<td data-label="体检结论">' + PVL.escapeHtml(item) + "</td></tr>";
        });
        var html = '<div class="banner ' +
          (problems.length ? "banner-danger" : "banner-success") + '">' +
          '<div class="banner__content">' +
          '<span class="banner__title">' +
          (problems.length ? "有 " + problems.length + " 个阻断问题" : "体检通过") +
          "</span>" +
          '<span class="banner__body">' +
          (problems.length
            ? "处理完这些问题才能划分验证集。"
            : "可以执行划分；划分只按批次切分，不会拆开相邻近似帧。") +
          "</span></div></div>";
        if (rows) {
          html += '<div class="table-wrap"><table class="table table--stack">' +
            "<thead><tr><th>级别</th><th>体检结论</th></tr></thead>" +
            "<tbody>" + rows + "</tbody></table></div>";
        }
        var classLines = Object.keys(counts).map(function (name) {
          return PVL.escapeHtml(name) + " " + PVL.escapeHtml(String(counts[name]));
        }).join(" · ");
        html += '<dl class="kv-list kv-list--rows">' +
          "<dt>总样本</dt><dd>" + PVL.escapeHtml(String(info.total)) + "</dd>" +
          "<dt>按类别</dt><dd>" + (classLines || "—") + "</dd>" +
          "<dt>可否划分</dt><dd>" +
          (info.ready ? "可以（无阻断问题）" : "暂不可以（见上方问题）") + "</dd></dl>";
        checkResult.innerHTML = html;
      }

      // ---- 划分 ----
      function setTrainLink(enabled, reason) {
        gotoTrain.classList.toggle("is-disabled", !enabled);
        gotoTrain.setAttribute("aria-disabled", enabled ? "false" : "true");
        gotoTrainReason.textContent = reason;
      }

      async function loadSplitStatus() {
        if (!state.current || !state.current.opened) return;
        try {
          state.splitInfo = await PVL.api("/api/datasets/split");
          renderSplitStatus(state.splitInfo);
        } catch (error) {
          var info = PVL.describeError(error);
          splitStatusText.textContent = "读取划分状态失败：" + info.message;
          splitStatusBox.className = "banner banner-warning";
        }
        renderSteps();
      }

      function renderSplitStatus(status) {
        if (!status.exists) {
          splitStatusText.textContent =
            "还没有划分文件（split.json）。执行一次划分后，训练页才能读到验证集。";
          splitStatusBox.className = "banner banner-warning";
          splitResult.innerHTML = "";
          setTrainLink(false, "先执行划分，再进入训练。");
          return;
        }
        var problems = status.problems || [];
        var warnings = status.warnings || [];
        splitStatusText.textContent = "已存在划分文件：" + status.path +
          "（seed " + status.seed + "，验证比例 " +
          Math.round(status.val_ratio * 100) + "%）。";
        splitStatusBox.className = problems.length
          ? "banner banner-warning"
          : "banner banner-success";
        splitResult.innerHTML = renderSplitCounts({
          train: status.train, val: status.val,
          train_by_class: {}, val_by_class: {},
          seed: status.seed, val_ratio: status.val_ratio,
          problems: problems, warnings: warnings,
        });
        setTrainLink(true, "划分已就绪：训练页会读取这份 split.json。");
      }

      function renderSplitCounts(result) {
        var byClass = function (label, map) {
          var keys = Object.keys(map || {});
          if (!keys.length) return "";
          return '<div class="kv-list kv-list--rows" style="margin-top:var(--space-3)">' +
            "<dt>" + label + "按类别</dt><dd>" +
            keys.map(function (name) {
              return PVL.escapeHtml(name) + " " + PVL.escapeHtml(String(map[name]));
            }).join(" · ") + "</dd></div>";
        };
        var html = '<div class="banner banner-success"><div class="banner__content">' +
          '<span class="banner__title">训练 ' + PVL.escapeHtml(String(result.train)) +
          " 张 / 验证 " + PVL.escapeHtml(String(result.val)) + " 张 · 按批次 · seed " +
          PVL.escapeHtml(String(result.seed)) + "</span>" +
          '<span class="banner__body">验证比例 ' +
          Math.round(result.val_ratio * 100) + "%。同一批次的样本不会跨集合，" +
          "因此数量通常不是精确比例，这是正常的。</span>" +
          "</div></div>" +
          byClass("训练", result.train_by_class) +
          byClass("验证", result.val_by_class);
        (result.problems || []).forEach(function (item) {
          html += '<div class="banner banner-danger"><div class="banner__content">' +
            '<span class="banner__body">' + PVL.escapeHtml(item) + "</span></div></div>";
        });
        (result.warnings || []).forEach(function (item) {
          html += '<div class="banner banner-warning"><div class="banner__content">' +
            '<span class="banner__body">' + PVL.escapeHtml(item) + "</span></div></div>";
        });
        return html;
      }

      async function runSplit() {
        clearError(splitError);
        var ratio = parseFloat(ratioInput.value);
        var seed = parseInt(seedInput.value || "1234", 10);
        if (!(ratio > 0 && ratio < 1)) {
          showError(splitError, "验证集比例必须在 0 和 1 之间，例如 0.2。");
          ratioInput.focus();
          return;
        }
        if (!(seed >= 0)) {
          showError(splitError, "随机种子必须是非负整数。");
          seedInput.focus();
          return;
        }
        splitRun.disabled = true;
        splitRun.textContent = "划分中…";
        try {
          var result = await PVL.api("/api/datasets/split", {
            method: "POST",
            body: { val_ratio: ratio, seed: seed },
          });
          state.splitInfo = result;
          splitResult.innerHTML = renderSplitCounts(result);
          splitStatusText.textContent = "划分文件已写入：" + result.split_path;
          splitStatusBox.className = "banner banner-success";
          setTrainLink(true, "划分已就绪：训练页会读取这份 split.json。");
          PVL.toast("划分完成：训练 " + result.train + " 张 / 验证 " +
            result.val + " 张", "success");
          renderSteps();
          loadCheck();
        } catch (error) {
          var info = PVL.describeError(error);
          showError(splitError, "划分失败：" + info.message, info.hint);
          PVL.toast("划分失败：" + info.message, "danger");
        } finally {
          splitRun.disabled = !(state.current && state.current.opened);
          splitRun.textContent = "执行划分";
        }
      }

      // ---- 事件 ----
      createForm.addEventListener("submit", async function (event) {
        event.preventDefault();
        var name = root.querySelector("#ds-new-name").value.trim();
        var classes = root.querySelector("#ds-new-classes").value
          .split(/[,，;；]/)
          .map(function (item) { return item.trim(); })
          .filter(Boolean);
        if (!name) {
          showError(createError, "请填写数据集名称。");
          root.querySelector("#ds-new-name").focus();
          return;
        }
        clearError(createError);
        root.querySelector("#ds-create-btn").disabled = true;
        try {
          var data = await PVL.api("/api/datasets/create", {
            method: "POST", body: { name: name, classes: classes },
          });
          state.current = data;
          state.filterClass = "";
          PVL.toast("已创建并打开数据集 " + (data.name || name), "success");
          root.querySelector("#ds-new-name").value = "";
          root.querySelector("#ds-new-classes").value = "";
          await loadDatasets();
          renderCurrent();
          loadSplitStatus();
        } catch (error) {
          var info = PVL.describeError(error);
          showError(createError, "创建失败：" + info.message, info.hint);
        } finally {
          root.querySelector("#ds-create-btn").disabled = false;
        }
      });

      listBox.addEventListener("click", async function (event) {
        var button = event.target.closest("[data-open]");
        if (!button || button.disabled) return;
        var item = button.closest("[data-root]");
        var openRoot = item ? item.getAttribute("data-root") : "";
        if (!openRoot) return;
        try {
          var data = await PVL.api("/api/datasets/open", {
            method: "POST", body: { root: openRoot },
          });
          state.current = data;
          state.filterClass = "";
          PVL.toast("已打开数据集 " + (data.name || ""), "success");
          await loadDatasets();
          renderCurrent();
          loadSplitStatus();
        } catch (error) {
          var info = PVL.describeError(error);
          showError(createError, "打开失败：" + info.message, info.hint);
        }
      });

      addClassBtn.addEventListener("click", async function () {
        var name = addClassInput.value.trim();
        if (!name) {
          PVL.toast("请填写类别名称", "warning");
          addClassInput.focus();
          return;
        }
        try {
          var data = await PVL.api("/api/datasets/classes/add", {
            method: "POST", body: { name: name },
          });
          state.current = data;
          addClassInput.value = "";
          PVL.toast("已添加类别 " + name, "success");
          renderCurrent();
        } catch (error) {
          PVL.toast("添加类别失败：" + PVL.describeError(error).message, "danger");
        }
      });

      classList.addEventListener("click", async function (event) {
        var renameBtn = event.target.closest("[data-rename]");
        var removeBtn = event.target.closest("[data-remove]");
        if (renameBtn) {
          var oldName = renameBtn.getAttribute("data-rename");
          var answer = window.prompt("把类别 “" + oldName + "” 重命名为：", oldName);
          if (answer === null) return;
          var nextName = answer.trim();
          if (!nextName || nextName === oldName) return;
          try {
            var data = await PVL.api("/api/datasets/classes/rename", {
              method: "POST", body: { name: oldName, new_name: nextName },
            });
            state.current = data;
            PVL.toast("已重命名为 " + nextName, "success");
            if (state.filterClass === oldName) state.filterClass = nextName;
            renderCurrent();
          } catch (error) {
            PVL.toast("重命名失败：" + PVL.describeError(error).message, "danger");
          }
          return;
        }
        if (removeBtn) {
          var name = removeBtn.getAttribute("data-remove");
          var ok = window.confirm(
            "删除类别 “" + name + "”？\n" +
            "该类别下已采集的图片会一起从数据集移除，且无法从本页恢复。");
          if (!ok) return;
          try {
            var removed = await PVL.api("/api/datasets/classes/remove", {
              method: "POST", body: { name: name },
            });
            state.current = removed;
            if (state.filterClass === name) {
              state.filterClass = "";
            }
            PVL.toast("已删除类别 " + name, "info");
            renderCurrent();
          } catch (error) {
            PVL.toast("删除类别失败：" + PVL.describeError(error).message, "danger");
          }
        }
      });

      filterSelect.addEventListener("change", function () {
        state.filterClass = filterSelect.value;
        loadSamples();
      });

      thumbs.addEventListener("click", async function (event) {
        var button = event.target.closest("[data-delete]");
        if (!button) return;
        var path = button.getAttribute("data-delete");
        var ok = window.confirm("删除这张样本？\n" + path +
          "\n删除后无法从本页恢复。");
        if (!ok) return;
        try {
          var data = await PVL.api("/api/datasets/samples/delete", {
            method: "POST", body: { path: path },
          });
          state.current = data;
          PVL.toast("已删除 1 张样本", "info");
          state.samples = state.samples.filter(function (item) {
            return item.path !== path;
          });
          renderThumbs();
          applyCurrentSnapshot();
          renderFilterOptions(state.current.classes || []);
          loadCheck();
        } catch (error) {
          PVL.toast("删除失败：" + PVL.describeError(error).message, "danger");
        }
      });

      captureClass.addEventListener("change", function () {
        var current = state.current;
        if (!current || !current.opened) return;
        var selected = captureClass.value;
        var display = selected;
        (current.classes || []).forEach(function (item) {
          if (item.name === selected) display = item.display_name;
        });
        captureTarget.textContent = "正在存入 " + current.name + " → " + display;
      });

      captureOneBtn.addEventListener("click", function () { captureOnce(); });
      captureStartBtn.addEventListener("click", function () { startCapture(); });
      captureStopBtn.addEventListener("click", function () { stopCapture(); });
      checkRefresh.addEventListener("click", function () { loadCheck(); });
      splitRun.addEventListener("click", function () { runSplit(); });

      // ---- 启动 ----
      renderCaptureAvailability();
      renderSteps();
      loadDatasets();
      loadCurrent(false);
      pollDevice();
      timers.device = setInterval(pollDevice, DEVICE_POLL_MS);
      timers.current = setInterval(function () {
        if (!destroyed && state.current && state.current.opened) {
          loadCurrent(true);
        }
      }, CURRENT_POLL_MS);

      // ---- 清理 ----
      return function cleanup() {
        destroyed = true;
        if (state.captureTimer) {
          clearInterval(state.captureTimer);
          state.captureTimer = null;
        }
        if (timers.current) { clearInterval(timers.current); timers.current = null; }
        if (timers.device) { clearInterval(timers.device); timers.device = null; }
        state.capturing = false;
        // 连续采集中离开页面：通知后端结束当前批次（已存图片保留，不删除）。
        if (state.current && state.current.opened && state.current.capturing) {
          PVL.api("/api/datasets/capture/stop", { method: "POST", body: {} })
            .catch(function () { /* 后端可能已自行结束，不影响清理 */ });
        }
      };
    },
  };

  window.PVL_PAGES = window.PVL_PAGES || {};
  window.PVL_PAGES.dataset = page;
})();
