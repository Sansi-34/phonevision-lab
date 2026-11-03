/*
 * PhoneVision Lab — 宣传页"滚动浮现"动效。
 *
 * 做什么：页面往下滚时，标题、段落、卡片依次淡入并轻微上移，同一组内错峰出现。
 *
 * 为什么这样设计：
 *   - 渐进增强：<html> 上没有 .js-reveal（脚本没跑、浏览器不支持、用户要求减少动效）
 *     时什么都不做，内容默认可见。动效只负责"更好看"，绝不能负责"能不能看到"。
 *   - 一次性：元素浮现后立刻 unobserve，来回滚动不会反复闪，也不会持续占着观察器。
 *   - 错峰用 --reveal-delay：同一组（data-reveal-group）内按 DOM 顺序 70ms 递增，
 *     上限 420ms，避免长列表最后一项等太久。
 *   - 不用 scroll 事件：IntersectionObserver 由浏览器在合成线程判定，滚动更顺滑，
 *     也不会因为高频 scroll 回调掉帧。
 */
(function () {
  'use strict';

  var docEl = document.documentElement;
  // head 里的内联脚本已经决定了是否启用；没启用就直接退出。
  if (!docEl.classList.contains('js-reveal')) return;

  var items = Array.prototype.slice.call(
    document.querySelectorAll('[data-reveal]'));
  if (!items.length) return;

  function show(element) {
    element.classList.add('is-visible');
  }

  // 不支持 IntersectionObserver：直接全部显示，不做动画。
  if (!('IntersectionObserver' in window)) {
    items.forEach(show);
    return;
  }

  // 同组错峰：同一容器内的第 n 个元素延迟 n*70ms（封顶 420ms）。
  items.forEach(function (element) {
    var group = element.closest('[data-reveal-group]');
    if (!group) return;
    var peers = Array.prototype.slice.call(
      group.querySelectorAll('[data-reveal]'));
    var index = peers.indexOf(element);
    if (index > 0) {
      element.style.setProperty(
        '--reveal-delay', Math.min(index * 70, 420) + 'ms');
    }
  });

  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      show(entry.target);
      observer.unobserve(entry.target);
    });
  }, {
    // 元素露出约 12% 且越过视口底部 8% 时才触发：避免刚贴边就闪出来
    threshold: 0.12,
    rootMargin: '0px 0px -8% 0px'
  });

  items.forEach(function (element) {
    observer.observe(element);
  });

  // 兜底：如果 4 秒后仍有元素没浮现（例如浏览器把观察器节流了），
  // 直接把当前视口内的元素显示出来，绝不让内容永久隐藏。
  window.setTimeout(function () {
    items.forEach(function (element) {
      if (element.classList.contains('is-visible')) return;
      var rect = element.getBoundingClientRect();
      if (rect.top < window.innerHeight && rect.bottom > 0) show(element);
    });
  }, 4000);
})();
