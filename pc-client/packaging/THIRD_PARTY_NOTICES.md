# PhoneVision Lab — 第三方组件许可声明

本文件列举 Windows 便携包（`PhoneVisionLab_<版本>_win-x64.zip`）内随附的第三方
组件及其许可。许可全文存放于 `licenses/` 目录（与本文档同目录）。

> 许可信息来源：各包在**已安装 wheel 元数据**（`*.dist-info/METADATA` 的
> `License` / `License-Expression` / `License-File` 字段）与随包 LICENSE 文件中的
> 实际声明，非凭记忆填写。包版本以打包时锁定的 `requirements-windows.lock` 为准；
> 下列版本为提交时的构建环境版本，最终以锁文件为准。

## 项目采用的许可路径

PhoneVision Lab 对 Qt / PySide6 采用 **LGPL-3.0** 路径（动态链接、不修改 Qt 库、
随包附源码获取方式与用户替换说明）。PyPI 上的 PySide6 官方 wheel 只发布
**Community Edition**，其元数据 `License` 字段为：

```
LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only
```

即该分发可选 LGPL-3.0 / GPL-2.0 / GPL-3.0 任一条款授权。本工程选择 **LGPL-3.0**。
许可合规说明见仓库 `docs/qt-lgpl-compliance.md`。

> **重要**：wheel 自带的 `LicenseRef-Qt-Commercial.txt` 是**商业条款**文本，仅因
> wheel 元数据引用而保留，**不代表本项目采用商业 Qt 授权**。Commercial 文本保留在
> `licenses/` 仅供存在性参考，不构成当前授权条款。

## 运行时组件（随便携包分发）

| 组件 | 版本 | 许可 | 项目主页 | 许可文件（licenses/） |
| --- | --- | --- | --- | --- |
| CPython（解释器运行时） | 3.12 | Python Software Foundation License（PSF） | https://www.python.org/ | `CPython_LICENSE.txt` |
| PySide6（Qt for Python 绑定） | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only；本项目采用 **LGPL-3.0**（Community Edition） | https://pyside.org | `lgpl-3.0.txt`、`gpl-3.0.txt`（LGPL 引用的 GPL-3.0）、`PySide6_LicenseRef-Qt-Commercial.txt`（商业条款，非当前采用） |
| PySide6_Essentials | 6.11.1 | 同上（本项目采用 LGPL-3.0） | https://pyside.org | 同上（`PySide6_Essentials_LicenseRef-Qt-Commercial.txt` 商业条款为保留参考） |
| PySide6_Addons | 6.11.1 | 同上（本项目采用 LGPL-3.0） | https://pyside.org | 同上（`PySide6_Addons_LicenseRef-Qt-Commercial.txt` 商业条款为保留参考） |
| shiboken6（绑定生成器运行时） | 6.11.1 | 同上（本项目采用 LGPL-3.0） | https://pyside.org | `lgpl-3.0.txt`、`gpl-3.0.txt`、`shiboken6_LicenseRef-Qt-Commercial.txt`（商业条款为保留参考） |
| Qt（随 PySide6 分发的 Qt 库，动态链接） | 6.11.1 | 同上（本项目采用 LGPL-3.0） | https://www.qt.io/ | 同 PySide6；Qt 库以动态链接方式随包分发（见 `docs/qt-lgpl-compliance.md`） |
| opencv-python（OpenCV 绑定） | 5.0.0.93 | Apache-2.0（wheel 元数据 `License: Apache 2.0`） | https://github.com/opencv/opencv-python | `opencv-python_LICENSE-3RD-PARTY.txt`（OpenCV 本体，含 Apache 2.0 全文）、`opencv-python_wrapper_LICENSE.txt`（MIT 包装声明） |
| OpenCV（随 opencv-python 分发的二进制） | — | Apache-2.0 | https://opencv.org/ | `opencv-python_LICENSE-3RD-PARTY.txt` |
| NumPy | 2.5.2 | BSD-3-Clause（元数据 `License-Expression: BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`，主许可为 BSD-3） | https://numpy.org | `numpy_LICENSE.txt` |
| Requests | 2.34.2 | Apache-2.0 | https://requests.readthedocs.io | `requests_LICENSE.txt`、`requests_NOTICE.txt` |
| Pillow | 12.3.0 | MIT-CMU（元数据 `License-Expression: MIT-CMU`，即 HPND 系历史许可） | https://python-pillow.github.io | `pillow_LICENSE.txt` |

