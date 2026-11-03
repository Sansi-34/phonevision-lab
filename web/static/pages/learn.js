/**
 * PhoneVision Lab Web — 学习中心与课程详情。
 *
 * 课程内容来自 static/courses.js（window.PVL_COURSES），与后端无关，
 * 因此没有旧手机时也能完整阅读。完成状态保存在 localStorage。
 * 每课底部提供"关联实验入口"，跳到对应的实践页面，做到"学一段、做一段"。
 */
window.PVL_PAGES = window.PVL_PAGES || {};

window.PVL_PAGES.learn = {
  render: async function (root) {
    const order = PVL.lessonOrder();
    const courses = PVL.courses();
    const completed = PVL.store.completedLessons || [];
    const doneCount = order.filter(function (id) {
      return completed.includes(id);
    }).length;
    const percent = order.length ? Math.round(doneCount / order.length * 100) : 0;

    root.appendChild(PVL.el(
      '<section class="page-head">' +
        '<h1>学习中心</h1>' +
        '<p class="page-lede">' +
          '八课走完"认识视觉 AI → 连接旧手机 → 采集数据 → 训练模型 → 部署推理 → 硬件联动 → 看懂性能"。' +
          '没有旧手机也能学，课程里的示意图与说明都标明是示意。' +
        '</p>' +
        '<div class="progress" role="progressbar" aria-valuenow="' + percent +
          '" aria-valuemin="0" aria-valuemax="100" aria-label="总体学习进度">' +
          '<div class="progress-bar" style="width:' + percent + '%"></div>' +
        '</div>' +
        '<p class="field-hint">已完成 ' + doneCount + ' / ' + order.length +
          ' 课（' + percent + '%）</p>' +
      '</section>'
    ));

    const grid = PVL.el('<div class="course-grid"></div>');
    order.forEach(function (id, index) {
      const course = courses[id] || {};
      const isDone = completed.includes(id);
      const minutes = course.minutes || 10;
      grid.appendChild(PVL.el(
        '<a class="course-card' + (isDone ? ' is-done' : '') + '" href="#/learn/' + id + '">' +
          '<div class="course-card-head">' +
            '<span class="course-num">第 ' + (index + 1) + ' 课</span>' +
            '<span class="badge ' + (isDone ? 'badge-success' : 'badge-neutral') + '">' +
              (isDone ? '已完成' : '未完成') +
            '</span>' +
          '</div>' +
          '<h3 class="course-title">' + PVL.escapeHtml(course.title || id) + '</h3>' +
          '<p class="course-sub">' + PVL.escapeHtml(course.subtitle || "") + '</p>' +
          '<p class="course-meta">约 ' + minutes + ' 分钟 · ' +
            PVL.escapeHtml(course.level || "入门") + '</p>' +
        '</a>'
      ));
    });
    root.appendChild(grid);

    root.appendChild(PVL.el('<aside class="source-invitation"><div><h2>接着读真实项目的源码</h2><p>跟着 OpenCV、TensorFlow 和 ESP-IDF，把课里的方法用到自己的实验里。</p></div><a class="btn btn-secondary" href="#/opensource">查看开源学习路线</a></aside>'));

    root.appendChild(PVL.el(
      '<div class="banner banner-info">' +
        '<strong>学习模式与实践模式</strong>' +
        '<p>学习模式：阅读课程、查看示意内容，不需要任何硬件。</p>' +
        '<p>实践模式：连接旧手机与本地服务后，实验台、数据集、训练与性能分析都会使用真实数据，' +
        '并在界面上标注"真实设备 / 模拟演示 / 尚未连接 / 功能开发中"。</p>' +
      '</div>'
    ));
  },
};

