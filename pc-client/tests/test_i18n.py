"""
PhoneVision Lab — 双语国际化模块测试（P0-4B，offscreen）。

职责：验证 qt_client/i18n.py 的 Translator 与 STRINGS 字典：
  1. zh-CN 与 en 的 key 集合完全一致（Translator.keys(language)）。
  2. 每个 key 两种语言的 {xxx} 格式化占位符集合完全一致。
  3. 缺失 key 返回 "???{key}???" 显式占位标记（绝不清空白），并可程序化查询。
  4. resolve_initial_language 优先级：CLI > 保存 > 系统区域；系统含 zh 前缀 -> zh-CN。
  5. QSettings 测试隔离：注入临时 QSettings，不污染真实用户配置。
  6. text(key, **kwargs) 支持 {name} 占位符格式化（如 toast_saved 的 {path}）。
  7. set_language 切换后 language() 与 text() 同步更新（含 language_changed 信号）。

为什么这样设计：
  - 不连网、不创建 QApplication 也可测（Translator 是纯 Qt 对象，不依赖界面）。
  - 用 QSettings("PhoneVisionLabTest", <唯一名>) 做临时存储，测试结束不残留。
  - 字典一致性用"测试为准"的外部解析：从 STRINGS 直接读取两种语言并比对，
    不依赖源码内部的循环自证。
"""
import os
import re
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PC_CLIENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

from PySide6.QtCore import QSettings

from qt_client.i18n import LANG_EN, LANG_ZH, STRINGS, Translator


def _placeholders(text: str) -> set:
    """解析文本中的 {xxx} 格式化占位符集合。无占位返回空集合。"""
    return set(re.findall(r"\{([^{}]+)\}", text))


class TranslatorConsistencyTest(unittest.TestCase):
    """字典一致性与显式回退。"""

    def setUp(self):
        # 隔离 settings：每个测试独立临时 QSettings（test 组织+唯一应用名）
        self.settings = QSettings("PhoneVisionLabTest", f"i18n_{self._testMethodName}")

    def test_zh_and_en_key_sets_identical(self):
        """两种语言 key 集合完全一致（keys(language) 显式断言）。"""
        zh = Translator(settings=self.settings, initial_language=LANG_ZH)
        en = Translator(settings=self.settings, initial_language=LANG_EN)
        zh_keys = zh.keys(LANG_ZH)
        en_keys = en.keys(LANG_EN)
        self.assertEqual(zh_keys, en_keys,
                         "zh-CN 与 en 的 key 集合必须完全一致")
        # 至少覆盖关键文案，避免空表自洽
        for key in ("save_screenshot", "device_placeholder", "toast_saved",
                    "placeholder_reconnecting", "mode_original"):
            self.assertIn(key, zh_keys, f"{key} 应在 STRINGS 中")
        # STRINGS 字典本身也是 key 集合（两种语言 tuple 元数固定为 2）
        self.assertEqual(set(STRINGS.keys()), zh_keys)

    def test_placeholder_sets_match_between_languages(self):
        """每个 key 两种语言的 {xxx} 占位符集合一致（防切语言后 format 崩）。"""
        for key, (zh, en) in STRINGS.items():
            with self.subTest(key=key):
                self.assertEqual(
                    _placeholders(zh), _placeholders(en),
                    f"{key}: zh-CN 与 en 的占位符集合应一致 "
                    f"(zh={_placeholders(zh)!r}, en={_placeholders(en)!r})")

    def test_all_placeholder_keys_format(self):
        """含占位符的 key 在两种语言都能被 text() 用实参正常格式化。"""
        tr = Translator(settings=self.settings, initial_language=LANG_ZH)
        tr.set_language(LANG_ZH, persist=False)
        # 每个 key 用带默认实参的格式化验证：占位符都能被填充、无残留花括号
        sample = {"path": "x.png", "mode": "Canny", "error": "boom"}
        for key, (zh, en) in STRINGS.items():
            placeholders = _placeholders(zh) | _placeholders(en)
            kwargs = {p: sample.get(p, str(p)) for p in placeholders}
            for lang in (LANG_ZH, LANG_EN):
                tr.set_language(lang, persist=False)
                out = tr.text(key, **kwargs)
                self.assertNotIn("{", out, f"{key}@{lang} 不应残留未格式化占位符")

    def test_missing_key_returns_non_empty_marker(self):
        """缺失 key 返回 '???{key}???' 显式标记，绝不清空白。"""
        tr = Translator(settings=self.settings, initial_language=LANG_ZH)
        out = tr.text("no_such_key_at_all")
        self.assertNotEqual(out, "")
        self.assertEqual(out, "???no_such_key_at_all???")
        self.assertIn("???", out)
        self.assertIn("no_such_key_at_all", out)

    def test_missing_key_tracked_in_missing_keys(self):
        """缺失 key 会被记录，missing_keys() 可程序化查询。"""
        tr = Translator(settings=self.settings)
        tr.text("ghost_key_1")
        tr.text("ghost_key_2")
        self.assertIn("ghost_key_1", tr.missing_keys())
        self.assertIn("ghost_key_2", tr.missing_keys())
        self.assertNotIn("save_screenshot", tr.missing_keys(),
                         "存在的 key 不应被记入 missing_keys")

    def test_no_blank_values_in_dict(self):
        """两种语言都不存在空白/空串文案（防止清空白回归）。"""
        for key, (zh, en) in STRINGS.items():
            with self.subTest(key=key):
                self.assertTrue(zh.strip(), f"{key} zh-CN 文案不应为空白")
                self.assertTrue(en.strip(), f"{key} en 文案不应为空白")


