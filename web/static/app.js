/**
 * PhoneVision Lab Web — 前端内核（API 客户端 / 路由 / 全局状态 / 组件）。
 *
 * 为什么是纯 JS 无构建：
 *   - 学习平台需要在学生机上"解压即用"，不引入 npm/打包/转译链路；
 *   - 后端 web/server/ 已经提供稳定的 JSON 接口，前端只需要 fetch + 模板渲染；
 *   - 所有真实状态都来自后端，前端不缓存业务数据，避免出现"界面说成功但实际失败"。
 *
 * 数据契约（后端 web/server/app.py）：
 *   - 成功：{ ok: true, data: ... }
 *   - 失败：{ ok: false, error: { code, message } }
 *   - 二进制：/api/vision/frame、/api/datasets/samples/image 直接返回图片字节
 *
 * 能力边界（前端必须如实呈现，不允许伪造）：
 *   - 设备未连接时，帧接口返回 no_frame，界面显示空状态与连接指导；
 *   - 训练环境不可用时，开始训练按钮禁用并展示原因（不是只灰掉）；
 *   - 硬件只显示控制器真实回执的状态（sent/received/executed/failed）；
 *   - 未接入的指标一律显示"— 未采集"，绝不用 0 或示例数据填充。
 */
(function () {
  "use strict";

  // ===================================================================
  // API 客户端
  // ===================================================================

  async function api(path, options) {
    const opts = options || {};
    const init = {
      method: opts.method || "GET",
      headers: { "Accept": "application/json" },
    };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    let response;
    try {
      response = await fetch(path, init);
    } catch (networkError) {
      const error = new Error("无法连接本地服务：请确认 web 服务正在运行");
      error.code = "network_error";
      error.cause = networkError;
      throw error;
    }
    const contentType = response.headers.get("Content-Type") || "";
    if (!contentType.includes("application/json")) {
      const error = new Error("服务返回了非预期内容（" + (contentType || "未知类型") + "）");
      error.code = "bad_response";
      throw error;
    }
    let payload;
    try {
      payload = await response.json();
    } catch (parseError) {
      const error = new Error("服务响应解析失败");
      error.code = "bad_response";
      throw error;
    }
    if (!payload || payload.ok !== true) {
      const info = (payload && payload.error) || {};
      const error = new Error(info.message || "请求失败");
      error.code = info.code || "unknown";
      throw error;
    }
    return payload.data;
  }

  // ===================================================================
  // 本地存储（学习进度、语言、最近地址）
  // ===================================================================

  const STORAGE_KEY = "phonevision-lab-web/v1";

  function loadStore() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return defaultStore();
      const parsed = JSON.parse(raw);
      return Object.assign(defaultStore(), parsed);
    } catch (error) {
      return defaultStore();
    }
  }

  function defaultStore() {
    return {
      completedLessons: [],
      lastVisited: [],
      language: "zh-CN",
      lastPhoneAddress: "",
      lastControllerAddress: "",
      pipelineMarks: {},
    };
  }

  function saveStore() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
    } catch (error) {
      // 隐私模式下 localStorage 可能不可写：静默降级，不影响使用
    }
  }

  const store = loadStore();

  // ===================================================================
  // 工具
  // ===================================================================

  function escapeHtml(value) {
    return String(value === undefined || value === null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /** 未采集指标的统一样式：绝不用 0 冒充。 */
  function metricValue(value, unit, unavailableText) {
    if (value === null || value === undefined || value === "") {
      return '<span class="metric-unavailable" title="该项尚未采集到真实数据">— ' +
        escapeHtml(unavailableText || "未采集") + "</span>";
    }
    const text = typeof value === "number" ? value.toFixed(value % 1 === 0 ? 0 : 2) : value;
    return '<span class="metric-value">' + escapeHtml(text) +
      (unit ? '<span class="metric-unit">' + escapeHtml(unit) + "</span>" : "") + "</span>";
  }

  function formatTime(seconds) {
    if (seconds === null || seconds === undefined) return "—";
    const total = Math.max(0, Math.round(seconds));
    const m = Math.floor(total / 60);
    const s = total % 60;
    return m + ":" + String(s).padStart(2, "0");
  }

  function el(html) {
    const template = document.createElement("template");
    template.innerHTML = html.trim();
    return template.content.firstElementChild;
  }

  function toast(message, kind) {
    const host = document.getElementById("toast-host");
    if (!host) return;
    const node = el('<div class="toast toast--' + (kind || "info") + '" role="status">' +
      escapeHtml(message) + "</div>");
    host.appendChild(node);
    setTimeout(function () {
      node.classList.add("is-leaving");
      setTimeout(function () { node.remove(); }, 200);
    }, 3200);
  }

  /** 错误提示：结论 + 原因 + 下一步，不展示堆栈。 */
  function describeError(error) {
    const code = error && error.code ? error.code : "unknown";
    const hints = {
      not_connected: "请先在实验台连接手机。",
      no_frame: "请确认手机已开始推流，并且与电脑在同一局域网。",
      no_dataset: "请先在学习路径中创建数据集。",
      no_split: "请先在数据集工作区执行“数据体检并划分”。",
      train_env_unavailable: "请按页面提示安装训练依赖（requirements-train.txt）。",
      busy: "请等待当前任务结束，或先取消。",
      device_error: "请检查设备地址、端口与网络。",
      network_error: "请确认本地服务已启动。",
    };
    return { code: code, message: (error && error.message) || "未知错误",
             hint: hints[code] || "" };
  }

  // ===================================================================
  // 路由
  // ===================================================================

  const routes = [
    { path: "/", page: "home", title: "首页" },
    { path: "/learn", page: "learn", title: "学习中心" },
    { path: "/opensource", page: "opensource", title: "开源学习路线" },
    { path: "/learn/:id", page: "lesson", title: "课程详情" },
    { path: "/progress", page: "progress", title: "学习进度" },
    { path: "/lab", page: "lab", title: "视觉实验台" },
    { path: "/dataset", page: "dataset", title: "数据集工作区" },
    { path: "/train", page: "train", title: "模型训练" },
    { path: "/deploy", page: "deploy", title: "手机部署与推理" },
    { path: "/hardware", page: "hardware", title: "硬件联动" },
    { path: "/performance", page: "performance", title: "性能分析" },
    { path: "/help", page: "help", title: "使用帮助" },
    { path: "/about", page: "about", title: "关于与能力清单" },
  ];

  function parseHash() {
    const raw = (location.hash || "#/").replace(/^#/, "");
    const path = raw.split("?")[0] || "/";
    const parts = path.split("/").filter(Boolean);
    if (parts.length === 0) return { name: "home", params: {} };
    if (parts[0] === "learn" && parts.length >= 2) {
      return { name: "lesson", params: { id: decodeURIComponent(parts[1]) } };
    }
    const known = routes.find(function (route) {
      return route.path === "/" + parts.join("/") && route.path !== "/learn/:id";
    });
    if (known) return { name: known.page, params: {} };
    return { name: "notfound", params: { path: path } };
  }

  let currentPage = null;
  let currentCleanup = null;

  async function render() {
    const route = parseHash();
    const isNavigation = currentPage !== null;
    const root = document.getElementById("page-root");
    if (!root) return;

    if (currentCleanup) {
      try { currentCleanup(); } catch (error) { /* 清理失败不阻塞渲染 */ }
      currentCleanup = null;
    }
    currentPage = route.name;
    document.body.dataset.page = route.name;

    document.querySelectorAll(".app-nav-link").forEach(function (link) {
      const target = link.getAttribute("data-nav");
      const active = (route.name === target) ||
        (route.name === "lesson" && target === "learn");
      link.classList.toggle("is-active", active);
      if (active) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    });

    root.setAttribute("aria-busy", "true");
    root.innerHTML = "";

    const module = window.PVL_PAGES && window.PVL_PAGES[route.name];
    if (!module || typeof module.render !== "function") {
      root.innerHTML = '<div class="empty-state"><h2>页面不存在</h2>' +
        "<p>这个地址还没有对应的页面。</p>" +
        '<a class="btn btn-primary" href="#/">返回首页</a></div>';
      root.setAttribute("aria-busy", "false");
      return;
    }

    try {
      const result = await module.render(root, route.params);
      if (typeof result === "function") currentCleanup = result;
      document.title = "PhoneVision Lab · " + pageTitle(route.name);
      applyPageHeader(route.name);
    } catch (error) {
      const info = describeError(error);
      root.innerHTML =
        '<div class="banner banner-danger"><strong>页面加载失败</strong>' +
        "<p>" + escapeHtml(info.message) + "</p>" +
        (info.hint ? "<p>" + escapeHtml(info.hint) + "</p>" : "") +
        '<button class="btn btn-secondary" type="button" onclick="location.reload()">重新加载</button></div>';
    }
    root.setAttribute("aria-busy", "false");
    const main = document.getElementById("main-content");
    if (isNavigation && main && main.focus) main.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }

  function pageTitle(name) {
    const found = routes.find(function (route) { return route.page === name; });
    return found ? found.title : "页面";
  }

  // 每页的眉题与副标题（顶栏显示，让用户随时知道"现在在哪一步"）
  const PAGE_HEADERS = {
    opensource: { eyebrow: "", title: "开源学习路线", desc: "沿着图像处理、训练、部署和硬件联动读源码" },
    home: { eyebrow: "", title: "学习工作台",
            desc: "" },
    learn: { eyebrow: "", title: "学习中心",
             desc: "八课走完视觉 AI 全流程，不需要硬件也能学" },
    lesson: { eyebrow: "", title: "课程详情",
              desc: "读完一课，做一步实验" },
    progress: { eyebrow: "", title: "学习进度",
                desc: "进度保存在本机浏览器中" },
    lab: { eyebrow: "实践第 1 步", title: "视觉实验台",
           desc: "连接旧手机，看实时画面，试五种视觉处理模式" },
    dataset: { eyebrow: "实践第 2 步", title: "数据集工作区",
               desc: "采集图片、管理类别、体检并划分训练/验证集" },
    train: { eyebrow: "实践第 3 步", title: "模型训练",
             desc: "训练轻量图像分类模型并导出模型包" },
    deploy: { eyebrow: "实践第 4 步", title: "手机部署与推理",
              desc: "把模型包导入手机，本地离线推理" },
    hardware: { eyebrow: "实践第 5 步", title: "硬件联动",
                desc: "用识别结果控制 ESP32 的 LED" },
    performance: { eyebrow: "实践第 6 步", title: "性能分析",
                   desc: "只显示真实采集到的指标，未接入项标为未采集" },
    help: { eyebrow: "", title: "使用帮助",
            desc: "五步走完第一次使用，附常见问题排查" },
    about: { eyebrow: "", title: "关于与能力清单",
             desc: "每个能力的真实状态，不把未验证的说成可用" },
    notfound: { eyebrow: "404", title: "页面不存在", desc: "" },
  };

  function applyPageHeader(name) {
    const info = PAGE_HEADERS[name] || PAGE_HEADERS.home;
    const eyebrow = document.getElementById("page-eyebrow");
    const title = document.getElementById("page-title");
    const desc = document.getElementById("page-desc");
    if (eyebrow) eyebrow.textContent = info.eyebrow;
    if (title) title.textContent = info.title;
    if (desc) desc.textContent = info.desc;
  }

  // ===================================================================
  // 全局状态（设备连接 + 训练进度）
  // ===================================================================

  let deviceStatus = null;
  let trainStatus = null;
  let statusPollTimer = null;

  function renderDevicePill() {
    const pill = document.getElementById("device-pill");
    const text = document.getElementById("device-pill-text");
    if (!pill || !text) return;
    pill.classList.remove("pill-neutral", "pill-success", "pill-warning",
                          "pill-danger", "pill-info", "pill-live");
    if (!deviceStatus || !deviceStatus.connected) {
      pill.classList.add("pill-neutral");
      text.textContent = "未连接设备";
      pill.title = "尚未连接旧手机：进入实验台填写手机 IP 即可连接";
      return;
    }
    if (deviceStatus.state === "Streaming") {
      pill.classList.add("pill-live");
      text.textContent = "已连接 · " + (deviceStatus.device || "手机");
    } else if (deviceStatus.state === "Reconnecting") {
      pill.classList.add("pill-warning");
      text.textContent = "重连中 · " + (deviceStatus.host || "");
    } else if (deviceStatus.state === "Error") {
      pill.classList.add("pill-danger");
      text.textContent = "连接错误";
    } else {
      pill.classList.add("pill-warning");
      text.textContent = deviceStatus.state_label || deviceStatus.state;
    }
  }

  function renderTrainPill() {
    const pill = document.getElementById("train-pill");
    const text = document.getElementById("train-pill-text");
    if (!pill || !text) return;
    if (!trainStatus || (trainStatus.state !== "running" &&
        trainStatus.state !== "cancelling" && trainStatus.export_state !== "running")) {
      pill.classList.add("is-hidden");
      return;
    }
    pill.classList.remove("is-hidden", "pill-neutral", "pill-info",
                          "pill-warning", "pill-danger");
    if (trainStatus.state === "running" || trainStatus.state === "cancelling") {
      pill.classList.add("pill-info");
      text.textContent = "训练中 " + (trainStatus.percent || 0) + "%";
      pill.title = "点击导航中的“模型训练”查看进度";
    } else {
      pill.classList.add("pill-warning");
      text.textContent = "导出模型中…";
      pill.title = "模型包正在生成";
    }
  }

  async function pollGlobalStatus() {
    try {
      deviceStatus = await api("/api/device/status");
    } catch (error) {
      deviceStatus = null;
    }
    renderDevicePill();
    document.dispatchEvent(new CustomEvent("pvl:device-status", { detail: deviceStatus }));
    try {
      trainStatus = await api("/api/train/status");
    } catch (error) {
      trainStatus = null;
    }
    renderTrainPill();
  }

  // ===================================================================
  // 启动
  // ===================================================================

  function start() {
    const nav = document.getElementById("app-nav");
    const navToggle = document.getElementById("nav-toggle");
    function closeNav() {
      if (nav) nav.classList.remove("is-open");
      if (navToggle) {
        navToggle.setAttribute("aria-expanded", "false");
        navToggle.setAttribute("aria-label", "展开导航");
      }
    }
    if (navToggle && nav) navToggle.addEventListener("click", function () {
      const open = nav.classList.toggle("is-open");
      navToggle.setAttribute("aria-expanded", String(open));
      navToggle.setAttribute("aria-label", open ? "收起导航" : "展开导航");
    });
    window.addEventListener("hashchange", closeNav);
    if (nav) nav.addEventListener("click", function (event) {
      if (event.target.closest(".app-nav-link")) closeNav();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && nav && nav.classList.contains("is-open")) {
        closeNav();
        if (navToggle) navToggle.focus();
      }
    });
    const skipLink = document.querySelector('a[href="#main-content"]');
    if (skipLink) skipLink.addEventListener("click", function (event) {
      event.preventDefault();
      const main = document.getElementById("main-content");
      if (main) {
        main.focus({ preventScroll: true });
        main.scrollIntoView({ block: "start", behavior: "auto" });
      }
    });
    window.addEventListener("hashchange", render);
    pollGlobalStatus();
    statusPollTimer = setInterval(pollGlobalStatus, 3000);
    render();

    // 记录最近访问的实验（学习进度页使用）
    window.addEventListener("hashchange", function () {
      const route = parseHash();
      if (["lab", "dataset", "train", "deploy", "hardware", "performance"]
          .includes(route.name)) {
        const entry = { page: route.name, at: new Date().toISOString() };
        store.lastVisited = [entry].concat(
          store.lastVisited.filter(function (item) { return item.page !== route.name; })
        ).slice(0, 8);
        saveStore();
      }
    });
  }

  // ===================================================================
  // 导出给页面模块
  // ===================================================================

  window.PVL = {
    api: api,
    store: store,
    saveStore: saveStore,
    escapeHtml: escapeHtml,
    metricValue: metricValue,
    formatTime: formatTime,
    el: el,
    toast: toast,
    describeError: describeError,
    render: render,
    getDeviceStatus: function () { return deviceStatus; },
    getTrainStatus: function () { return trainStatus; },
    refreshGlobalStatus: pollGlobalStatus,
    courses: function () {
      return (window.PVL_COURSES && window.PVL_COURSES) || {};
    },
    courseMap: function () {
      return (window.PVL_COURSE_MAP) || {};
    },
    lessonOrder: function () {
      return (window.PVL_LESSON_ORDER) || [];
    },
    isLessonComplete: function (id) {
      return store.completedLessons.includes(id);
    },
    markLessonComplete: function (id, done) {
      const index = store.completedLessons.indexOf(id);
      if (done && index === -1) {
        store.completedLessons.push(id);
      } else if (!done && index !== -1) {
        store.completedLessons.splice(index, 1);
      }
      saveStore();
    },
  };

  window.PVL_PAGES = window.PVL_PAGES || {};

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
