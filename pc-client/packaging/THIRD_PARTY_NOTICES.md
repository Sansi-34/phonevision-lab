# PhoneVision Lab — 第三方组件许可声明

本文件列举 Windows 便携包（`PhoneVisionLab_<版本>_win-x64.zip`）内随附的第三方
组件及其许可。许可全文存放于 `licenses/` 目录（与本文档同目录）。

> 许可信息来源：各包在**已安装 wheel 元数据**（`*.dist-info/METADATA` 的
> `License` / `License-Expression` / `License-File` 字段）与随包 LICENSE 文件中的
> 实际声明，非凭记忆填写。包版本以打包时锁定的 `requirements-windows.lock` 为准；
> 下列版本为提交时的构建环境版本，最终以锁文件为准。

## 运行时组件（随便携包分发）

| 组件 | 版本 | 许可 | 项目主页 | 许可文件（licenses/） |
| --- | --- | --- | --- | --- |
| CPython（解释器运行时） | 3.12 | Python Software Foundation License（PSF） | https://www.python.org/ | `CPython_LICENSE.txt` |
| PySide6（Qt for Python 绑定） | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only（另有商业许可） | https://pyside.org | `PySide6_LicenseRef-Qt-Commercial.txt`（商业条款） |
| PySide6_Essentials | 6.11.1 | 同上 | https://pyside.org | `PySide6_Essentials_LicenseRef-Qt-Commercial.txt` |
| PySide6_Addons | 6.11.1 | 同上 | https://pyside.org | `PySide6_Addons_LicenseRef-Qt-Commercial.txt` |
| shiboken6（绑定生成器运行时） | 6.11.1 | 同上 | https://pyside.org | `shiboken6_LicenseRef-Qt-Commercial.txt` |
| Qt（随 PySide6 分发的 Qt 库） | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://www.qt.io/ | 见上（PySide6 许可） |
| opencv-python（OpenCV 绑定） | 5.0.0.93 | Apache-2.0（wheel 元数据 `License: Apache 2.0`） | https://github.com/opencv/opencv-python | `opencv-python_LICENSE-3RD-PARTY.txt`（OpenCV 本体，含 Apache 2.0 全文）、`opencv-python_wrapper_LICENSE.txt`（MIT 包装声明） |
| OpenCV（随 opencv-python 分发的二进制） | — | Apache-2.0 | https://opencv.org/ | `opencv-python_LICENSE-3RD-PARTY.txt` |
| NumPy | 2.5.1 | BSD-3-Clause（wheel 元数据含 AND 子许可，主许可为 BSD-3） | https://numpy.org | `numpy_LICENSE.txt` |
| Requests | 2.34.2 | Apache-2.0 | https://requests.readthedocs.io | `requests_LICENSE.txt`、`requests_NOTICE.txt` |
| Pillow | 12.3.0 | MIT-CMU（元数据 `License-Expression: MIT-CMU`，即 HPND 系历史许可） | https://python-pillow.github.io | `pillow_LICENSE.txt` |

## Requests 传递依赖（随便携包分发）

| 组件 | 版本 | 许可 | 项目主页 | 许可文件 |
| --- | --- | --- | --- | --- |
| urllib3 | 2.7.0 | MIT | https://urllib3.readthedocs.io | `urllib3_LICENSE.txt` |
| certifi | 2026.7.22 | MPL-2.0 | https://github.com/certifi/python-certifi | `certifi_LICENSE.txt` |
| charset-normalizer | 3.4.9 | MIT | https://charset-normalizer.readthedocs.io | `charset_normalizer_LICENSE.txt` |
| idna | 3.18 | BSD-3-Clause | https://github.com/kjd/idna | `idna_LICENSE.md` |

## 构建期组件（仅打包时使用，不随便携包分发）

| 组件 | 版本 | 许可 | 项目主页 |
| --- | --- | --- | --- |
| PyInstaller | 6.22.0 | GPL-2.0-or-later 带 Bootloader Exception（允许用它打包并分发自由或商业程序） | https://pyinstaller.org |
| pyinstaller-hooks-contrib | 2026.6 | Apache-2.0（其自身仓库声明；构建后按实际元数据核验） | https://github.com/pyinstaller/pyinstaller-hooks-contrib |

## 保留的许可文本

- Qt / PySide6 要求保留其许可条款。当前 wheel 仅携带 `LicenseRef-Qt-Commercial.txt`
  商业条款文本；LGPL-3.0 / GPL 文本未随 wheel 附带。本项目以 LGPL-3.0 条款使用并
  分发 Qt/PySide6（动态链接、不修改 Qt 库、随包附源代码获取方式说明），完整 LGPL-3.0
  文本请见 <https://www.gnu.org/licenses/lgpl-3.0.html> 与
  <https://doc.qt.io/qt-6/lgpl.html>。
- **待确认**：PyInstaller 在 `pip show` 中 `License` 字段直接声明为
  "GPLv2-or-later with a special exception"，与官方一致，本声明据此填写；
  但该字段未使用标准 SPDX 标识（无 `License-Expression`），已按说明原文记录。
- **待确认**：`pyinstaller-hooks-contrib` 的 `pip show` 未返回 `License` 字段，
  上方 Apache-2.0 取自其 GitHub 仓库 `COPYING`；构建后请按实际 wheel 元数据核验。
- **待确认**：Pillow 元数据 `License-Expression: MIT-CMU`（SPDX 中为
  "MIT-CMU"，即 HPND 系）。若构建环境版本不同，以实际元数据为准。

## 本应用自身

PhoneVision Lab 本体以 MIT 许可开源（见仓库根目录 `LICENSE`）。

---

*生成说明：本文件与 `licenses/` 内容由打包流程从已安装 wheel 元数据生成；
  构建后应复核一次版本与许可字段与锁文件一致。*