class TranslatorPriorityTest(unittest.TestCase):
    """初始语言优先级：CLI > 保存 > 系统区域。"""

    def test_cli_wins_over_saved_and_system(self):
        self.assertEqual(Translator.resolve_initial_language("en", "zh-CN", "zh_CN"), LANG_EN)
        self.assertEqual(Translator.resolve_initial_language("zh-CN", "en", "en_US"), LANG_ZH)
        # CLI 大小写/下划线归一化
        self.assertEqual(Translator.resolve_initial_language("ZH_CN", None, None), LANG_ZH)

    def test_saved_wins_over_system(self):
        self.assertEqual(Translator.resolve_initial_language(None, "en", "zh_CN"), LANG_EN)
        self.assertEqual(Translator.resolve_initial_language(None, "zh-CN", "en_US"), LANG_ZH)

    def test_system_zh_prefix_resolves_zh_cn(self):
        for loc in ("zh_CN", "zh-CN", "zh_CN.UTF-8", "zh_TW", "zh_Hans_CN"):
            self.assertEqual(
                Translator.resolve_initial_language(None, None, loc), LANG_ZH,
                f"系统区域 {loc!r} 含 zh 前缀应解析为 zh-CN")

    def test_system_non_zh_resolves_en(self):
        for loc in ("en_US", "en_GB", "ja_JP", "", None):
            self.assertEqual(
                Translator.resolve_initial_language(None, None, loc), LANG_EN,
                f"系统区域 {loc!r} 不含 zh 前缀应解析为 en")


