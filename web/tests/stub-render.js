/**
 * 前端契约测试用的 Node 桩脚本（由 test_frontend_contract.py 调用）。
 *
 * 用法：node stub-render.js <页面文件名>  例如 node stub-render.js home.js
 * 输出：最后一行 RESULTS:[{page,ok,error}, ...]
 *
 * 为什么用独立文件而不是 Python 字符串内嵌：
 *   - 桩里要写大量 JS（DOM 假节点、PVL 内核假实现），内嵌在 Python 三引号里
 *     容易被引号/反斜杠转义搞坏，改起来也难读；
 *   - 独立文件可以直接用 node --check 自检，也能单独 `node stub-render.js home.js` 调试。
 *
 * 桩的边界（诚实说明）：
 *   - 这是"最小 DOM 桩"，只保证页面模块能加载、注册、跑完一次 render 不抛异常；
 *   - 它不验证真实渲染结果、不验证浏览器行为、不联网；
 *   - 真正的浏览器联调由开发者在本地完成。
 */
"use strict";

const path = require("path");

// ---------------------------------------------------------------- DOM 桩
// querySelector/getElementById 返回一个新的假节点而不是 null：
// 真实浏览器里页面刚渲染完，这些元素是存在的。返回 null 会让页面在
// "查询刚创建的子元素"时崩溃，那不是被测代码的缺陷，而是桩不够真实。
function makeNode() {
  const node = {
    children: [],
    style: {},
    dataset: {},
    attributes: {},
    classList: {
      add() {}, remove() {}, toggle() {}, contains() { return false; },
    },
    setAttribute(k, v) { this.attributes[k] = v; },
    getAttribute(k) { return this.attributes[k] || null; },
    removeAttribute(k) { delete this.attributes[k]; },
    appendChild(c) { this.children.push(c); return c; },
    append(...cs) { cs.forEach((c) => this.children.push(c)); },
    remove() {}, focus() {}, click() {}, blur() {}, submit() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
    // 关键：查询子元素也返回假节点，让页面代码能继续跑完渲染
    querySelector() { return makeNode(); },
    querySelectorAll() { return []; },
    closest() { return makeNode(); },
    matches() { return false; },
    insertAdjacentHTML() {},
    getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0 }; },
    scrollTop: 0, scrollHeight: 0, scrollIntoView() {},
    set innerHTML(v) { this._h = String(v); },
    get innerHTML() { return this._h || ""; },
    set textContent(v) { this._t = String(v); },
    get textContent() { return this._t || ""; },
    set value(v) { this._v = String(v); },
    get value() { return this._v || ""; },
    set checked(v) { this._c = Boolean(v); },
    get checked() { return Boolean(this._c); },
    set disabled(v) { this._d = Boolean(v); },
    get disabled() { return Boolean(this._d); },
  };
  return node;
}

global.window = global;
global.document = {
  readyState: "complete",
  createElement() { return makeNode(); },
  createDocumentFragment() { return makeNode(); },
  createTextNode() { return makeNode(); },
  getElementById() { return makeNode(); },
  querySelector() { return makeNode(); },
  querySelectorAll() { return []; },
  addEventListener() {},
  removeEventListener() {},
  body: makeNode(),
  documentElement: makeNode(),
};
global.localStorage = {
  getItem() { return null; },
  setItem() {},
  removeItem() {},
  clear() {},
};
global.location = { hash: "#/", pathname: "/", search: "", href: "http://localhost/" };
// Node 21+ 内置了只读的 global.navigator，直接赋值会抛 TypeError；用 defineProperty
try {
  Object.defineProperty(global, "navigator", {
    value: { userAgent: "node-stub", language: "zh-CN" },
    configurable: true, writable: true,
  });
} catch (e) {
  // 某些版本下 navigator 不可配置：页面代码基本不读它，忽略即可
}
global.history = { pushState() {}, replaceState() {} };
global.fetch = function () {
  return Promise.reject(Object.assign(new Error("stub: no network"),
    { code: "network_error" }));
};
global.requestAnimationFrame = function (fn) { return setTimeout(fn, 0); };
// 打桩前先保存 Node 原生定时器：页面代码看到的是"立即返回 0"的假定时器，
// 而测试自身需要一个真实的兜底定时器（render 若遗留未决 Promise 时强制收尾）。
const REAL_SET_TIMEOUT = global.setTimeout;
const REAL_CLEAR_TIMEOUT = global.clearTimeout;

