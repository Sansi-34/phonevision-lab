# Web 原型 · 设计与实现契约（并行开发必读）

所有页面必须遵守本文件。风格不统一 = 返工。

## 0. 事实基线（不许改写）

- 手机通过**局域网**用 MJPEG 推流到电脑，默认 `http://<手机IP>:8080`，**不是 USB**。
- 电脑负责：实时预览、传统视觉处理、数据集、训练、导出、手动硬件测试、性能记录。
- 手机负责：采集、**本机** TFLite 推理、自动联动规则。
- 硬件：ESP32 + LED，端口 8081；命令四态 `已发送 / 已接收 / 已执行 / 失败`。
- 性能：电脑只实测"接收帧率/显示帧率/丢帧"等传输指标；手机推理、硬件耗时、功耗**未接入**，显示"未采集 / 暂不支持"。
- 现状：真机端到端、ESP32 真机联动、便携包内训练环境均**未完成验证**，界面上必须如实标注。
- 原型没有任何后端。所有"连接""训练""采集"按钮都只能做**本地交互演示**，并在文案里说明原型不会真的连接。

## 1. 文件与归属

| 文件 | 负责人 | 说明 |
| --- | --- | --- |
| `assets/css/styles.css` | Lead（已完成） | 令牌 + 通用组件，**禁止修改** |
| `assets/css/page-home.css` | home | 仅首页/项目页样式 |
| `assets/css/page-learn.css` | learn | 学习中心 + 课程详情 |
| `assets/css/page-lab.css` | lab | 实验台 |
| `assets/js/site.js` | Lead（已完成） | 导航/弹窗/进度/筛选，**禁止修改** |
| `assets/js/lab.js` | lab | 实验台画布处理 |
| `index.html` `projects.html` | home | |
| `learn.html` `lesson.html` | learn | |
| `lab.html` | lab | |

页面专属 CSS 只能写自己那份文件；需要新组件时优先用 `styles.css` 已有类组合。

## 2. 通用 head

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>页面名 · PhoneVision Lab</title>
  <meta name="description" content="……（一句真实的描述）">
  <link rel="stylesheet" href="assets/css/styles.css">
  <link rel="stylesheet" href="assets/css/page-xxx.css">
  <script defer src="assets/js/site.js"></script>
</head>
<body data-page="home">   <!-- home | learn | lab | projects | lesson -->
```

## 3. 导航（逐字复制，不要改结构）

`aria-current` 由 `site.js` 根据 `<body data-page>` 自动加，**不要手写**。

```html
<header class="nav">
  <div class="nav__inner">
    <a class="brand" href="index.html" aria-label="PhoneVision Lab 首页">
      <svg class="brand__mark" viewBox="0 0 26 26" aria-hidden="true">
        <rect x="1" y="1" width="7" height="7" rx="1.6" fill="#14203A"/>
        <rect x="9.5" y="1" width="7" height="7" rx="1.6" fill="#1F4BE0"/>
        <rect x="18" y="1" width="7" height="7" rx="1.6" fill="#D6E1FB"/>
        <rect x="1" y="9.5" width="7" height="7" rx="1.6" fill="#14203A"/>
        <rect x="9.5" y="9.5" width="7" height="7" rx="1.6" fill="#14203A"/>
        <rect x="18" y="9.5" width="7" height="7" rx="1.6" fill="#E5DFD3"/>
        <rect x="1" y="18" width="7" height="7" rx="1.6" fill="#E5DFD3"/>
        <rect x="9.5" y="18" width="7" height="7" rx="1.6" fill="#14203A"/>
        <rect x="18" y="18" width="7" height="7" rx="1.6" fill="#1F4BE0"/>
      </svg>
      <span class="brand__name">PhoneVision <span>Lab</span></span>
    </a>
    <nav class="nav__links" aria-label="主导航">
      <a class="nav__link" data-nav="learn" href="learn.html">学习</a>
      <a class="nav__link" data-nav="lab" href="lab.html">实验台</a>
      <a class="nav__link" data-nav="projects" href="projects.html">我的项目</a>
    </nav>
    <div class="nav__right">
      <span class="status">
        <span class="status__dot" aria-hidden="true"></span>
        手机未连接
        <span class="status__sep" aria-hidden="true"></span>
        <span class="status__detail">局域网</span>
      </span>
      <button class="btn btn--primary btn--sm" type="button" data-open-modal="connect-modal">连接手机</button>
      <button class="nav__help" type="button" data-open-modal="help-modal" aria-label="帮助">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M9.4 9.2a2.7 2.7 0 1 1 3.9 2.4c-.8.4-1.3 1-1.3 1.9"/><circle cx="12" cy="17" r=".8" fill="currentColor" stroke="none"/></svg>
      </button>
    </div>
  </div>
