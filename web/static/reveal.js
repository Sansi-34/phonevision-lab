/*
 * PhoneVision Lab — 滚动浮现（宣传页 + 工作台各页面共用）。
 *
 * 做什么：页面往下滚时，标题、段落、卡片依次淡入并轻微上移，同一容器内错峰出现。
 *
 * 为什么这样设计：
 *   - 渐进增强：<html> 上没有 .js-reveal（脚本没跑、浏览器不支持、用户要求减少动效）
 *     时什么都不做，内容默认可见。动效只负责"更好看"，绝不能负责"能不能看到"。
 *   - 两种目标来源：
 *       1) 显式：元素带 data-reveal（宣传页用它精确控制每一段）；
 *       2) 自动：工作台页面由 JS 动态渲染，逐页手写属性既啰嗦又容易漏，
 *          因此按结构挑选 —— section / .page-head / 网格的直接子项。
 *   - 一次性：元素浮现后立刻 unobserve，来回滚动不会反复闪，也不持续占观察器。
 *   - 不用 scroll 事件：IntersectionObserver 在合成线程判定，长页面滚动更顺滑。
 *   - reset()：工作台是单页应用，切路由时旧节点被丢弃，必须断开观察器，
 *     否则会持有已移除的 DOM。
 */
(function () {
  'use strict';

  var docEl = document.documentElement;
  var enabled = docEl.classList.contains('js-reveal');
  var observer = null;

  function show(element) {
    element.classList.add('is-visible');
  }

  /** 自动模式下挑选"像区块"的元素：section、页头、网格子项。 */
  function autoTargets(root) {
    var out = [];
    var push = function (element) {
      if (out.indexOf(element) === -1) out.push(element);
    };

    Array.prototype.forEach.call(root.querySelectorAll('section, .page-head'), push);

    // 卡片列表逐张出现，比整块淡入更有节奏
    Array.prototype.forEach.call(root.querySelectorAll('[class$="-grid"]'), function (grid) {
      Array.prototype.forEach.call(grid.children, function (child) {
        // 只挑有实际内容块的子项，避免把空占位也藏起来
        if (child.children.length) push(child);
      });
    });

    return out;
  }

  /** 同一父容器内的目标按顺序错峰，封顶 360ms。 */
  function assignDelays(list) {
    var buckets = [];
    list.forEach(function (element) {
      var bucket = null;
      for (var i = 0; i < buckets.length; i++) {
        if (buckets[i].parent === element.parentNode) { bucket = buckets[i]; break; }
      }
      if (!bucket) {
        bucket = { parent: element.parentNode, items: [] };
        buckets.push(bucket);
      }
      bucket.items.push(element);
    });
    buckets.forEach(function (bucket) {
      bucket.items.forEach(function (element, index) {
        if (index > 0) {
          element.style.setProperty('--reveal-delay', Math.min(index * 70, 360) + 'ms');
        }
      });
    });
  }

  function revealNow(list) {
    list.forEach(show);
  }

  function scan(root) {
    if (!enabled) return;
    var node = root || document;
    var explicit = node.querySelectorAll('[data-reveal]');
    var list;
    if (explicit.length) {
      list = Array.prototype.slice.call(explicit);
    } else {
      // 自动模式下先把 data-reveal 写到元素上：CSS 的隐藏规则只认这个属性，
      // 不写属性就会出现"JS 以为在观察、CSS 根本没隐藏"的假动效。
      list = autoTargets(node);
      list.forEach(function (element) {
        element.setAttribute('data-reveal', '');
      });
    }
    if (!list.length) return;

    // 不支持 IntersectionObserver：直接全部显示，不做动画。
    if (!('IntersectionObserver' in window)) {
      revealNow(list);
      return;
    }

    assignDelays(list);

    if (!observer) {
      observer = new IntersectionObserver(function (entries) {
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
    }

    list.forEach(function (element) {
      if (element.classList.contains('is-visible')) return;
      observer.observe(element);
    });

    // 兜底：观察器被浏览器节流时，4 秒后把视口内的元素直接显示出来，
    // 绝不让内容永久隐藏。
    window.setTimeout(function () {
      list.forEach(function (element) {
        if (element.classList.contains('is-visible')) return;
        var rect = element.getBoundingClientRect();
        if (rect.top < window.innerHeight && rect.bottom > 0) show(element);
      });
    }, 4000);
  }

  /** 切路由时调用：断开观察器，避免持有已移除的节点。 */
  function reset() {
    if (observer) {
      observer.disconnect();
      observer = null;
    }
  }

  window.PVL_REVEAL = { scan: scan, reset: reset };

  // 静态页（宣传页）自己启动；单页应用由 app.js 在每次 render 后调用 scan()。
  function boot() {
    if (!enabled) return;
    // 工作台的 <body data-page="..."> 由 app.js 设置，说明是单页应用，交给它调度。
    if (document.body && document.body.dataset && document.body.dataset.page) return;
    scan(document);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
