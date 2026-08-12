# Qt / PySide6 LGPL-3.0 合规说明

本文件记录 PhoneVision Lab Windows 便携包对 Qt 与 PySide6 的许可路径选择与
合规安排，面向**发布前门禁 P0-5B**。本工程记录**不构成法律意见**；如对许可义务
有疑问，请咨询律师或查阅 Qt 官方许可说明 <https://doc.qt.io/qt-6/lgpl.html>。

## 1. 采用的许可路径

- 本项目使用 **Qt 6.11.1**（随 PySide6 6.11.1 分发）与 **PySide6 6.11.1**。
- 本项目选择 **LGPL-3.0** 条款（Community Edition）。
- 依据：PyPI 上 PySide6/PySide6_Essentials/PySide6_Addons/shiboken6 的官方
  wheel 元数据（`*.dist-info/METADATA`）一致声明：

  ```
  License: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only
  ```

  即该分发可选 LGPL-3.0 / GPL-2.0 / GPL-3.0 任一条款。LGPL-3.0 允许在满足
  「动态链接 + 可替换库 + 可获取源码」等条件下用于闭源/商业程序，也天然适合
  本 MIT 开源项目，故采用 LGPL-3.0。

> **注意**：wheel 同时携带 `LicenseRef-Qt-Commercial.txt`（商业条款）是元数据
> 引用所需，**不代表本项目采用商业 Qt 授权**。商业文本仅作保留参考，
> 明确标注"非当前采用路径"（见 `pc-client/packaging/THIRD_PARTY_NOTICES.md`）。

## 2. 精确版本

| 组件 | 版本 |
| --- | --- |
| PySide6 | 6.11.1 |
| PySide6_Essentials | 6.11.1 |
| PySide6_Addons | 6.11.1 |
| shiboken6 | 6.11.1 |
| Qt（随 PySide6 分发） | 6.11.1 |

以上与 `pc-client/packaging/requirements-windows.lock` 锁定版本一致；构建时以
锁文件为准（构建流程见 `pc-client/scripts/build_windows.ps1`）。

## 3. 动态链接 / 库位置

- Qt 库以 **DLL 形式动态链接** 分发：PyInstaller onedir 包内
  `PhoneVisionLab/`（由 PySide6 官方 hook 收集），典型文件：
  `Qt6Core.dll`、`Qt6Gui.dll`、`Qt6Widgets.dll`、`Qt6Network.dll` 等位于
  PySide6 安装目录（构建 venv 的 `site-packages/PySide6/`），经 PyInstaller
  收集进包内与 EXE 同级（`_internal/PySide6/` 或按 onedir 布局）。
- 应用通过 shiboken6/PySide6 绑定在运行时动态加载 Qt DLL，**不静态链接、
  不修改 Qt 库本身**。

## 4. 源码获取

LGPL-3.0 要求随分发提供（或以可获取方式指引）对应版本的 Qt 源码。本项目：

- Qt 源码（版本 6.11.1，与随包 DLL 一致）：
  <https://download.qt.io/official_releases/qt/6.11/6.11.1/>
  （选择与目标平台匹配的源码包，如 `qtbase-everywhere-src-6.11.1.tar.xz` 等）。
- Qt for Python / PySide6 源码：
  <https://code.qt.io/cgit/pyside/pyside-setup.git/>（tag `v6.11.1`）。
- 许可全文随包分发：`licenses/lgpl-3.0.txt`、`licenses/gpl-3.0.txt`。

## 5. 用户替换 / 重编译 Qt 库的说明

便携包采用 PyInstaller onedir，Qt DLL 全部位于包内目录。用户如希望替换或
重编译 Qt 库，可：

1. 从上方 Qt 源码（6.11.1）编译，产出同名 DLL（如 `Qt6Core.dll`）。
2. 替换包内对应 DLL（保持同名、保持与 EXE 同级或原相对位置）。
3. 需满足 LGPL 的接口兼容性要求（ABI 兼容）；PySide6 绑定以同一版本构建时
   通常兼容。若替换后出现加载失败，说明 ABI 不匹配，请使用与 PySide6 6.11.1
   对应的 Qt 6.11.1 重新编译。
4. 如修改了 Qt 库源码，按 LGPL-3.0 条款，修改后的库本身需以 LGPL-3.0 发布并
   提供对应源码（见 `licenses/lgpl-3.0.txt` 第 2、4 节）。

本项目应用层（MIT）与 Qt 库之间是动态链接关系，应用自身源码不受 LGPL 传染。

## 6. 随包文件核对清单

- `licenses/lgpl-3.0.txt`（GNU LGPL v3 全文）
- `licenses/gpl-3.0.txt`（GNU GPL v3 全文，LGPL-3.0 引用之）
- `licenses/PySide6_*_LicenseRef-Qt-Commercial.txt` 与
  `licenses/shiboken6_LicenseRef-Qt-Commercial.txt`（商业条款，**保留参考，
  非当前采用路径**）
- `THIRD_PARTY_NOTICES.md`（版本/许可总表，含上述获取方式说明）

## 7. 限制与备注

- 本项目不构成法律意见；LGPL 合规责任最终由发布方/用户依据自身使用场景承担。
- Qt 的 LGPL 使用还有额外约束（如对 Qt 库修改的源码提供、标识保留等），
  详见 Qt 官方 <https://doc.qt.io/qt-6/lgpl.html> 与 LGPL-3.0 全文。