</header>
```

## 4. 连接弹窗（每个页面都要有，逐字复制，放在 `</body>` 前）

```html
<div class="modal" id="connect-modal" role="dialog" aria-modal="true" aria-labelledby="connect-title">
  <div class="modal__panel">
    <div class="modal__head">
      <div>
        <p class="eyebrow eyebrow--plain">局域网连接</p>
        <h2 class="modal__title" id="connect-title">连接你的旧手机</h2>
      </div>
      <button class="modal__close" type="button" data-close-modal aria-label="关闭">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>
      </button>
    </div>
    <div class="modal__body">
      <ol class="steps">
        <li><strong>让两台设备连同一个 Wi-Fi。</strong>手机和电脑必须在同一局域网，不要用手机热点做桥接。</li>
        <li><strong>在手机 App 里点「开始推流」。</strong>App 会在屏幕上显示本机地址，例如 192.168.2.14:8080。</li>
        <li><strong>把地址填到下面。</strong>电脑会先请求 /ping 确认手机在线，再开始接收 MJPEG 画面。</li>
      </ol>
      <form class="stack u-mt5" data-connect-form novalidate>
        <label class="field">
          <span class="field__label">手机地址</span>
          <input class="input input--mono" name="host" type="text" inputmode="decimal"
                 placeholder="192.168.2.14" autocomplete="off" spellcheck="false">
          <span class="field__hint">以手机 App 屏幕上显示的地址为准，不同 Wi-Fi 下会变。</span>
        </label>
        <label class="field">
          <span class="field__label">端口</span>
          <input class="input input--mono" name="port" type="text" inputmode="numeric" value="8080">
        </label>
        <div data-connect-result hidden></div>
        <div class="modal__actions">
          <button class="btn btn--primary" type="submit">检测并连接</button>
          <a class="btn btn--ghost" href="lab.html">先看示意画面</a>
        </div>
        <p class="meta">原型说明：本页面没有网络层，不会真的连接设备，也不会保存地址。真实连接由桌面客户端完成。</p>
      </form>
    </div>
  </div>
</div>
```

## 5. 帮助弹窗（逐字复制）

```html
<div class="modal" id="help-modal" role="dialog" aria-modal="true" aria-labelledby="help-title">
  <div class="modal__panel">
    <div class="modal__head">
      <div>
        <p class="eyebrow eyebrow--plain">帮助</p>
        <h2 class="modal__title" id="help-title">常见问题</h2>
      </div>
      <button class="modal__close" type="button" data-close-modal aria-label="关闭">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>
      </button>
    </div>
    <div class="modal__body stack">
      <div><p class="h3">连不上手机？</p><p class="small u-mt2">确认手机 App 已点「开始推流」、两台设备在同一 Wi-Fi、地址与 App 显示一致。电脑上可先访问 http://手机IP:8080/ping 验证。</p></div>
      <hr class="hairline">
      <div><p class="h3">训练按钮是灰的？</p><p class="small u-mt2">训练需要独立的 Python 环境（requirements-train.txt）。便携包不内置 TensorFlow，请改用 start-training.cmd 启动。</p></div>
      <hr class="hairline">
      <div><p class="h3">为什么 LED 没有真的亮？</p><p class="small u-mt2">ESP32 与 LED 的真机链路仍在验证中。电脑端只能确认到「已接收」，没有「已执行」回执时不会显示成功。</p></div>
      <hr class="hairline">
      <div><p class="h3">数据存在哪里？</p><p class="small u-mt2">默认在本机 %LOCALAPPDATA%\PhoneVisionLab，不上传云端，也没有账号体系。</p></div>
    </div>
  </div>