## Requests 传递依赖（随便携包分发）

| 组件 | 版本 | 许可 | 项目主页 | 许可文件 |
| --- | --- | --- | --- | --- |
| urllib3 | 2.7.0 | MIT | https://urllib3.readthedocs.io | `urllib3_LICENSE.txt` |
| certifi | 2026.7.22 | MPL-2.0 | https://github.com/certifi/python-certifi | `certifi_LICENSE.txt` |
| charset-normalizer | 3.5.0 | MIT | https://charset-normalizer.readthedocs.io | `charset_normalizer_LICENSE.txt` |
| idna | 3.18 | BSD-3-Clause | https://github.com/kjd/idna | `idna_LICENSE.md` |

## 构建期组件（仅打包时使用，不随便携包分发）

| 组件 | 版本 | 许可 | 项目主页 |
| --- | --- | --- | --- |
| PyInstaller | 6.22.0 | GPL-2.0-or-later 带 **Bootloader Exception**（允许用它打包并分发自由或商业程序）；例外条款全文见 `pyinstaller_COPYING.txt` | https://pyinstaller.org |
| pyinstaller-hooks-contrib | 2026.6 | 标准 hooks 为 GPL-2.0-or-later，runtime hooks 为 Apache-2.0（其 wheel 内 `licenses/LICENSE` 全文含 GPL-2.0 与 Apache-2.0 两节） | https://github.com/pyinstaller/pyinstaller-hooks-contrib |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause | https://github.com/mhammond/pywin32 |
| altgraph | 0.17.5 | MIT | https://github.com/ronaldoussoren/altgraph |
| pefile | 2024.8.26 | MIT | https://github.com/erocarrera/pefile |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://packaging.pypa.io |
| setuptools | 84.0.0 | MIT | https://setuptools.pypa.io |

## 保留的许可文本与说明

- **LGPL-3.0 全文**：`licenses/lgpl-3.0.txt`（GNU Lesser General Public License
  v3，2007-06-29，取自 FSF 官方文本；LGPL-3.0 本身按条款并入 GPL-3.0 全文）。
- **GPL-3.0 全文**：`licenses/gpl-3.0.txt`（GNU General Public License v3，
  LGPL-3.0 引用之）。
- **Commercial 条款**：`PySide6_*_LicenseRef-Qt-Commercial.txt` 与
  `shiboken6_LicenseRef-Qt-Commercial.txt` 仅因 wheel 元数据引用而保留。
  **非当前采用路径，仅供参考**；本项目未持有商业 Qt 授权。
- **Qt 源码获取**：LGPL-3.0 要求随分发提供（或指引获取）对应版本的 Qt 源码。
  本项目对应 Qt 6.11.1（与 PySide6 6.11.1 一致），可到
  <https://download.qt.io/official_releases/qt/6.11/6.11.1/> 获取（选择与目标
  平台匹配的源码包）；PySide6 绑定源码见 <https://code.qt.io/cgit/pyside/pyside-setup.git>。
  用户替换/重编译 Qt 库的说明见仓库 `docs/qt-lgpl-compliance.md`。
- **PyInstaller 许可**：`pip show` 中 `License` 字段声明为
  "GPLv2-or-later with a special exception"，`licenses/pyinstaller_COPYING.txt`
  含 Bootloader Exception 全文（允许生成并分发自由或商业程序的可执行文件）。
- **待确认**：pyinstaller-hooks-contrib 的 `pip show` 未返回标准 `License` 字段；
  上表按 wheel 内 `licenses/LICENSE` 原文（标准 hooks GPL-2.0-or-later、
  runtime hooks Apache-2.0）填写，构建后请按实际 wheel 元数据核验。

## 本应用自身

PhoneVision Lab 本体以 MIT 许可开源（见仓库根目录 `LICENSE`）。本项目不构成法律
意见；如对许可义务有疑问，请咨询律师或查阅 Qt 官方许可说明
<https://doc.qt.io/qt-6/lgpl.html>。

---

*生成说明：本文件与 `licenses/` 内容由打包流程从已安装 wheel 元数据生成；
  构建后应复核一次版本与许可字段与锁文件一致。*
