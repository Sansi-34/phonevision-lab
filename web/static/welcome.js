/* A local photograph processed in the browser, never presented as live inference. */
(function () {
  'use strict';
  const photo = document.getElementById('photo');
  const canvas = document.getElementById('edges');
  const comparison = document.getElementById('comparison');
  const range = document.getElementById('split');
  const note = document.getElementById('demo-note');
  function render() {
    if (!photo.naturalWidth) return;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    if (!context) return;
    try {
      const w = canvas.width, h = canvas.height;
      context.drawImage(photo, 0, 0, w, h);
      const source = context.getImageData(0, 0, w, h);
      const gray = new Float32Array(w * h);
      for (let i = 0; i < gray.length; i++) {
        gray[i] = source.data[i * 4] * .299 + source.data[i * 4 + 1] * .587 + source.data[i * 4 + 2] * .114;
      }
      const output = context.createImageData(w, h);
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        const i = y * w + x;
        let edge = 0;
        if (x > 0 && x < w - 1 && y > 0 && y < h - 1) {
          const gx = -gray[i-w-1] + gray[i-w+1] - 2*gray[i-1] + 2*gray[i+1] - gray[i+w-1] + gray[i+w+1];
          const gy = -gray[i-w-1] - 2*gray[i-w] - gray[i-w+1] + gray[i+w-1] + 2*gray[i+w] + gray[i+w+1];
          edge = Math.min(220, Math.hypot(gx, gy));
        }
        output.data[i*4] = 23 + edge;
        output.data[i*4+1] = 36 + edge;
        output.data[i*4+2] = 28 + edge;
        output.data[i*4+3] = 255;
      }
      context.putImageData(output, 0, 0);
      canvas.hidden = false;
      document.querySelector('.split-line').hidden = false;
      document.querySelector('.edge-label').hidden = false;
      document.querySelector('.comparison-control').hidden = false;
      note.textContent = '左侧是 Sobel 边缘处理，右侧是原始照片。';
    } catch (_) {
      canvas.hidden = true;
      note.textContent = '边缘预览暂不可用，你仍可查看原图和阅读课程。';
    }
  }
  photo.addEventListener('load', render, { once: true });
  photo.addEventListener('error', function () { note.textContent = '示例照片未能加载，你仍可通过下方入口开始学习。'; });
  if (photo.complete) {
    if (photo.naturalWidth) render();
    else note.textContent = '示例照片未能加载，你仍可通过下方入口开始学习。';
  }
  function updateSplit() {
    comparison.style.setProperty('--split', range.value + '%');
    range.setAttribute('aria-valuetext', '边缘图占 ' + range.value + '%');
  }
  range.addEventListener('input', updateSplit);
  let dragging = false;
  function moveSplit(event) {
    const bounds = comparison.getBoundingClientRect();
    range.value = String(Math.round(Math.max(0, Math.min(100,
      (event.clientX - bounds.left) / bounds.width * 100))));
    updateSplit();
  }
  comparison.addEventListener('pointerdown', function (event) {
    if (canvas.hidden || !event.isPrimary || event.button !== 0) return;
    dragging = true;
    comparison.setPointerCapture(event.pointerId);
    moveSplit(event);
  });
  comparison.addEventListener('pointermove', function (event) {
    if (dragging) moveSplit(event);
  });
  comparison.addEventListener('pointerup', function () { dragging = false; });
  comparison.addEventListener('pointercancel', function () { dragging = false; });
  comparison.addEventListener('lostpointercapture', function () { dragging = false; });
  photo.addEventListener('dragstart', function (event) {
    event.preventDefault();
  });
})();
