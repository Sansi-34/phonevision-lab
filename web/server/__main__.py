"""
PhoneVision Lab Web — 入口：`python -m web.server`。

单独一个文件而不是在 app.py 里加 __main__ 分支的原因：
  - app.py 被测试 import（测试只驱动路由与 handler，不想启动真服务器）；
  - 把"启动服务器"的 argparse 与 serve_forever 隔在这里，测试导入零副作用。

常用命令：
  python -m web.server                      # 监听 127.0.0.1:8088（仅本机）
  python -m web.server --port 9000

注意：入口的 Host 白名单只接受 127.0.0.1 / localhost / [::1]，
`--host 0.0.0.0` 的局域网访问会被 403 拒绝（防 DNS rebinding）。
"""
from __future__ import annotations

import os
import sys

# 让 `python -m web.server` 在仓库任意位置都能 import 到 server 包
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from server.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
