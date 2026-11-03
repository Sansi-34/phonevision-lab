/**
 * 读取 courses.js 的结构化摘要（由 test_frontend_contract.py 调用）。
 *
 * 用法：node stub-courses.js
 * 输出：一行 JSON
 *
 * 为什么用独立脚本而不是 node -e 内联字符串：
 *   内联脚本在 Windows + PowerShell 下极易被引号转义搞坏（本项目实际踩过），
 *   独立文件可以用 node --check 自检，也能单独运行调试。
 */
"use strict";

const path = require("path");

global.window = global;

try {
  require(path.join(__dirname, "..", "static", "courses.js"));
} catch (e) {
  console.log(JSON.stringify({ error: String(e && e.message) }));
  process.exit(0);
}

const courses = window.PVL_COURSES || {};
const order = window.PVL_LESSON_ORDER || [];
const map = window.PVL_COURSE_MAP || {};

console.log(JSON.stringify({
  count: Object.keys(courses).length,
  order: order,
  titles: order.map((id) => (courses[id] || {}).title),
  demos: order.map((id) => (courses[id] || {}).demo
                            && courses[id].demo.type),
  goals: order.map((id) => ((courses[id] || {}).goals || []).length),
  sections: order.map((id) => ((courses[id] || {}).sections || []).length),
  checklists: order.map((id) => ((courses[id] || {}).checklist || []).length),
  prereqs: order.map((id) => ((courses[id] || {}).prerequisites || []).length),
  minutes: order.map((id) => (courses[id] || {}).minutes),
  mapMatches: order.every((id) => map[id] === courses[id]),
}));