</div>
```

## 6. 页脚（逐字复制）

```html
<footer class="footer">
  <div class="container">
    <div class="footer__grid">
      <div>
        <a class="brand" href="index.html">
          <!-- 同 nav 的品牌 SVG，可复制 -->
        </a>
        <p class="small u-mt3" style="max-width: 28ch">把闲置安卓手机变成采集设备与边缘推理终端的学习平台。</p>
      </div>
      <div>
        <p class="footer__title">学习</p>
        <a class="footer__link" href="learn.html">全部课程</a>
        <a class="footer__link" href="lesson.html">从第一课开始</a>
        <a class="footer__link" href="learn.html#ch3">图像处理</a>
      </div>
      <div>
        <p class="footer__title">实践</p>
        <a class="footer__link" href="lab.html">视觉实验台</a>
        <a class="footer__link" href="projects.html">我的项目</a>
        <a class="footer__link" href="lab.html#metrics">性能指标</a>
      </div>
      <div>
        <p class="footer__title">关于</p>
        <a class="footer__link" href="#" data-open-modal="help-modal">帮助与常见问题</a>
        <a class="footer__link" href="#" data-open-modal="connect-modal">连接手机</a>
        <span class="footer__link u-muted">本地运行 · 无账号 · 无云端</span>
      </div>
    </div>
    <div class="footer__bottom">
      <span>© <span data-year></span> PhoneVision Lab · 学习原型</span>
      <span>页面中的画面、分类结果与性能数字均为示意，不代表真实测试。</span>
    </div>
  </div>
</footer>
```

## 7. 已有类清单（只能用这些 + 自己的页面类）

- 布局：`.container` `.section` `.section--tight` `.section--band` `.stack` `.grid` `.hairline`
- 文字：`.display` `.h1` `.h2` `.h3` `.lead` `.body` `.small` `.meta` `.mono` `.eyebrow` `.eyebrow--plain` `.section-head` `.section-head__text` `.section-head__aside`
- 按钮：`.btn` `.btn--primary` `.btn--ghost` `.btn--quiet` `.btn--sm` `.btn--block` `.link`
- 卡片：`.card` `.card--blue` `.card--mint` `.card--sand` `.card--lilac` `.card--sky` `.card--flush` `.card__head` `.card__title`
- 标签：`.tag` `.tag--know` `.tag--lab` `.tag--plan` `.tag--ok` `.tag--warn` `.tag--danger` `.chips` `.chip`
- 状态：`.status` `.status__dot` `.status__dot--live/wait/error` `.status__sep` `.status__detail`
- 进度：`.progress` `.progress__bar` `.progress--thin`
- 提示：`.callout` `.callout--info/warn/ok` `.callout__icon` `.callout__title`
- 表单：`.field` `.field__label` `.input` `.input--mono` `.field__hint` `.field__error`
- 弹窗：`.modal` `.modal__panel` `.modal__head` `.modal__title` `.modal__close` `.modal__body` `.modal__actions`
- 步骤：`.steps`
- 空/加载：`.empty` `.empty__art` `.empty__title` `.empty__desc` `.skeleton`
- 表格：`.table` `.table--fixed`
- 工具：`.sr-only` `.u-muted` `.u-ink2` `.u-mono` `.u-nowrap` `.u-mt2..7` `.flex` `.items-center` `.gap2/3/4` `.between` `.wrap` `.shrink-0`

## 8. 文案与诚实规则

1. 中文，克制的书面语；不用 emoji，不用「一键部署」「智能识别」「颠覆」这类营销词。
2. 任何数字要么是真实可核对的事实（例如 8080 端口、24 课、8 章），要么明确写「示意」。
3. 未接入的能力用 `.tag--plan`「规划中」或文案「未采集」「暂不支持」，**不要**用禁用按钮假装成已实现。
4. 禁止出现：目标检测框（当前是图像分类）、"AI 会自动帮你"、云端账号、USB 连接手机。
5. 插图里的分类结果必须标「示意」，例如画面角标「示意画面 · 非真实设备」。

## 9. 字体与视觉纪律

- 大标题用 `.display` / `.h1` / `.h2`（衬线）；正文、按钮、导航一律无衬线。
- 强调色只有钴蓝 `--blue`；辅助色只用于卡片底，不用于文字。
- 不用渐变、发光、玻璃拟态、重阴影；层次靠留白、细线、底色。
- 卡片圆角 `--r-lg`（14px），按钮是胶囊；不要用 24px+ 的大圆角。
- 图标统一 24×24 线性、`stroke-width: 1.6~1.8`、`stroke-linecap: round`。

## 10. 可访问性

- 每个 `<svg>` 装饰性加 `aria-hidden="true"`；有语义的加 `role="img"` + `<title>`。
- 表单控件必须有 `<label>`；按钮有明确文案或用 `aria-label`。
- 状态不能只靠颜色：色点 + 文字。
- 图片/画布需有替代说明（`aria-label` 或相邻文字）。

## 11. 验收

- 五个页面互相可达：`index.html ⇄ learn.html ⇄ lesson.html ⇄ lab.html ⇄ projects.html`。
- 1440 / 1024 / 768 / 390 宽度下无横向滚动、无文字溢出。
- 所有页面导航一致、页脚一致、弹窗可用（Esc 关闭）。
- 控制台无报错。
