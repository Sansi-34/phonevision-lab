/** PhoneVision Lab — a course index and a working image-processing sample. */
window.PVL_PAGES = window.PVL_PAGES || {};
window.PVL_PAGES.home = {
  render: async function (root) {
    const order = PVL.lessonOrder();
    const courses = PVL.courses();
    const completed = PVL.store.completedLessons || [];
    const done = order.filter(function (id) { return completed.includes(id); }).length;
    const next = order.find(function (id) { return !completed.includes(id); });
    const esc = PVL.escapeHtml;
    const names = [
      '计算机怎样看一张图', '把旧手机接到电脑上', '试试灰度、边缘与颜色', '为模型准备自己的数据',
      '训练第一个分类模型', '让模型在手机上运行', '用识别结果点亮 LED', '看懂帧率与延迟'
    ];
    const tracks = ['认识视觉', '设备连接', '图像处理', '数据采集', '模型训练', '手机部署', '硬件联动', '性能分析'];
    const rows = order.map(function (id, i) {
      const course = courses[id] || {};
      const isDone = completed.includes(id);
      return `<a class="notebook-lesson${isDone ? ' is-done' : ''}" href="#/learn/${esc(id)}" title="${esc(course.title || id)}">
        <span class="notebook-number">${String(i + 1).padStart(2, '0')}</span>
        <span class="notebook-name">${esc(names[i] || course.title || id)}<small>${esc(tracks[i] || '')}</small></span>
        <span class="notebook-duration">约 ${Number(course.minutes) || 10} 分钟</span>
        <span class="notebook-state">${isDone ? '已完成' : (id === next ? '从这里开始' : '未完成')}</span>
      </a>`;
    }).join('');

    root.appendChild(PVL.el(`<div class="home-workbench">
      <section class="home-intro" aria-labelledby="home-title">
        <div class="home-story">
          <h2 id="home-title">用旧手机，<br>做一次视觉实验。</h2>
          <p>从一张图像开始，学会采集、训练，<br class="wide-break">再把模型放回手机。</p>
          <div class="home-start">
            <a class="btn btn-primary btn-lg" href="#/learn">开始学习（${order.length} 课）</a>
            <a class="home-quiet-link" href="#/lab">已有手机？去连接</a>
          </div>
          <p class="home-reassurance">课程随时可读，不必先准备硬件。</p>
        </div>
        <figure class="image-study" aria-labelledby="study-heading">
          <div class="study-toolbar">
            <span id="study-heading">先试试看</span>
            <div class="study-switch" role="group" aria-label="示例图像处理方式">
              <button type="button" data-study-mode="original" aria-pressed="true">原图</button>
              <button type="button" data-study-mode="gray" aria-pressed="false">灰度</button>
              <button type="button" data-study-mode="edge" aria-pressed="false">边缘</button>
            </div>
          </div>
          <div class="study-image">
            <img id="study-source" src="/assets/jade-study.jpg" width="1280" height="929" alt="玉树的叶片与枝干，用来观察颜色、亮度和边缘的变化" fetchpriority="high">
            <canvas id="study-canvas" width="640" height="465" hidden role="img" aria-label="示例照片的图像处理结果"></canvas>
          </div>
          <figcaption><span id="study-description" aria-live="polite">点击灰度或边缘，看看同一张照片有什么不同。</span><span>示例照片，非实时画面</span></figcaption>
        </figure>
      </section>
      <div class="home-notebook">
        <section class="notebook-courses" aria-labelledby="notebook-heading">
          <div class="notebook-heading"><div><h2 id="notebook-heading">一课一课，做出来。</h2><p>${done ? `已完成 ${done} / ${order.length} 课` : `从连接手机到本地推理，共 ${order.length} 课。`}</p></div><a href="#/learn">课程目录</a></div>
          <div class="notebook-lessons">${rows}</div>
          <p class="notebook-footnote">阅读时长为估计值。学习进度只保存在这台电脑的浏览器里。</p>
        </section>
        <aside class="bench-aside" aria-label="动手实践">
          <section class="bench-connection">
            <div class="connection-title"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="6" y="2" width="12" height="20" rx="2"/><path d="M10 18h4M9 6h6"/></svg><h2>手边有旧手机？</h2></div>
            <p id="home-device-state" role="status">正在查看连接状态…</p>
            <p>手机与电脑连接同一个 Wi-Fi，<br>在手机 App 中开启推流。</p>
            <a class="btn btn-secondary" href="#/lab">进入实验台</a>
          </section>
          <section class="bench-tools" aria-labelledby="tools-heading"><h2 id="tools-heading">你的实验工具</h2>
            <a href="#/dataset"><span>数据集工作区<small>采集图片，整理类别</small></span><span aria-hidden="true">↗</span></a>
            <a href="#/train"><span>模型训练<small>需要本地训练依赖</small></span><span aria-hidden="true">↗</span></a>
            <a href="#/deploy"><span>手机部署与推理<small>导出后，在手机端导入</small></span><span aria-hidden="true">↗</span></a>
            <a href="#/hardware"><span>硬件联动<small>旧手机与 ESP32</small></span><span aria-hidden="true">↗</span></a>
            <a href="#/performance"><span>性能分析<small>只记录真实测量结果</small></span><span aria-hidden="true">↗</span></a>
          </section>
          <a class="bench-help" href="#/help">第一次使用？查看准备指南</a>
          <a class="bench-help" href="#/opensource">学完课程，跟开源项目继续练</a>
        </aside>
      </div>
      <details class="capability-reference"><summary>各项功能的条件与限制</summary><div class="capability-body"><table class="table home-capabilities" role="table"><thead role="rowgroup"><tr role="row"><th scope="col" role="columnheader">能力</th><th scope="col" role="columnheader">状态</th><th scope="col" role="columnheader">说明</th></tr></thead><tbody role="rowgroup"><tr role="row"><td role="cell">手机摄像头实时画面</td><td role="cell"><span class="badge badge-info">需连接手机</span></td><td role="cell">手机 App 开始推流后，本地服务解析 MJPEG 流并提供画面</td></tr><tr role="row"><td role="cell">传统视觉处理</td><td role="cell"><span class="badge badge-success">现有</span></td><td role="cell">原始 / 灰度 / Canny / HSV / 轮廓五种模式</td></tr><tr role="row"><td role="cell">数据集采集与体检</td><td role="cell"><span class="badge badge-success">现有</span></td><td role="cell">按采集批次划分训练/验证集，避免指标虚高</td></tr><tr role="row"><td role="cell">模型训练与导出</td><td role="cell"><span class="badge badge-warning">需训练依赖</span></td><td role="cell">需安装 requirements-train.txt（TensorFlow）；未安装时页面会说明</td></tr><tr role="row"><td role="cell">手机本机推理</td><td role="cell"><span class="badge badge-warning">手机端操作</span></td><td role="cell">在 Android App 导入模型包；网页端只提供指南，不能自动推送</td></tr><tr role="row"><td role="cell">硬件联动</td><td role="cell"><span class="badge badge-warning">未全面验证</span></td><td role="cell">可连接控制器做手动测试；自动控制在手机端执行，网页端不提供开关</td></tr><tr role="row"><td role="cell">性能分析</td><td role="cell"><span class="badge badge-success">现有</span></td><td role="cell">采集/接收/显示帧率与丢帧为真实数据；推理与功耗显示“未采集”</td></tr></tbody></table></div></details>
      <p class="study-credit">示例照片：<a href="https://commons.wikimedia.org/wiki/File:Among_the_branches_of_a_potted_jade_plant.jpg" target="_blank" rel="noopener noreferrer">W.carter</a>，CC0，来自 Wikimedia Commons。</p>
    </div>`));

    let disposed = false;
    let mode = 'original';
    let pixels = null;
    const image = root.querySelector('#study-source');
    const canvas = root.querySelector('#study-canvas');
    const description = root.querySelector('#study-description');
    const buttons = root.querySelectorAll('[data-study-mode]');
    function draw() {
      if (disposed || !image.complete || !image.naturalWidth) return;
      if (mode === 'original') {
        image.hidden = false;
        canvas.hidden = true;
        description.textContent = '点击灰度或边缘，看看同一张照片有什么不同。';
        return;
      }
      const context = canvas.getContext('2d', { willReadFrequently: true });
      if (!context) return;
      if (!pixels) {
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        pixels = context.getImageData(0, 0, canvas.width, canvas.height);
      }
      const w = canvas.width, h = canvas.height;
      const gray = new Float32Array(w * h);
      for (let i = 0; i < gray.length; i++) gray[i] = pixels.data[i * 4] * .299 + pixels.data[i * 4 + 1] * .587 + pixels.data[i * 4 + 2] * .114;
      const result = context.createImageData(w, h);
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        const i = y * w + x;
        let value = gray[i];
        if (mode === 'edge') {
          value = 0;
          if (x > 0 && y > 0 && x < w - 1 && y < h - 1) {
            const gx = -gray[i - w - 1] + gray[i - w + 1] - 2 * gray[i - 1] + 2 * gray[i + 1] - gray[i + w - 1] + gray[i + w + 1];
            const gy = -gray[i - w - 1] - 2 * gray[i - w] - gray[i - w + 1] + gray[i + w - 1] + 2 * gray[i + w] + gray[i + w + 1];
            value = Math.min(255, Math.hypot(gx, gy));
          }
        }
        result.data[i * 4] = result.data[i * 4 + 1] = result.data[i * 4 + 2] = value;
        result.data[i * 4 + 3] = 255;
      }
      context.putImageData(result, 0, 0);
      image.hidden = true;
      canvas.hidden = false;
      description.textContent = mode === 'gray' ? '去掉颜色后，只留下亮度的变化。' : 'Sobel 算子提取亮度变化，显出叶片和枝干的边缘。';
      canvas.setAttribute('aria-label', mode === 'gray' ? '玉树照片的灰度处理结果' : '玉树照片的 Sobel 边缘处理结果');
    }
    image.addEventListener('load', draw);
    image.addEventListener('error', function () {
      description.textContent = '示例照片未能加载。你仍可阅读课程或连接手机。';
      buttons.forEach(function (button) { button.disabled = true; });
    });
    buttons.forEach(function (button) {
      button.addEventListener('click', function () {
        mode = button.getAttribute('data-study-mode');
        buttons.forEach(function (item) { item.setAttribute('aria-pressed', String(item === button)); });
        draw();
      });
    });
    function updateDeviceState(event) {
      if (disposed) return;
      const status = event ? event.detail : PVL.getDeviceStatus();
      if (!status) {
        root.querySelector('#home-device-state').textContent = '暂时无法读取设备状态';
        return;
      }
      root.querySelector('#home-device-state').textContent = status.connected
        ? '已连接 ' + (status.host || '手机') + '，' + (status.state_label || status.state || '')
        : '还没有连接手机';
    }
    document.addEventListener('pvl:device-status', updateDeviceState);
    if (PVL.getDeviceStatus()) updateDeviceState();
    return function () {
      disposed = true;
      image.removeEventListener('load', draw);
      document.removeEventListener('pvl:device-status', updateDeviceState);
    };
  }
};
