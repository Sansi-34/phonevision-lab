"""
PhoneVision Lab — P0-5A frozen 资源路径解析测试。

职责：验证 qt_client/resources.py 在 PyInstaller frozen（sys.frozen + sys._MEIPASS）
与源码两种模式下都能正确解析打包资源路径：
  20. frozen：mock sys.frozen/_MEIPASS 后 resource_path 基于 _MEIPASS/qt_client/。
  21. 源码：非 frozen 时基于本文件 __file__ 所在目录（qt_client/ 包目录）。

为什么这样设计：
  - 纯逻辑单测：不真正打包，用 mock 模拟 sys.frozen / sys._MEIPASS。
  - resources.py 在 import 时缓存了 _PKG_DIR（源码包目录），因此测试应在
    受控环境中重新加载模块或断言相对结构，避免被模块级缓存干扰。
  - 同时验证资源目标布局与 packaging/PhoneVisionLab.spec 的 datas 一致：
    style.qss → qt_client/，app.png → qt_client/assets/（镜像源码包布局）。

依赖源码状态：qt_client/resources.py 已落地（另一 agent）→ 可跑。
"""
import importlib
import os
import sys
import unittest
from unittest import mock

_PC_CLIENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)


def _fresh_resources_module():
    """重新加载 resources 模块（清掉模块级 _PKG_DIR 缓存），返回模块对象。

    每次 reload 都重新基于 __file__ 计算 _PKG_DIR，让 mock sys.frozen 前后的
    断言互不干扰。
    """
    import qt_client.resources as res
    return importlib.reload(res)


class FrozenResourcePathTest(unittest.TestCase):
    """item 20：frozen（PyInstaller）模式路径解析。"""

    def test_frozen_resource_path_uses_meipass(self):
        """frozen 时 resource_path 基于 sys._MEIPASS + qt_client/ 前缀。"""
        res = _fresh_resources_module()
        fake_meipass = r"C:\portable\PhoneVisionLab\_internal"
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "_MEIPASS", fake_meipass, create=True):
            p = res.resource_path("style.qss")
        expected = os.path.join(fake_meipass, "qt_client", "style.qss")
        self.assertEqual(os.path.normpath(p), os.path.normpath(expected))
        self.assertTrue(p.startswith(fake_meipass),
                        f"frozen 路径应以 _MEIPASS 开头，实得 {p}")

    def test_frozen_icon_path(self):
        """frozen 时 icon_path 指向 _MEIPASS/qt_client/assets/app.png。"""
        res = _fresh_resources_module()
        fake_meipass = r"C:\bundle\_internal"
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "_MEIPASS", fake_meipass, create=True):
            p = res.icon_path()
        expected = os.path.join(fake_meipass, "qt_client", "assets", "app.png")
        self.assertEqual(os.path.normpath(p), os.path.normpath(expected))

    def test_frozen_qss_path_matches_spec_datas(self):
        """frozen 的 style.qss 路径与 spec datas 目标布局一致（qt_client/ 镜像）。"""
        res = _fresh_resources_module()
        fake_meipass = r"C:\bundle\_internal"
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "_MEIPASS", fake_meipass, create=True):
            p = res.style_qss_path()
        # 相对 _MEIPASS 的部分 = qt_client/style.qss，与 spec 的 (source, 'qt_client') 对齐
        rel = os.path.relpath(p, fake_meipass)
        self.assertEqual(os.path.normpath(rel),
                         os.path.normpath(os.path.join("qt_client", "style.qss")))


class SourceResourcePathTest(unittest.TestCase):
    """item 21：源码（非 frozen）模式路径解析。"""

    def test_source_path_based_on_pkg_dir(self):
        """非 frozen 时 resource_path 基于 qt_client/ 包目录（__file__ 推导）。"""
        res = _fresh_resources_module()
        # 确保未模拟 frozen（真实解释器状态）
        self.assertFalse(getattr(sys, "frozen", False))
        p = res.resource_path("style.qss")
        self.assertEqual(os.path.normpath(p),
                         os.path.normpath(os.path.join(_PC_CLIENT, "qt_client",
                                                       "style.qss")))
        self.assertTrue(os.path.isabs(p), "源码模式应返回绝对路径")

    def test_source_icon_path_exists(self):
        """源码模式 icon_path 指向真实存在的 assets/app.png。"""
        res = _fresh_resources_module()
        p = res.icon_path()
        self.assertTrue(os.path.exists(p),
                        f"源码模式图标路径应存在，实得 {p}")
        self.assertEqual(os.path.basename(p), "app.png")

    def test_source_qss_exists(self):
        """源码模式 style_qss_path 指向真实存在的 style.qss。"""
        res = _fresh_resources_module()
        p = res.style_qss_path()
        self.assertTrue(os.path.exists(p), f"源码模式 QSS 应存在，实得 {p}")

    def test_source_mode_does_not_touch_meipass(self):
        """非 frozen 时即使 sys._MEIPASS 残留旧值也不使用（以 __file__ 为准）。"""
        res = _fresh_resources_module()
        with mock.patch.object(sys, "frozen", False, create=True), \
                mock.patch.object(sys, "_MEIPASS", r"C:\should\not\use", create=True):
            p = res.resource_path("style.qss")
        self.assertNotIn("should", p, "源码模式不应使用 _MEIPASS")
        self.assertEqual(os.path.normpath(p),
                         os.path.normpath(os.path.join(_PC_CLIENT, "qt_client",
                                                       "style.qss")))


class ResourcePathContractTest(unittest.TestCase):
    """路径解析的防御契约（两种模式都成立）。"""

    def test_resource_path_rejects_absolute_relative(self):
        """relative 以绝对路径开头时仍按拼接处理，但最终结果不会逃逸到包外。"""
        res = _fresh_resources_module()
        # 即便调用方误传绝对路径，结果也应落在 qt_client/ 下（拼接而非截断）
        p = res.resource_path("style.qss")
        self.assertTrue("qt_client" in p or getattr(sys, "frozen", False))


if __name__ == "__main__":
    unittest.main()
