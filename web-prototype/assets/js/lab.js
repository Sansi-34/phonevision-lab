/* PhoneVision Lab · 视觉实验台
   纯原生 JS，无依赖。画面由 Canvas 程序化生成，所有处理都在浏览器里
   逐像素完成，没有任何网络请求，也不代表真实设备数据。 */
(function () {
  "use strict";

  var W = 640;
  var H = 480;
  var SW = 320;
  var SH = 240;
  var TICK_MS = 66;
  var MAX_CONTOURS = 20;
  var MONO = '"Cascadia Mono", "Consolas", "SFMono-Regular", monospace';
  var SANS = '"Segoe UI", "Microsoft YaHei UI", "PingFang SC", sans-serif';

  var MODE_ORDER = ["raw", "gray", "canny", "hsv", "contour"];
  var MODES = {
    raw: {
      name: "原始",
      desc: "不改变任何像素：先看清示意场景本身的颜色与位置，再切换到其他模式，比较同一帧被算法改写后的样子。"
    },
    gray: {
      name: "灰度",
      desc: "去掉颜色，只保留亮度。每个像素按 0.299R + 0.587G + 0.114B 加权求和，这是多数视觉流程的第一步。"
    },
    canny: {
      name: "Canny",
      desc: "先计算 Sobel 梯度得到边缘强度，再用低、高两个阈值筛选：高于高阈值的是强边缘，只有与强边缘相连的弱边缘才会保留。"
    },
    hsv: {
      name: "HSV",
      desc: "把 RGB 换算成色调、饱和度、明度，按区间保留符合颜色的像素。相比直接比较 RGB，它更不容易被整体明暗变化干扰。"
    },
    contour: {
      name: "轮廓",
      desc: "在 HSV 掩膜上做 4 邻域连通区域搜索，统计面积并过滤过小的噪点，再画出外接矩形、中心点与中心坐标。"
    }
  };

  var state = {
    mode: "raw",
    params: {
      low: 50,
      high: 150,
      hMin: 0,
      hMax: 179,
      sMin: 60,
      sMax: 255,
      vMin: 60,
      vMax: 255,
      minArea: 500
    },
    frame: null,
    count: 0,
    recording: false,
    loopTimer: 0,
    recordTimer: 0,
    processTimer: 0,
    bgCanvas: null,
    noiseCanvas: null,
    vignette: null,
    shadow: null,
    badgeWidth: 0,
    maskBits: null,
    visited: null,
    stack: null
  };

  var dom = {};
  var scene = null;
  var sceneCtx = null;
  var smallCanvas = null;
  var smallCtx = null;
  var buffers = {};

  function each(list, fn) {
    Array.prototype.forEach.call(list || [], fn);
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function now() {
    return window.performance && typeof window.performance.now === "function"
      ? window.performance.now()
      : Date.now();
  }

  /* ---------- 场景生成 ---------- */

  function roundRectPath(g, x, y, w, h, r) {
    var rr = Math.min(r, w / 2, h / 2);
    g.beginPath();
    g.moveTo(x + rr, y);
    g.lineTo(x + w - rr, y);
    g.arcTo(x + w, y, x + w, y + rr, rr);
    g.lineTo(x + w, y + h - rr);
    g.arcTo(x + w, y + h, x + w - rr, y + h, rr);
    g.lineTo(x + rr, y + h);
    g.arcTo(x, y + h, x, y + h - rr, rr);
    g.lineTo(x, y + rr);
    g.arcTo(x, y, x + rr, y, rr);
    g.closePath();
  }

  function buildBackground() {
    var c = document.createElement("canvas");
    c.width = W;
    c.height = H;
    var g = c.getContext("2d");
    if (!g) return c;

    var surface = g.createLinearGradient(0, 0, 0, H);
    surface.addColorStop(0, "#E9E2D8");
    surface.addColorStop(0.42, "#D8CFC1");
    surface.addColorStop(0.72, "#C4B9A9");
    surface.addColorStop(1, "#B2A797");
    g.fillStyle = surface;
    g.fillRect(0, 0, W, H);

    var light = g.createRadialGradient(150, 10, 20, 150, 10, 380);
    light.addColorStop(0, "rgba(255, 252, 245, 0.48)");
    light.addColorStop(1, "rgba(255, 252, 245, 0)");
    g.fillStyle = light;
    g.fillRect(0, 0, W, 260);

    g.strokeStyle = "rgba(112, 92, 67, 0.10)";
    g.lineWidth = 1;
    for (var i = 0; i < 16; i++) {
      var y = 218 + i * 17 + Math.sin(i * 1.9) * 3;
      g.beginPath();
      g.moveTo(0, y);
      g.bezierCurveTo(160, y + 4, 300, y - 5, 480, y + 2);
      g.bezierCurveTo(555, y + 6, 600, y - 2, W, y + 1);
      g.stroke();
    }

    g.strokeStyle = "rgba(98, 79, 57, 0.09)";
    for (var k = 0; k < 3; k++) {
      g.beginPath();
      g.ellipse(118 + k * 214, 322 + k * 26, 26 + k * 6, 6 + k, 0.06, 0, Math.PI * 2);
      g.stroke();
    }

    return c;
  }

  function buildNoise() {
    var c = document.createElement("canvas");
    c.width = W;
    c.height = H;
    var g = c.getContext("2d");
    if (!g) return c;
    var img = g.createImageData(W, H);
    var d = img.data;
    for (var i = 0; i < d.length; i += 4) {
      var v = 96 + Math.floor(Math.random() * 160);
      d[i] = v;
      d[i + 1] = v;
      d[i + 2] = v;
      d[i + 3] = Math.floor(Math.random() * 18);
    }
    g.putImageData(img, 0, 0);
    return c;
  }

  function buildVignette(g) {
    var grad = g.createRadialGradient(W / 2, H * 0.46, H * 0.22, W / 2, H * 0.5, H * 0.82);
    grad.addColorStop(0, "rgba(10, 14, 21, 0)");
    grad.addColorStop(0.72, "rgba(10, 14, 21, 0.04)");
    grad.addColorStop(1, "rgba(10, 14, 21, 0.24)");
    return grad;
  }

  function buildShadowGradient(g) {
    var grad = g.createRadialGradient(0, 0, 0.06, 0, 0, 1);
    grad.addColorStop(0, "rgba(72, 58, 43, 0.34)");
    grad.addColorStop(0.55, "rgba(72, 58, 43, 0.16)");
    grad.addColorStop(1, "rgba(72, 58, 43, 0)");
    return grad;
  }

  function drawShadow(g, cx, cy, rx, ry, alpha) {
    g.save();
    g.translate(cx, cy);
    g.scale(rx, ry);
    g.globalAlpha = alpha;
    g.fillStyle = state.shadow;
    g.beginPath();
    g.arc(0, 0, 1, 0, Math.PI * 2);
    g.fill();
    g.restore();
  }

  function drawApple(g, cx, cy, r) {
    g.save();

    var grad = g.createRadialGradient(cx - r * 0.34, cy - r * 0.4, r * 0.08, cx, cy, r * 1.3);
    grad.addColorStop(0, "#D65B4C");
    grad.addColorStop(0.42, "#BA3D32");
    grad.addColorStop(0.8, "#982B25");
    grad.addColorStop(1, "#761F1D");
    g.fillStyle = grad;
    g.beginPath();
    g.moveTo(cx, cy - r * 0.8);
    g.bezierCurveTo(cx + r * 0.52, cy - r * 1.06, cx + r * 1.0, cy - r * 0.5, cx + r * 0.94, cy + r * 0.08);
    g.bezierCurveTo(cx + r * 0.88, cy + r * 0.7, cx + r * 0.44, cy + r * 1.0, cx, cy + r * 0.98);
    g.bezierCurveTo(cx - r * 0.44, cy + r * 1.0, cx - r * 0.88, cy + r * 0.7, cx - r * 0.94, cy + r * 0.08);
    g.bezierCurveTo(cx - r * 1.0, cy - r * 0.5, cx - r * 0.52, cy - r * 1.06, cx, cy - r * 0.8);
    g.closePath();
    g.fill();

    g.fillStyle = "rgba(255, 238, 230, 0.22)";
    g.beginPath();
    g.ellipse(cx - r * 0.34, cy - r * 0.4, r * 0.24, r * 0.13, -0.55, 0, Math.PI * 2);
    g.fill();

    g.strokeStyle = "#5C4128";
    g.lineWidth = Math.max(3, r * 0.055);
    g.lineCap = "round";
    g.beginPath();
    g.moveTo(cx + 1, cy - r * 0.78);
    g.quadraticCurveTo(cx + 2, cy - r * 0.98, cx + 7, cy - r * 1.08);
    g.stroke();

    g.fillStyle = "#4B7F4B";
    g.beginPath();
    g.ellipse(cx + r * 0.22, cy - r * 0.96, r * 0.2, r * 0.085, -0.5, 0, Math.PI * 2);
    g.fill();

    g.restore();
  }

  function drawBox(g, x, y, w, h) {
    g.save();
    var ox = 18;
    var oy = 16;

    g.fillStyle = "#5B7CC9";
    g.beginPath();
    g.moveTo(x, y);
    g.lineTo(x + ox, y - oy);
    g.lineTo(x + w + ox, y - oy);
    g.lineTo(x + w, y);
    g.closePath();
    g.fill();

    g.fillStyle = "#2E4987";
    g.beginPath();
    g.moveTo(x + w, y);
    g.lineTo(x + w + ox, y - oy);
    g.lineTo(x + w + ox, y + h - oy);
    g.lineTo(x + w, y + h);
    g.closePath();
    g.fill();

    var grad = g.createLinearGradient(x, y, x, y + h);
    grad.addColorStop(0, "#4066BC");
    grad.addColorStop(1, "#31509A");
    g.fillStyle = grad;
    g.fillRect(x, y, w, h);

    g.strokeStyle = "rgba(24, 38, 70, 0.25)";
    g.lineWidth = 1.5;
    g.strokeRect(x + 0.75, y + 0.75, w - 1.5, h - 1.5);

    g.fillStyle = "rgba(255, 255, 255, 0.18)";
    g.fillRect(x + 18, y + 22, w - 36, 8);
    g.fillStyle = "rgba(255, 255, 255, 0.10)";
    g.fillRect(x + 18, y + 38, w - 58, 5);

    g.restore();
  }

  function drawGreenBlock(g, x, y, size) {
    g.save();
    var grad = g.createLinearGradient(x, y, x + size, y + size);
    grad.addColorStop(0, "#5A9A6C");
    grad.addColorStop(1, "#3F7A52");
    g.fillStyle = grad;
    roundRectPath(g, x, y, size, size, 4);
    g.fill();
    g.strokeStyle = "rgba(28, 64, 40, 0.28)";
    g.lineWidth = 1.5;
    g.stroke();
    g.fillStyle = "rgba(255, 255, 255, 0.16)";
    g.fillRect(x + 8, y + 8, size - 16, 4);
    g.restore();
  }

  function drawScene(t) {
    var g = sceneCtx;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.globalAlpha = 1;
    g.globalCompositeOperation = "source-over";
    g.imageSmoothingEnabled = true;
    g.drawImage(state.bgCanvas, 0, 0);

    var ax = 252 + Math.sin(t * 0.0016) * 3;
    var ay = 300 + Math.cos(t * 0.0013) * 2.5;
    var ar = 74 + Math.sin(t * 0.0011) * 2.2;

    var bx = 458 + Math.sin(t * 0.0012 + 2.1) * 3;
    var by = 306 + Math.cos(t * 0.0017 + 1.3) * 2;

    var gx = 392 + Math.sin(t * 0.0019 + 4.2) * 3;
    var gy = 238 + Math.cos(t * 0.0014 + 3.1) * 2.4;

    drawShadow(g, ax + 10, ay + ar * 0.92, ar * 1.05, ar * 0.26, 0.3);
    drawApple(g, ax, ay, ar);

    drawShadow(g, bx + 76, by + 100, 82, 20, 0.24);
    drawBox(g, bx, by, 132, 104);

    drawShadow(g, gx + 27, gy + 56, 38, 9, 0.22);
    drawGreenBlock(g, gx, gy, 54);

    g.globalAlpha = 0.7;
    g.imageSmoothingEnabled = false;
    g.drawImage(state.noiseCanvas, 0, 0);
    g.imageSmoothingEnabled = true;
    g.globalAlpha = 1;

    g.fillStyle = state.vignette;
    g.fillRect(0, 0, W, H);
  }

  /* ---------- 图像处理 ---------- */

  function process(mode, params) {
    var src = state.frame;
    var ctx = dom.ctx;
    if (!src || !ctx) return false;

    var p = params || state.params;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
    ctx.imageSmoothingEnabled = true;

    if (mode === "gray") {
      ctx.putImageData(toGray(src, getBuffer("gray", W, H)), 0, 0);
    } else if (mode === "canny") {
      renderCanny(src, p);
    } else if (mode === "hsv") {
      ctx.putImageData(buildHsvMask(src, p, false).image, 0, 0);
    } else if (mode === "contour") {
      var mask = buildHsvMask(src, p, true);
      drawContours(mask.image, mask.bits, p.minArea);
    } else {
      ctx.putImageData(src, 0, 0);
    }

    paintBadge(ctx);
    return true;
  }

  function getBuffer(name, width, height) {
    if (!buffers[name]) {
      buffers[name] = dom.ctx.createImageData(width, height);
    }
    return buffers[name];
  }

  function toGray(src, dst) {
    var s = src.data;
    var d = dst.data;
    for (var i = 0; i < s.length; i += 4) {
      var v = (s[i] * 77 + s[i + 1] * 150 + s[i + 2] * 29) >> 8;
      d[i] = v;
      d[i + 1] = v;
      d[i + 2] = v;
      d[i + 3] = 255;
    }
    return dst;
  }

  function buildHsvMask(src, p, needBits) {
    var s = src.data;
    var img = getBuffer("mask", W, H);
    var d = img.data;
    if (!state.maskBits) state.maskBits = new Uint8Array(W * H);
    var bits = state.maskBits;

    var hMin = p.hMin;
    var hMax = p.hMax;
    var sMin = p.sMin;
    var sMax = p.sMax;
    var vMin = p.vMin;
    var vMax = p.vMax;

    for (var i = 0, j = 0; i < s.length; i += 4, j++) {
      var r = s[i];
      var g = s[i + 1];
      var b = s[i + 2];

      var max = r > g ? (r > b ? r : b) : (g > b ? g : b);
      var min = r < g ? (r < b ? r : b) : (g < b ? g : b);
      var delta = max - min;

      var h = 0;
      var sat = max > 0 ? (delta * 255 / max) | 0 : 0;
      var val = max;

      if (delta > 0) {
        if (max === r) h = ((g - b) * 60) / delta;
        else if (max === g) h = ((b - r) * 60) / delta + 120;
        else h = ((r - g) * 60) / delta + 240;
        if (h < 0) h += 360;
        h *= 0.5;
      }

      var hit = h >= hMin && h <= hMax &&
                sat >= sMin && sat <= sMax &&
                val >= vMin && val <= vMax;
      var v = hit ? 255 : 0;
      d[i] = v;
      d[i + 1] = v;
      d[i + 2] = v;
      d[i + 3] = 255;
      if (needBits !== false) bits[j] = hit ? 1 : 0;
    }

    return { image: img, bits: bits };
  }

  function renderCanny(src, p) {
    var s = src.data;
    if (!buffers.smallGray) buffers.smallGray = new Uint8Array(SW * SH);
    if (!buffers.mag) buffers.mag = new Uint16Array(SW * SH);
    if (!buffers.gx) buffers.gx = new Int16Array(SW * SH);
    if (!buffers.gy) buffers.gy = new Int16Array(SW * SH);
    if (!buffers.thin) buffers.thin = new Uint16Array(SW * SH);
    if (!buffers.edges) buffers.edges = new Uint8Array(SW * SH);
    if (!buffers.edgeStack) buffers.edgeStack = new Int32Array(SW * SH);

    var gray = buffers.smallGray;
    var mag = buffers.mag;
    var gxBuf = buffers.gx;
    var gyBuf = buffers.gy;
    var thin = buffers.thin;
    var edges = buffers.edges;
    var stack = buffers.edgeStack;
    var x;
    var y;
    var idx;

    for (y = 0; y < SH; y++) {
      var row = y * 2 * W;
      for (x = 0; x < SW; x++) {
        var si = (row + x * 2) * 4;
        gray[y * SW + x] = (s[si] * 77 + s[si + 1] * 150 + s[si + 2] * 29) >> 8;
      }
    }

    for (y = 0; y < SH; y++) {
      for (x = 0; x < SW; x++) {
        idx = y * SW + x;
        if (x === 0 || y === 0 || x === SW - 1 || y === SH - 1) {
          mag[idx] = 0;
          gxBuf[idx] = 0;
          gyBuf[idx] = 0;
          continue;
        }
        var tl = gray[idx - SW - 1];
        var tc = gray[idx - SW];
        var tr = gray[idx - SW + 1];
        var ml = gray[idx - 1];
        var mr = gray[idx + 1];
        var bl = gray[idx + SW - 1];
        var bc = gray[idx + SW];
        var br = gray[idx + SW + 1];

        var gx = (tr + 2 * mr + br) - (tl + 2 * ml + bl);
        var gy = (bl + 2 * bc + br) - (tl + 2 * tc + tr);
        var m = Math.abs(gx) + Math.abs(gy);
        gxBuf[idx] = gx;
        gyBuf[idx] = gy;
        mag[idx] = m > 1020 ? 1020 : m;
      }
    }

    /* 非极大值抑制：沿梯度方向只保留局部最大值，得到更细的边缘。 */
    for (y = 0; y < SH; y++) {
      for (x = 0; x < SW; x++) {
        idx = y * SW + x;
        var v = mag[idx];
        if (v === 0 || x === 0 || y === 0 || x === SW - 1 || y === SH - 1) {
          thin[idx] = 0;
          continue;
        }
        var ax = Math.abs(gxBuf[idx]);
        var ay = Math.abs(gyBuf[idx]);
        var keep;
        if (ay * 2.414 <= ax) {
          keep = v >= mag[idx - 1] && v >= mag[idx + 1];
        } else if (ax * 2.414 <= ay) {
          keep = v >= mag[idx - SW] && v >= mag[idx + SW];
        } else if ((gxBuf[idx] > 0) === (gyBuf[idx] > 0)) {
          keep = v >= mag[idx - SW - 1] && v >= mag[idx + SW + 1];
        } else {
          keep = v >= mag[idx - SW + 1] && v >= mag[idx + SW - 1];
        }
        thin[idx] = keep ? v : 0;
      }
    }

    var lo = Math.min(p.low, p.high);
    var hi = Math.max(p.low, p.high);
    var top = 0;
    edges.fill(0);

    for (idx = 0; idx < thin.length; idx++) {
      if (thin[idx] > 0 && thin[idx] >= hi) {
        edges[idx] = 2;
        stack[top++] = idx;
      } else if (thin[idx] > 0 && thin[idx] >= lo) {
        edges[idx] = 1;
      }
    }

    while (top > 0) {
      var cur = stack[--top];
      x = cur % SW;
      y = (cur - x) / SW;
      for (var dy = -1; dy <= 1; dy++) {
        var ny = y + dy;
        if (ny < 0 || ny >= SH) continue;
        for (var dx = -1; dx <= 1; dx++) {
          if (dx === 0 && dy === 0) continue;
          var nx = x + dx;
          if (nx < 0 || nx >= SW) continue;
          var n = ny * SW + nx;
          if (edges[n] === 1) {
            edges[n] = 2;
            stack[top++] = n;
          }
        }
      }
    }

    var out = buffers.edgeImage;
    if (!out) {
      out = smallCtx.createImageData(SW, SH);
      buffers.edgeImage = out;
    }
    var d = out.data;
    for (idx = 0; idx < edges.length; idx++) {
      var v = edges[idx] === 2 ? 255 : 0;
      var o = idx * 4;
      d[o] = v;
      d[o + 1] = v;
      d[o + 2] = v;
      d[o + 3] = 255;
    }

    smallCtx.putImageData(out, 0, 0);

    var ctx = dom.ctx;
    ctx.clearRect(0, 0, W, H);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(smallCanvas, 0, 0, W, H);
    ctx.imageSmoothingEnabled = true;
  }

  function drawContours(maskImage, bits, minArea) {
    var ctx = dom.ctx;
    ctx.putImageData(maskImage, 0, 0);

    if (!state.visited) state.visited = new Uint8Array(W * H);
    if (!state.stack) state.stack = new Int32Array(W * H);
    var visited = state.visited;
    var stack = state.stack;
    visited.fill(0);

    var comps = [];
    var total = W * H;

    for (var start = 0; start < total; start++) {
      if (!bits[start] || visited[start]) continue;

      var top = 0;
      stack[top++] = start;
      visited[start] = 1;

      var area = 0;
      var minX = W;
      var minY = H;
      var maxX = 0;
      var maxY = 0;

      while (top > 0) {
        var cur = stack[--top];
        var x = cur % W;
        var y = (cur - x) / W;
        area++;
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;

        if (x > 0) {
          var n1 = cur - 1;
          if (bits[n1] && !visited[n1]) { visited[n1] = 1; stack[top++] = n1; }
        }
        if (x < W - 1) {
          var n2 = cur + 1;
          if (bits[n2] && !visited[n2]) { visited[n2] = 1; stack[top++] = n2; }
        }
        if (y > 0) {
          var n3 = cur - W;
          if (bits[n3] && !visited[n3]) { visited[n3] = 1; stack[top++] = n3; }
        }
        if (y < H - 1) {
          var n4 = cur + W;
          if (bits[n4] && !visited[n4]) { visited[n4] = 1; stack[top++] = n4; }
        }
      }

      if (area >= minArea) {
        comps.push({
          area: area,
          x: minX,
          y: minY,
          w: maxX - minX + 1,
          h: maxY - minY + 1,
          cx: (minX + maxX) / 2,
          cy: (minY + maxY) / 2
        });
      }
    }

    comps.sort(function (a, b) { return b.area - a.area; });
    if (comps.length > MAX_CONTOURS) comps = comps.slice(0, MAX_CONTOURS);

    ctx.save();
    ctx.lineJoin = "miter";
    ctx.lineWidth = 2;

    for (var i = 0; i < comps.length; i++) {
      var c = comps[i];

      ctx.strokeStyle = "rgba(47, 91, 255, 0.95)";
      ctx.strokeRect(c.x - 5.5, c.y - 5.5, c.w + 11, c.h + 11);

      ctx.strokeStyle = "rgba(30, 158, 99, 0.95)";
      ctx.strokeRect(c.x + 0.5, c.y + 0.5, Math.max(0, c.w - 1), Math.max(0, c.h - 1));

      ctx.fillStyle = "#DC3B32";
      ctx.beginPath();
      ctx.arc(c.cx, c.cy, 4, 0, Math.PI * 2);
      ctx.fill();

      var label = Math.round(c.cx) + ", " + Math.round(c.cy);
      ctx.font = "600 12px " + MONO;
      var tw = ctx.measureText(label).width;
      var lx = Math.min(Math.max(c.x, 2), W - tw - 16);
      var ly = c.y - 24;
      if (ly < 2) ly = Math.min(c.y + c.h + 6, H - 20);

      roundRectPath(ctx, lx, ly, tw + 12, 18, 4);
      ctx.fillStyle = "rgba(10, 15, 25, 0.74)";
      ctx.fill();

      ctx.fillStyle = "#F2F5FA";
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(label, lx + 6, ly + 9.5);
    }

    ctx.restore();
  }

  function paintBadge(ctx) {
    var text = "示意画面 · 非真实设备";
    ctx.save();
    ctx.font = "600 15px " + SANS;
    if (!state.badgeWidth) state.badgeWidth = ctx.measureText(text).width;

    var padX = 13;
    var bh = 30;
    var bw = state.badgeWidth + padX * 2;
    var x = W - bw - 14;
    var y = H - bh - 14;

    roundRectPath(ctx, x, y, bw, bh, 6);
    ctx.fillStyle = "rgba(9, 13, 21, 0.62)";
    ctx.fill();
    ctx.strokeStyle = "rgba(255, 255, 255, 0.18)";
    ctx.lineWidth = 1;
    ctx.stroke();

    ctx.fillStyle = "rgba(248, 250, 252, 0.92)";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(text, x + padX, y + bh / 2 + 0.5);
    ctx.restore();
  }

  /* ---------- 交互 ---------- */

  function updateModeUI() {
    each(document.querySelectorAll("[data-mode]"), function (btn) {
      btn.setAttribute("aria-pressed", String(btn.getAttribute("data-mode") === state.mode));
    });

    if (dom.modeChip) dom.modeChip.textContent = MODES[state.mode].name;
    if (dom.modeDesc) dom.modeDesc.textContent = MODES[state.mode].desc;

    var withParams = state.mode === "canny" || state.mode === "hsv" || state.mode === "contour";

    each(document.querySelectorAll("[data-param-group]"), function (group) {
      group.hidden = group.getAttribute("data-param-group") !== state.mode;
    });

    if (dom.paramEmpty) dom.paramEmpty.hidden = withParams;

    if (dom.paramHint) {
      if (withParams) {
        dom.paramHint.hidden = true;
      } else {
        dom.paramHint.hidden = false;
        dom.paramHint.textContent = state.mode === "gray"
          ? "灰度固定按亮度加权计算，不提供对比度调整。"
          : "原始模式直接显示画面，不做任何处理。";
      }
    }

    if (dom.canvas) {
      dom.canvas.setAttribute(
        "aria-label",
        "示意摄像头画面：暖灰桌面上有一个红色圆形、一个蓝色矩形和一个绿色方块；当前为" +
          MODES[state.mode].name + "模式。画面由程序生成，不是真实设备。"
      );
    }
  }

  function setMode(mode, silent) {
    if (!MODES[mode]) return;
    state.mode = mode;
    updateModeUI();
    if (!silent) announce("已切换到" + MODES[mode].name + "模式");
    scheduleProcess(0);
  }

  function announce(text) {
    if (dom.announce) dom.announce.textContent = text;
  }

  function syncParam(key, value) {
    each(document.querySelectorAll('input[data-param="' + key + '"]'), function (input) {
      if (parseInt(input.value, 10) !== value) input.value = String(value);
      var row = input.parentNode;
      var out = row ? row.querySelector("output") : null;
      if (out) out.textContent = String(value);
    });
  }

  function scheduleProcess(delay) {
    if (state.processTimer) window.clearTimeout(state.processTimer);
    state.processTimer = window.setTimeout(function () {
      state.processTimer = 0;
      if (!state.frame) return;
      try {
        process(state.mode, state.params);
      } catch (e) {
        /* 单帧失败时保持上一帧，不让整页脚本停止 */
      }
    }, typeof delay === "number" ? delay : 50);
  }

  function updateCount() {
    if (dom.captureNote) {
      dom.captureNote.textContent = "本次已采集 " + state.count + " 张（示意，不会真的写入文件）";
    }
  }

  function toast(text) {
    try {
      if (window.PVL && typeof window.PVL.toast === "function") window.PVL.toast(text);
    } catch (e) {
      /* toast 不可用时忽略 */
    }
  }

  function downloadSnapshot() {
    try {
      var url = dom.canvas.toDataURL("image/png");
      var a = document.createElement("a");
      a.href = url;
      a.download = "pvl-demo-" + state.mode + ".png";
      document.body.appendChild(a);
      a.click();
      a.remove();
      toast("已下载当前示意画面");
    } catch (e) {
      toast("当前浏览器不允许下载示意画面");
    }
  }

  function captureOne() {
    state.count++;
    updateCount();
    toast("已截图（示意，未写入文件）");
    announce("已记录一张示意采集，未写入文件。");
  }

  function startRecording() {
    state.recording = true;
    if (dom.live) {
      dom.live.textContent = "停止采集";
      dom.live.setAttribute("data-recording", "true");
      dom.live.setAttribute("aria-pressed", "true");
    }
    state.recordTimer = window.setInterval(function () {
      if (document.hidden) return;
      state.count++;
      updateCount();
    }, 1000);
    toast("开始连续采集（示意，不会写入文件）");
    announce("连续采集已开始，每秒按示意计数一张，不会写入文件。");
  }

  function stopRecording(withSummary) {
    if (state.recordTimer) {
      window.clearInterval(state.recordTimer);
      state.recordTimer = 0;
    }
    var wasRecording = state.recording;
    state.recording = false;
    if (dom.live) {
      dom.live.textContent = "开始连续采集";
      dom.live.setAttribute("data-recording", "false");
      dom.live.setAttribute("aria-pressed", "false");
    }
    if (wasRecording && withSummary) {
      toast("已停止：本次共采集 " + state.count + " 张（示意，未写入文件）");
    }
    announce("连续采集已停止。");
  }

  function toggleRecording() {
    if (state.recording) stopRecording(true);
    else startRecording();
  }

  function bindEvents() {
    each(document.querySelectorAll("[data-mode]"), function (btn) {
      btn.addEventListener("click", function () {
        setMode(btn.getAttribute("data-mode"));
      });
    });

    each(document.querySelectorAll('input[type="range"][data-param]'), function (input) {
      var key = input.getAttribute("data-param");
      var initial = parseInt(input.value, 10);
      if (!isNaN(initial)) state.params[key] = initial;

      input.addEventListener("input", function () {
        var value = parseInt(input.value, 10);
        if (isNaN(value)) value = 0;
        state.params[key] = value;
        syncParam(key, value);
        scheduleProcess(50);
      });
    });

    var snap = byId("snapshot-btn");
    if (snap) snap.addEventListener("click", downloadSnapshot);

    var one = byId("capture-one");
    if (one) one.addEventListener("click", captureOne);

    if (dom.live) dom.live.addEventListener("click", toggleRecording);

    document.addEventListener("keydown", function (e) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (document.querySelector('.modal[data-open="true"]')) return;
      var target = e.target;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" ||
                     target.tagName === "SELECT" || target.isContentEditable)) return;
      var idx = ["1", "2", "3", "4", "5"].indexOf(e.key);
      if (idx === -1) return;
      e.preventDefault();
      setMode(MODE_ORDER[idx]);
    });
  }

  function cleanup() {
    if (state.loopTimer) {
      window.clearInterval(state.loopTimer);
      state.loopTimer = 0;
    }
    if (state.recordTimer) {
      window.clearInterval(state.recordTimer);
      state.recordTimer = 0;
    }
    if (state.processTimer) {
      window.clearTimeout(state.processTimer);
      state.processTimer = 0;
    }
  }

  function tick() {
    if (document.hidden) return;
    try {
      drawScene(now());
      state.frame = sceneCtx.getImageData(0, 0, W, H);
      process(state.mode, state.params);
    } catch (e) {
      try {
        dom.ctx.drawImage(scene, 0, 0);
      } catch (e2) {
        /* 保持空白，不抛错 */
      }
    }
  }

  function init() {
    var canvas = byId("lab-canvas");
    if (!canvas) return;

    var ctx = null;
    try {
      ctx = canvas.getContext("2d", { willReadFrequently: true });
    } catch (e) {
      ctx = null;
    }
    if (!ctx) {
      try { ctx = canvas.getContext("2d"); } catch (e2) { return; }
    }
    if (!ctx) return;

    scene = document.createElement("canvas");
    scene.width = W;
    scene.height = H;
    try {
      sceneCtx = scene.getContext("2d", { willReadFrequently: true }) || scene.getContext("2d");
    } catch (e) {
      try { sceneCtx = scene.getContext("2d"); } catch (e2) { sceneCtx = null; }
    }
    if (!sceneCtx) return;

    smallCanvas = document.createElement("canvas");
    smallCanvas.width = SW;
    smallCanvas.height = SH;
    try { smallCtx = smallCanvas.getContext("2d"); } catch (e) { smallCtx = null; }
    if (!smallCtx) return;

    dom.canvas = canvas;
    dom.ctx = ctx;
    dom.modeChip = byId("mode-chip");
    dom.modeDesc = byId("mode-desc");
    dom.paramEmpty = document.querySelector("[data-param-empty]");
    dom.paramHint = document.querySelector("[data-param-hint]");
    dom.captureNote = byId("capture-note");
    dom.announce = byId("lab-announce");
    dom.live = byId("capture-live");

    state.bgCanvas = buildBackground();
    state.noiseCanvas = buildNoise();
    state.vignette = buildVignette(sceneCtx);
    state.shadow = buildShadowGradient(sceneCtx);

    bindEvents();
    updateModeUI();
    updateCount();

    tick();
    state.loopTimer = window.setInterval(tick, TICK_MS);

    window.addEventListener("pagehide", function (e) {
      if (!e.persisted) cleanup();
    });

    window.PVLLab = {
      process: function (mode, params) {
        try { return process(mode || state.mode, params || state.params); }
        catch (e) { return false; }
      },
      setMode: function (mode) { setMode(mode, true); },
      getMode: function () { return state.mode; },
      getParams: function () {
        var copy = {};
        for (var key in state.params) {
          if (Object.prototype.hasOwnProperty.call(state.params, key)) copy[key] = state.params[key];
        }
        return copy;
      },
      getCaptureCount: function () { return state.count; },
      canvas: canvas
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