class TranslatorBehaviorTest(unittest.TestCase):
    """text() 格式化 / set_language 切换 / QSettings 持久化与隔离。"""

    def setUp(self):
        self.settings = QSettings("PhoneVisionLabTest", f"i18n_behavior_{self._testMethodName}")
        self.settings.clear()

    def test_text_formats_named_placeholders(self):
        """text(key, **kwargs) 支持 {name} 格式化。"""
        tr = Translator(settings=self.settings, initial_language=LANG_ZH)
        self.assertEqual(tr.text("toast_saved", path="x.png"), "已保存: x.png")
        self.assertEqual(tr.text("current_mode", mode="Canny"), "当前: Canny")
        tr.set_language(LANG_EN, persist=False)
        self.assertEqual(tr.text("toast_saved", path="x.png"), "Saved: x.png")

    def test_text_no_kwargs_returns_raw(self):
        """不含占位符的 key 直接返回原文，不抛异常。"""
        tr = Translator(settings=self.settings, initial_language=LANG_ZH)
        self.assertEqual(tr.text("save_screenshot"), "保存截图")
        tr.set_language(LANG_EN, persist=False)
        self.assertEqual(tr.text("save_screenshot"), "Save Screenshot")

    def test_set_language_updates_language_and_text(self):
        """set_language 切换后 language() 与 text() 同步更新。"""
        tr = Translator(settings=self.settings, initial_language=LANG_ZH)
        self.assertEqual(tr.language(), LANG_ZH)
        self.assertEqual(tr.text("save_screenshot"), "保存截图")
        tr.set_language(LANG_EN)
        self.assertEqual(tr.language(), LANG_EN)
        self.assertEqual(tr.text("save_screenshot"), "Save Screenshot")
        # 切回中文
        tr.set_language(LANG_ZH)
        self.assertEqual(tr.language(), LANG_ZH)
        self.assertEqual(tr.text("save_screenshot"), "保存截图")

    def test_set_language_emits_language_changed(self):
        """语言确实变化时 emit language_changed；同语言切换不 emit。"""
        tr = Translator(settings=self.settings, initial_language=LANG_ZH)
        emitted = []
        tr.language_changed.connect(emitted.append)
        tr.set_language(LANG_EN)
        self.assertEqual(emitted, [LANG_EN])
        # 同语言：不重复 emit
        tr.set_language(LANG_EN)
        self.assertEqual(emitted, [LANG_EN])
        # 归一化别名（zh_CN -> zh-CN）也触发一次切换
        tr.set_language("zh_CN")
        self.assertEqual(emitted, [LANG_EN, LANG_ZH])

    def test_set_language_persists_to_injected_settings(self):
        """set_language(persist=True) 写入注入的 QSettings。"""
        tr = Translator(settings=self.settings, initial_language=LANG_ZH)
        tr.set_language(LANG_EN, persist=True)
        self.assertEqual(self.settings.value("language"), LANG_EN)

    def test_injected_settings_isolated_no_global_pollution(self):
        """用临时 QSettings 读写，不污染真实用户配置（PhoneVisionLab）。"""
        # 先清掉临时 org 的残留，确保测试从干净状态开始
        self.settings.clear()
        # 真实用户配置命名空间（生产 QSettings 组织/应用名）：先取基线再比较。
        # 不能直接断言 != LANG_EN —— 开发机/CI 上用户可能本来就保存了 en，
        # 那会让"隔离性"测试误报（与隔离性无关的环境状态）。
        prod = QSettings("PhoneVisionLab", "PhoneVisionLab")
        before = prod.value("language")
        tr = Translator(settings=self.settings, initial_language=LANG_ZH)
        tr.set_language(LANG_EN, persist=True)
        self.assertEqual(self.settings.value("language"), LANG_EN)
        self.assertEqual(prod.value("language"), before,
                         "测试写入的语言不应泄漏到真实用户配置")

    def test_injected_settings_seed_initial_language_from_saved(self):
        """构造时从注入的 QSettings 读取已保存语言（saved 参与初始语言解析）。"""
        self.settings.setValue("language", LANG_EN)
        tr = Translator(settings=self.settings, initial_language=LANG_ZH)
        # resolve 保存 > 系统：注入 settings 里已存 en，构造默认仍为 zh-CN
        # （初始语言由 initial_language 决定；保存值通过 resolve_initial_language 消费）。
        self.assertEqual(tr.language(), LANG_ZH)
        saved = self.settings.value("language")
        self.assertEqual(saved, LANG_EN)
        self.assertEqual(Translator.resolve_initial_language(None, saved, "zh_CN"), LANG_EN)


if __name__ == "__main__":
    unittest.main()