window.PVL_PAGES.lesson = {
  render: async function (root, params) {
    const id = params.id;
    const course = PVL.courseMap()[id];
    if (!course) {
      root.appendChild(PVL.el(
        '<div class="empty-state">' +
          '<h2>课程不存在</h2>' +
          '<p>没有找到这门课：' + PVL.escapeHtml(id) + '</p>' +
          '<a class="btn btn-primary" href="#/learn">返回学习中心</a>' +
        '</div>'
      ));
      return;
    }

    const order = PVL.lessonOrder();
    const index = order.indexOf(id);
    const isDone = PVL.isLessonComplete(id);

    root.appendChild(PVL.el(
      '<nav class="breadcrumb" aria-label="位置">' +
        '<a href="#/learn">学习中心</a><span aria-hidden="true">/</span>' +
        '<span>第 ' + (index + 1) + ' 课</span>' +
      '</nav>'
    ));

    root.appendChild(PVL.el(
      '<article class="lesson">' +
        '<header class="lesson-head">' +
          '<p class="lesson-eyebrow">第 ' + (index + 1) + ' 课 · 约 ' +
            (course.minutes || 10) + ' 分钟</p>' +
          '<h1>' + PVL.escapeHtml(course.title) + '</h1>' +
          '<p class="lesson-sub">' + PVL.escapeHtml(course.subtitle || "") + '</p>' +
        '</header>' +

        '<section class="card"><div class="card-header">' +
          '<h2 class="card-title">学习目标</h2></div>' +
          '<div class="card-body"><ul class="goal-list">' +
            (course.goals || []).map(function (goal) {
              return '<li>' + PVL.escapeHtml(goal) + '</li>';
            }).join("") +
          '</ul></div></section>' +

        '<section class="card"><div class="card-header">' +
          '<h2 class="card-title">需要准备</h2></div>' +
          '<div class="card-body"><ul class="goal-list">' +
            (course.prerequisites || []).map(function (item) {
              return '<li>' + PVL.escapeHtml(item) + '</li>';
            }).join("") +
          '</ul></div></section>' +

        '<div class="lesson-sections"></div>' +

        '<section class="card"><div class="card-header">' +
          '<h2 class="card-title">完成标志</h2></div>' +
          '<div class="card-body"><ul class="goal-list">' +
            (course.checklist || []).map(function (item) {
              return '<li>' + PVL.escapeHtml(item) + '</li>';
            }).join("") +
          '</ul></div></section>' +

        '<section class="card lesson-actions"><div class="card-body">' +
          '<label class="checkbox-label">' +
            '<input type="checkbox" id="lesson-done"' + (isDone ? ' checked' : '') + '>' +
            '<span>我已完成这一课</span>' +
          '</label>' +
          '<div class="lesson-nav">' +
            (index > 0
              ? '<a class="btn btn-secondary" href="#/learn/' + order[index - 1] + '">上一课</a>'
              : '<a class="btn btn-secondary" href="#/learn">返回列表</a>') +
            (index < order.length - 1
              ? '<a class="btn btn-primary" href="#/learn/' + order[index + 1] + '">下一课</a>'
              : '<a class="btn btn-primary" href="#/lab">进入实验台</a>') +
          '</div>' +
        '</div></section>' +
      '</article>'
    ));

    const sectionsHost = root.querySelector(".lesson-sections");
    (course.sections || []).forEach(function (section) {
      const card = PVL.el(
        '<section class="card"><div class="card-header">' +
          '<h2 class="card-title">' + PVL.escapeHtml(section.heading) + '</h2></div>' +
          '<div class="card-body"></div></section>'
      );
      const body = card.querySelector(".card-body");
      (section.paragraphs || []).forEach(function (text) {
        body.appendChild(PVL.el('<p class="lesson-p">' +
          PVL.escapeHtml(text) + '</p>'));
      });
      if (section.bullets && section.bullets.length) {
        const list = PVL.el('<ul class="goal-list"></ul>');
        section.bullets.forEach(function (item) {
          list.appendChild(PVL.el('<li>' + PVL.escapeHtml(item) + '</li>'));
        });
        body.appendChild(list);
      }
      if (section.steps && section.steps.length) {
        const steps = PVL.el('<ol class="step-list"></ol>');
        section.steps.forEach(function (item, i) {
          steps.appendChild(PVL.el(
            '<li class="step-item"><span class="step-num">' + (i + 1) +
            '</span><span>' + PVL.escapeHtml(item) + '</span></li>'
          ));
        });
        body.appendChild(steps);
      }
      if (section.note) {
        body.appendChild(PVL.el('<p class="lesson-note">' +
          PVL.escapeHtml(section.note) + '</p>'));
      }
      sectionsHost.appendChild(card);
    });

    // 关联实验入口
    const demo = course.demo || {};
    const demoRoutes = {
      "image-processing": "/lab",
      "dataset": "/dataset",
      "training": "/train",
      "deploy": "/deploy",
      "hardware": "/hardware",
      "performance": "/performance",
    };
    if (demo.type && demoRoutes[demo.type]) {
      root.appendChild(PLV_demoCard(demo, demoRoutes[demo.type]));
    }

    const related = (window.PVL_OPEN_SOURCE || []).filter(function (item) { return item.lessons.includes(id); });
    if (related.length) root.appendChild(PVL.el('<section class="lesson-sources"><h2>用开源项目接着练</h2><p>读源码前先看对应路线里的准备条件和练习目标。</p>' + related.map(function (item) {
      return '<a href="#/opensource?stage=' + item.id + '">' + PVL.escapeHtml(item.project) + '：' + PVL.escapeHtml(item.title) + '</a>';
    }).join('') + '</section>'));

    const checkbox = root.querySelector("#lesson-done");
    if (checkbox) {
      checkbox.addEventListener("change", function () {
        PVL.markLessonComplete(id, checkbox.checked);
        PVL.toast(checkbox.checked ? "已标记为完成" : "已取消完成标记", "success");
        PVL.render();
      });
    }
  },
};

