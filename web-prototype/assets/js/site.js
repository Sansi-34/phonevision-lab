/* PhoneVision Lab · 站点脚本
   纯原生 JS，无构建、无依赖。所有状态仅存在浏览器 localStorage。
   ------------------------------------------------------------------ */
(function () {
  "use strict";

  /* ---------- 本地学习进度（真实、可清空，不预置任何完成记录） ---------- */
  var KEY = "pvl.progress.v1";

  function read() {
    try {
      var raw = localStorage.getItem(KEY);
      var data = raw ? JSON.parse(raw) : null;
      if (!data || typeof data !== "object") throw 0;
      return {
        done: Array.isArray(data.done) ? data.done : [],
        last: typeof data.last === "string" ? data.last : "",
      };
    } catch (e) {
      return { done: [], last: "" };
    }
  }

  function write(data) {
    try { localStorage.setItem(KEY, JSON.stringify(data)); } catch (e) { /* 隐身模式静默失败 */ }
  }

  var PVL = {
    progress: {
      get: read,
      isDone: function (id) { return read().done.indexOf(id) !== -1; },
      mark: function (id) {
        var d = read();
        if (d.done.indexOf(id) === -1) d.done.push(id);
        d.last = id;
        write(d);
        document.dispatchEvent(new CustomEvent("pvl:progress"));
        return d;
      },
      unmark: function (id) {
        var d = read();
        d.done = d.done.filter(function (x) { return x !== id; });
        write(d);
        document.dispatchEvent(new CustomEvent("pvl:progress"));
        return d;
      },
      toggle: function (id) { return PVL.progress.isDone(id) ? PVL.progress.unmark(id) : PVL.progress.mark(id); },
      count: function () { return read().done.length; },
      clear: function () { write({ done: [], last: "" }); document.dispatchEvent(new CustomEvent("pvl:progress")); },
    },
    toast: function (text) {
      var el = document.querySelector("[data-toast]");
      if (!el) {
        el = document.createElement("div");
        el.setAttribute("data-toast", "");
        el.style.cssText =
          "position:fixed;left:50%;bottom:28px;transform:translateX(-50%);" +
          "background:#14203A;color:#FBF8F2;padding:10px 18px;border-radius:999px;" +
          "font-size:13px;z-index:120;box-shadow:0 12px 32px -12px rgba(20,32,58,.4);" +
          "opacity:0;transition:opacity .2s ease;pointer-events:none;max-width:80vw;";
        document.body.appendChild(el);
      }
      el.textContent = text;
      el.style.opacity = "1";
      clearTimeout(el._t);
      el._t = setTimeout(function () { el.style.opacity = "0"; }, 2600);
    },
  };
  window.PVL = PVL;

  /* ---------- 导航高亮 ---------- */
  function initNav() {
    var page = document.body.getAttribute("data-page");
    if (!page) return;
    document.querySelectorAll("[data-nav]").forEach(function (a) {
      if (a.getAttribute("data-nav") === page) a.setAttribute("aria-current", "page");
    });
  }

  /* ---------- 弹窗 ---------- */
  var lastFocus = null;

  function openModal(id) {
    var m = document.getElementById(id);
    if (!m) return;
    lastFocus = document.activeElement;
    m.setAttribute("data-open", "true");
    document.body.style.overflow = "hidden";
    var focusable = m.querySelector("input, button, [href]");
    if (focusable) setTimeout(function () { focusable.focus(); }, 30);
  }

  function closeModal(m) {
    if (!m) return;
    m.setAttribute("data-open", "false");
    document.body.style.overflow = "";
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  function initModals() {
    document.addEventListener("click", function (e) {
      var open = e.target.closest("[data-open-modal]");
      if (open) { e.preventDefault(); openModal(open.getAttribute("data-open-modal")); return; }

      var close = e.target.closest("[data-close-modal]");
      if (close) { e.preventDefault(); closeModal(close.closest(".modal")); return; }

      if (e.target.classList && e.target.classList.contains("modal")) closeModal(e.target);
    });

    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      var m = document.querySelector('.modal[data-open="true"]');
      if (m) closeModal(m);
    });
  }

  /* ---------- 连接手机（原型：不发起任何真实请求） ---------- */
  function initConnect() {
    var form = document.querySelector("[data-connect-form]");
    if (!form) return;
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var host = (form.querySelector('[name="host"]') || {}).value || "";
      var port = (form.querySelector('[name="port"]') || {}).value || "8080";
      var out = form.querySelector("[data-connect-result]");
      if (!host.trim()) {
        if (out) {
          out.hidden = false;
          out.className = "field__error";
          out.textContent = "请输入手机屏幕上显示的 IP 地址。";
        }
        return;
      }
      if (!out) return;
      out.hidden = false;
      out.className = "callout callout--warn u-mt4";
      out.innerHTML =
        '<svg class="callout__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><circle cx="12" cy="16.4" r=".8" fill="currentColor"/></svg>' +
        '<div><div class="callout__title">这是交互原型，不会真的连接设备</div>' +
        "地址 " + host.replace(/[<>&]/g, "") + ":" + port.replace(/[<>&]/g, "") +
        " 已记录在表单里，但原型没有网络层。真实连接由桌面客户端经局域网 /ping 校验后建立。" +
        "你可以继续浏览，或先去实验台看示意画面。</div>";
      return;
    });
  }

  /* ---------- 学习中心的筛选 ---------- */
  function initFilters() {
    var chips = document.querySelectorAll("[data-filter]");
    if (!chips.length) return;

    chips.forEach(function (chip) {
      chip.addEventListener("click", function () {
        chips.forEach(function (c) { c.setAttribute("aria-pressed", String(c === chip)); });
        var want = chip.getAttribute("data-filter");
        applyFilter(want);
      });
    });

    function applyFilter(want) {
      var chapters = document.querySelectorAll("[data-chapter]");
      chapters.forEach(function (ch) {
        var visible = 0;
        ch.querySelectorAll("[data-course]").forEach(function (row) {
          var type = row.getAttribute("data-course-type");
          var done = row.getAttribute("data-done") === "true";
          var show =
            want === "all" ||
            (want === "know" && type === "know") ||
            (want === "lab" && type === "lab") ||
            (want === "todo" && !done);
          row.hidden = !show;
          if (show) visible++;
        });
        ch.hidden = visible === 0;
      });
    }
  }

  /* ---------- 进度渲染 ---------- */
  function renderProgress() {
    var data = read();
    var n = data.done.length;

    document.querySelectorAll("[data-progress-count]").forEach(function (el) { el.textContent = n; });

    /* "首次使用 · 还没有记录" 只在真的没有进度时出现 */
    document.querySelectorAll("[data-progress-empty]").forEach(function (el) {
      el.hidden = n > 0;
    });

    document.querySelectorAll("[data-progress-bar]").forEach(function (el) {
      var total = parseInt(el.getAttribute("data-progress-total") || "24", 10);
      el.style.width = Math.min(100, Math.round((n / total) * 100)) + "%";
    });
    document.querySelectorAll("[data-progress-percent]").forEach(function (el) {
      var total = parseInt(el.getAttribute("data-progress-total") || "24", 10);
      el.textContent = Math.round((n / total) * 100) + "%";
    });

    document.querySelectorAll("[data-course]").forEach(function (row) {
      var id = row.getAttribute("data-course");
      var done = data.done.indexOf(id) !== -1;
      row.setAttribute("data-done", String(done));
      var mark = row.querySelector("[data-course-state]");
      if (mark) {
        mark.textContent = done ? "已完成" : "未开始";
        mark.className = done ? "tag tag--ok" : "tag";
        mark.hidden = false;
      }
    });

    document.querySelectorAll("[data-course-progress]").forEach(function (el) {
      var ids = (el.getAttribute("data-course-progress") || "").split(",").filter(Boolean);
      var done = ids.filter(function (id) { return data.done.indexOf(id) !== -1; }).length;
      el.textContent = done + " / " + ids.length;
    });
  }

  /* ---------- 课程完成按钮 ---------- */
  function initLesson() {
    var btn = document.querySelector("[data-mark-complete]");
    if (!btn) return;
    var id = btn.getAttribute("data-mark-complete");

    function paint() {
      var done = PVL.progress.isDone(id);
      btn.textContent = done ? "已标记完成 · 点击取消" : "标记本课完成";
      btn.classList.toggle("btn--primary", !done);
      btn.classList.toggle("btn--ghost", done);
      btn.setAttribute("aria-pressed", String(done));
    }

    btn.addEventListener("click", function () {
      PVL.progress.toggle(id);
      paint();
      PVL.toast(PVL.progress.isDone(id) ? "已记录到本机学习进度" : "已取消完成标记");
    });
    paint();
  }

  /* ---------- 通用 ---------- */
  function initYear() {
    document.querySelectorAll("[data-year]").forEach(function (el) {
      el.textContent = new Date().getFullYear();
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initNav();
    initModals();
    initConnect();
    initFilters();
    initLesson();
    initYear();
    renderProgress();
  });
  document.addEventListener("pvl:progress", renderProgress);
})();