global.setInterval = function () { return 0; };
global.clearInterval = function () {};
global.setTimeout = function () { return 0; };
global.clearTimeout = function () {};
global.XMLHttpRequest = function () {
  return { open() {}, send() {}, setRequestHeader() {}, readyState: 0 };
};
global.confirm = function () { return false; };
global.alert = function () {};
global.prompt = function () { return null; };

// ---------------------------------------------------------------- PVL 内核桩
// 接口与 web/static/app.js 暴露的 window.PVL 一致。
const emptyStore = {
  completedLessons: [], lastVisited: [], language: "zh-CN",
  lastPhoneAddress: "", lastControllerAddress: "", pipelineMarks: {},
};

window.PVL = {
  api() { return Promise.reject(new Error("stub: api not available")); },
  store: emptyStore,
  saveStore() {},
  escapeHtml(s) { return String(s === undefined || s === null ? "" : s); },
  metricValue(v, unit, unavailable) {
    if (v === null || v === undefined || v === "") {
      return "— " + (unavailable || "未采集");
    }
    return String(v) + (unit || "");
  },
  formatTime(s) { return "0:00"; },
  el(html) { return makeNode(); },
  toast() {},
  describeError(e) {
    return { code: (e && e.code) || "unknown",
             message: (e && e.message) || String(e), hint: "" };
  },
  render() {},
  getDeviceStatus() { return null; },
  getTrainStatus() { return null; },
  refreshGlobalStatus() { return Promise.resolve(); },
  courses() { return window.PVL_COURSES || {}; },
  courseMap() { return window.PVL_COURSE_MAP || {}; },
  lessonOrder() { return window.PVL_LESSON_ORDER || []; },
  isLessonComplete() { return false; },
  markLessonComplete() {},
};
window.PVL_PAGES = window.PVL_PAGES || {};

// ---------------------------------------------------------------- 加载被测模块
// 本文件位于 web/tests/，被测文件位于 web/static/ 与 web/static/pages/
const staticDir = path.join(__dirname, "..", "static");
try {
  require(path.join(staticDir, "courses.js"));
} catch (e) {
  console.log("RESULTS:" + JSON.stringify([{ page: "courses.js", ok: false,
                                             error: String(e && e.message) }]));
  process.exit(0);
}

const target = process.argv[2];
if (!target) {
  console.log("RESULTS:" + JSON.stringify([{ page: "(none)", ok: false,
                                             error: "missing page argument" }]));
  process.exit(0);
}

try {
  require(path.join(staticDir, "pages", target));
} catch (e) {
  console.log("RESULTS:" + JSON.stringify([{ page: target, ok: false,
                                             error: String(e && e.message) }]));
  process.exit(0);
}

// ---------------------------------------------------------------- 驱动渲染
const results = [];
const names = Object.keys(window.PVL_PAGES);

if (names.length === 0) {
  console.log("RESULTS:" + JSON.stringify([{ page: target, ok: false,
                                             error: "no page module registered" }]));
  process.exit(0);
}

let pending = names.length;

function finish() {
  console.log("RESULTS:" + JSON.stringify(results));
  process.exit(0);
}

names.forEach(function (name) {
  const page = window.PVL_PAGES[name];
  if (!page || typeof page.render !== "function") {
    results.push({ page: name, ok: false, error: "no render function" });
    if (--pending === 0) finish();
    return;
  }
  let outcome;
  try {
    outcome = page.render(makeNode(), { id: "c1", path: "/" });
  } catch (e) {
    results.push({ page: name, ok: false, error: String(e && e.message) });
    if (--pending === 0) finish();
    return;
  }
  if (outcome && typeof outcome.then === "function") {
    outcome.then(function () {
      results.push({ page: name, ok: true });
      if (--pending === 0) finish();
    }).catch(function (e) {
      results.push({ page: name, ok: false, error: String(e && e.message) });
      if (--pending === 0) finish();
    });
  } else {
    results.push({ page: name, ok: true });
    if (--pending === 0) finish();
  }
});

// 兜底：render 里若遗留了真实定时器，1 秒后强制结束。
const guard = REAL_SET_TIMEOUT(finish, 1000);
if (guard && typeof guard.unref === "function") guard.unref();