function PLV_demoCard(demo, route) {
  return PVL.el(
    '<section class="card lesson-demo"><div class="card-body">' +
      '<span class="badge badge-info">关联实验</span>' +
      '<h3>' + PVL.escapeHtml(demo.title || "打开实验") + '</h3>' +
      '<p>' + PVL.escapeHtml(demo.description || "") + '</p>' +
      '<a class="btn btn-primary" href="#' + route + '">进入实验</a>' +
    '</div></section>'
  );
}

window.PVL_PAGES.opensource = {
  render: async function (root) {
    const projects = window.PVL_OPEN_SOURCE || [];
    const params = new URLSearchParams(location.hash.split('?')[1] || '');
    const item = projects.find(function (p) { return p.id === params.get('stage'); }) || projects[0];
    const esc = PVL.escapeHtml;
    if (!item || !item.guide) {
      root.appendChild(PVL.el('<div class="empty-state"><h2>学习资料暂未加载</h2><p>请刷新页面重试，或先回到平台课程学习。</p><a href="#/learn">返回学习中心</a></div>'));
      return;
    }
    const g = item.guide;
    const index = projects.indexOf(item);
    function external(url, label) {
      return '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(label) + '</a>';
    }
    const nav = projects.map(function (p, i) {
      return '<a class="route-stop" href="#/opensource?stage=' + p.id + '"' + (p === item ? ' aria-current="step"' : '') + '><span class="route-stop-number">' + (i === 5 ? '选' : String(i + 1).padStart(2, '0')) + '</span><span><strong>' + esc(p.category) + '</strong><small>' + esc(p.project) + '</small></span></a>';
    }).join('');
    const reading = g.reading.map(function (r, i) {
      return '<li><span class="reading-order">' + String(i + 1).padStart(2, '0') + '</span><div>' + external(r[1], r[0]) + '<p>' + esc(r[2]) + '</p></div></li>';
    }).join('');
    root.appendChild(PVL.el(`
      <div class="source-guide">
        <header class="route-intro">
          <div><h2>沿着开源代码，做完一个视觉项目。</h2><p>从处理一张照片，到把模型放回手机。每站都有阅读重点、练习任务和自查问题。</p></div>
          <div class="route-scope"><strong>5 站主线，1 条开发支线</strong><span>从电脑上的图像处理开始</span></div>
        </header>
        <div class="source-guide-layout">
          <aside class="route-outline"><nav class="source-stations" aria-label="选择开源学习阶段"><h2>学习路线</h2>${nav}</nav><div class="route-mobile-picker"><label for="source-stage-selector">选择学习阶段</label><select class="field-select" id="source-stage-selector">${projects.map(function (p, i) { return '<option value="' + p.id + '"' + (p === item ? ' selected' : '') + '>' + (i === 5 ? '选学' : String(i + 1).padStart(2, '0')) + ' / ' + esc(p.category) + ' / ' + esc(p.project) + '</option>'; }).join('')}</select></div><div class="route-outline-note"><p>刚接触视觉 AI？</p><a href="#/learn">先读平台的 8 节入门课</a><p>相机开发是选学支线，使用现成手机 App 可以跳过。</p></div></aside>
          <article class="route-article source-project" id="source-${item.id}" aria-labelledby="route-title">
            <header class="route-article-head"><div class="route-position"><span>${index === 5 ? '开发支线' : '主线第 ' + (index + 1) + ' 站'}</span><span>${esc(item.level)}</span></div><h2 id="route-title">${esc(item.title)}</h2><p>${esc(item.why)}</p><div class="route-project-links">${external(item.repo, item.project + ' 仓库')}${external(item.entry, item.entryLabel)}</div></header>
            <dl class="route-preparation"><div><dt>需要准备</dt><dd>${esc(g.equipment)}</dd></div><div><dt>资料语言</dt><dd>${esc(item.language)}</dd></div></dl>
            <div class="route-prep-copy"><p>${esc(item.prepare)}</p><span>对应平台课程：${item.lessons.map(function (id) { return '<a href="#/learn/' + id + '">第 ' + id.slice(1) + ' 课</a>'; }).join('、')}</span></div>
            <nav class="route-inpage" aria-label="本阶段内容"><a href="#/opensource?stage=${item.id}&section=concepts">知识重点</a><a href="#/opensource?stage=${item.id}&section=reading">阅读清单</a><a href="#/opensource?stage=${item.id}&section=practice">动手练习</a><a href="#/opensource?stage=${item.id}&section=check">学习自查</a></nav>
            <section class="route-section" id="source-concepts" tabindex="-1"><div class="route-section-title"><h3>先理解这三个概念</h3><span>${esc(g.focus)}</span></div><dl class="concept-list">${g.concepts.map(function (c) { return '<div><dt>' + esc(c[0]) + '</dt><dd>' + esc(c[1]) + '</dd></div>'; }).join('')}</dl></section>
            <section class="route-section" id="source-reading" tabindex="-1"><div class="route-section-title"><h3>带着问题读源码</h3><span>按顺序阅读上游资料</span></div><ol class="reading-list">${reading}</ol><p class="route-reading-note">先沿着这两份资料找清楚输入、处理过程和输出，再回到自己的实验验证。</p></section>
            <section class="route-section" id="source-practice" tabindex="-1"><div class="route-section-title"><h3>动手练习</h3><span>本站设计的实践任务</span></div><div class="practice-brief"><h4>${esc(g.workshop.title)}</h4><p>${esc(g.workshop.brief)}</p><ol>${g.workshop.tasks.map(function (task) { return '<li>' + esc(task) + '</li>'; }).join('')}</ol><div class="practice-outputs"><strong>这次练习留下什么</strong><ul>${g.workshop.outputs.map(function (output) { return '<li>' + esc(output) + '</li>'; }).join('')}</ul></div><a class="btn btn-primary" href="#/${item.practice}">${esc(item.practiceLabel)}</a></div></section>
            <section class="route-section" id="source-check" tabindex="-1"><div class="route-section-title"><h3>合上资料，试着回答</h3><span>自查问题不计入课程完成进度</span></div><ol class="route-questions">${g.checks.map(function (q) { return '<li>' + esc(q) + '</li>'; }).join('')}</ol><p class="route-success"><strong>本阶段的完成目标</strong>${esc(item.result)}</p></section>
            <section class="route-section"><h3>遇到问题时</h3><div class="route-pitfalls">${g.pitfalls.map(function (p) { return '<details><summary>' + esc(p[0]) + '</summary><p>' + esc(p[1]) + '</p></details>'; }).join('')}</div><p class="source-note">${esc(item.note)}</p></section>
            <nav class="route-pagination" aria-label="切换学习阶段">${index > 0 ? '<a href="#/opensource?stage=' + projects[index - 1].id + '"><small>上一站</small><strong>' + esc(projects[index - 1].category) + '</strong></a>' : '<a href="#/learn"><small>先补基础</small><strong>平台入门课程</strong></a>'}${index < projects.length - 1 ? '<a href="#/opensource?stage=' + projects[index + 1].id + '"><small>' + (index === 4 ? '选学支线' : '下一站') + '</small><strong>' + esc(projects[index + 1].category) + '</strong></a>' : '<a href="#/lab"><small>带回自己的项目</small><strong>进入视觉实验台</strong></a>'}</nav>
            <p class="source-provenance">阅读指引、练习与自查由本站整理，原文以上游资料为准。资料核对：2026-11-02。外部资料需要联网，示例未逐一在实机复现。</p>
          </article>
        </div>
      </div>
    `));
    const selector = root.querySelector('#source-stage-selector');
    if (selector) selector.addEventListener('change', function () {
      if (projects.some(function (p) { return p.id === selector.value; })) location.hash = '#/opensource?stage=' + selector.value;
    });
    const section = params.get('section');
    if (['concepts', 'reading', 'practice', 'check'].includes(section)) {
      requestAnimationFrame(function () {
        const target = root.querySelector('#source-' + section);
        if (target) { target.scrollIntoView({ block: 'start' }); target.focus({ preventScroll: true }); }
      });
    }
  }
};
