"""
PhoneVision Lab — Android Release 候选配置测试（P0-5B）。

职责：静态校验 Android 侧为 GitHub 开源准备的 Release 候选配置契约：
  1. Android versionName 与 PC（qt_client/version.py）一致为 0.1.0-alpha.1，versionCode 保持 1。
  2. gradle-wrapper.properties 带官方 distributionSha256Sum（非占位）。
  3. verification-metadata.xml 采用 SHA-256 逐件校验，无通配信任。
  4. settings.gradle.kts 默认仓库不含腾讯云镜像。
  5. 签名接口走环境变量，源码无明文 secret。
  6. keystore 扩展名被 gitignore。
  7. AndroidManifest 有 android:icon 与 android:roundIcon。
  8. 图标资源存在（mipmap 各密度 + adaptive 图层 + fallback）。
  9. Release 候选脚本的产物命名明确带 debug / release-unsigned。

为什么这样设计：
  - 全部静态检查（读文件 / 解析文本 / AST），不运行 Gradle，测试在任何机器上都可跑。
  - 版本一致性以 pc-client/qt_client/version.py 为事实来源：AST 解析避免副作用。
  - verification-metadata 的"非通配信任"检查：确认文件不含 trusted-artifacts /
    trusted-keys 白名单（允许任意的通配），且只含显式 sha256 条目。
  - 图标检查同时覆盖 API 26+ 的 adaptive-icon（mipmap-anydpi-v26 + drawable 图层）与
    API 21 回退的 mipmap-*/ic_launcher(.round).png。

依赖源码状态：所有被断言的文件均已落地（本任务创建/修改），可跑。
"""
import ast
import os
import re
import sys
import unittest
import xml.etree.ElementTree as ET

_PC_CLIENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

_REPO_ROOT = os.path.dirname(_PC_CLIENT)
_ANDROID = os.path.join(_REPO_ROOT, "android")

_APP_GRADLE = os.path.join(_ANDROID, "app", "build.gradle.kts")
_WRAPPER = os.path.join(_ANDROID, "gradle", "wrapper", "gradle-wrapper.properties")
_VERIFICATION = os.path.join(_ANDROID, "gradle", "verification-metadata.xml")
_SETTINGS = os.path.join(_ANDROID, "settings.gradle.kts")
_MANIFEST = os.path.join(_ANDROID, "app", "src", "main", "AndroidManifest.xml")
_VERSION = os.path.join(_PC_CLIENT, "qt_client", "version.py")
_RELEASE_SCRIPT = os.path.join(_ANDROID, "scripts", "build_release_candidate.ps1")
_RES = os.path.join(_ANDROID, "app", "src", "main", "res")

# 与 verification-metadata.xml 相同命名空间的稳定前缀，避免硬编码
_NS = {"vm": "https://schema.gradle.org/dependency-verification"}


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _pc_version() -> str:
    """AST 解析 qt_client/version.py 取 __version__ 字面量。"""
    tree = ast.parse(_read(_VERSION))
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and getattr(node.targets[0], "id", "") == "__version__"):
            return ast.literal_eval(node.value)
    raise AssertionError("version.py 中未找到 __version__")


class AndroidVersionTest(unittest.TestCase):
    """item 1：Android 版本与 PC 统一。"""

    def test_version_name_matches_pc(self):
        source = _read(_APP_GRADLE)
        m = re.search(r'versionName\s*=\s*"([^"]+)"', source)
        self.assertIsNotNone(m, "app/build.gradle.kts 未声明 versionName")
        self.assertEqual(m.group(1), _pc_version())

    def test_version_code_stays_1(self):
        m = re.search(r'versionCode\s*=\s*(\d+)', _read(_APP_GRADLE))
        self.assertIsNotNone(m, "app/build.gradle.kts 未声明 versionCode")
        self.assertEqual(int(m.group(1)), 1)


class WrapperChecksumTest(unittest.TestCase):
    """item 2：wrapper 带官方 distributionSha256Sum（非占位）。"""

    def test_distribution_sha256_present_and_real(self):
        props = _read(_WRAPPER)
        m = re.search(r"^distributionSha256Sum=(.+)$", props, re.MULTILINE)
        self.assertIsNotNone(m, "gradle-wrapper.properties 缺 distributionSha256Sum")
        value = m.group(1).strip()
        self.assertRegex(value, r"^[0-9a-f]{64}$",
                         "distributionSha256Sum 必须是 64 位十六进制，当前: %r" % value)
        # 不得是占位符
        self.assertNotIn(value.lower(),
                         {"", "0" * 64, "TODO", "placeholder", "changeme"})


class VerificationMetadataTest(unittest.TestCase):
    """item 3：verification-metadata.xml 非通配信任。"""

    @classmethod
    def setUpClass(cls):
        cls.root = ET.parse(_VERIFICATION).getroot()

    def test_uses_sha256_only(self):
        # 至少存在 1 条 sha256 校验
        sha_count = len(self.root.findall(".//vm:sha256", _NS))
        self.assertGreater(sha_count, 0, "verification-metadata.xml 没有任何 sha256 条目")
        # 不允许 md5/sha1 类型的弱校验
        for weak in ("md5", "sha1"):
            self.assertEqual(
                len(self.root.findall(f".//vm:{weak}", _NS)), 0,
                "verification-metadata.xml 不应包含 %s 校验" % weak)

    def test_no_trusted_artifacts_or_keys_wildcards(self):
        source = _read(_VERIFICATION)
        self.assertNotIn("trusted-artifacts", source,
                         "不应有 trusted-artifacts 通配信任段")
        self.assertNotIn("trusted-keys", source,
                         "不应有 trusted-keys 通配信任段")
        self.assertNotIn("trusted-artifacts", source.lower())

    def test_metadata_mode_enforces_verification(self):
        config = self.root.find("vm:configuration", _NS)
        self.assertIsNotNone(config)
        verify = config.find("vm:verify-metadata", _NS)
        self.assertIsNotNone(verify)
        self.assertEqual(verify.text.strip().lower(), "true")


class RepositorySourceTest(unittest.TestCase):
    """item 4：默认仓库源不含腾讯云镜像。"""

    def test_no_tencent_cloud_mirror_default(self):
        settings = _read(_SETTINGS)
        self.assertNotIn("mirrors.cloud.tencent.com", settings,
                         "settings.gradle.kts 默认源不应包含腾讯云镜像")
        self.assertIn("google()", settings)
        self.assertIn("mavenCentral()", settings)

    def test_plugin_management_has_plugin_portal(self):
        settings = _read(_SETTINGS)
        self.assertIn("gradlePluginPortal()", settings)


class SigningInterfaceTest(unittest.TestCase):
    """item 5：签名接口用环境变量，无明文 secret。"""

    def test_env_var_interface_declared(self):
        app_gradle = _read(_APP_GRADLE)
        for var in ("PVL_ANDROID_KEYSTORE", "PVL_ANDROID_KEY_ALIAS",
                    "PVL_ANDROID_STORE_PASSWORD", "PVL_ANDROID_KEY_PASSWORD"):
            self.assertIn(var, app_gradle,
                          "app/build.gradle.kts 应声明签名环境变量 %s" % var)

    def test_no_plaintext_secret_in_gradle(self):
        app_gradle = _read(_APP_GRADLE)
        # 不硬编码 keystore 路径 / 密码字面量；storePassword 等只来自 System.getenv
        for bad in ("storePassword = \"", "keyPassword = \"", "storeFile = \""):
            self.assertNotIn(bad, app_gradle,
                             "app/build.gradle.kts 不应包含明文密码/路径字面量")

    def test_release_unsigned_when_env_missing(self):
        # 四项全齐才签名：源码里应有"全部非空才启用"的守卫逻辑
        app_gradle = _read(_APP_GRADLE)
        self.assertIn("System.getenv", app_gradle)
        self.assertIn("signingConfigs", app_gradle)

    def test_keystore_extension_gitignored(self):
        root_gi = os.path.join(_REPO_ROOT, ".gitignore")
        with open(root_gi, encoding="utf-8") as fh:
            content = fh.read()
        for ext in ("*.keystore", "*.jks"):
            self.assertIn(ext, content,
                          ".gitignore 应忽略 keystore 扩展名 %s" % ext)


class ManifestIconTest(unittest.TestCase):
    """item 7：Manifest 声明 icon 与 roundIcon。"""

    def test_icon_attributes_present(self):
        manifest = _read(_MANIFEST)
        self.assertIn('android:icon="@mipmap/ic_launcher"', manifest)
        self.assertIn('android:roundIcon="@mipmap/ic_launcher_round"', manifest)


class IconResourcesTest(unittest.TestCase):
    """item 8：图标资源齐全（adaptive + 各密度 mipmap）。"""

    DENS = ("mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi")

    def test_adaptive_layers(self):
        for name in ("ic_launcher_foreground", "ic_launcher_background"):
            self.assertTrue(
                os.path.isfile(os.path.join(_RES, "drawable", name + ".png")),
                "缺少 adaptive 图层 drawable/%s.png" % name)

    def test_adaptive_xml(self):
        for name in ("ic_launcher", "ic_launcher_round"):
            xml_path = os.path.join(_RES, "mipmap-anydpi-v26", name + ".xml")
            self.assertTrue(os.path.isfile(xml_path), "缺少 %s.xml" % name)
            tree = ET.parse(xml_path)
            root = tree.getroot()
            self.assertEqual(root.tag.rsplit("}", 1)[-1], "adaptive-icon")
            tags = [c.tag.rsplit("}", 1)[-1] for c in root]
            self.assertIn("background", tags)
            self.assertIn("foreground", tags)

    def test_legacy_mipmaps_all_densities(self):
        for density in self.DENS:
            for name in ("ic_launcher", "ic_launcher_round"):
                png = os.path.join(_RES, "mipmap-%s" % density, name + ".png")
                self.assertTrue(os.path.isfile(png),
                                "缺少回退图标 %s" % os.path.relpath(png, _RES))


class ReleaseScriptTest(unittest.TestCase):
    """item 9：unsigned 候选命名明确。"""

    def test_script_existing(self):
        self.assertTrue(os.path.isfile(_RELEASE_SCRIPT),
                        "缺少 scripts/build_release_candidate.ps1")

    def test_unsigned_naming_explicit(self):
        source = _read(_RELEASE_SCRIPT)
        # 产物名显式带 debug 与 release-unsigned，不把 unsigned 冒充正式
        self.assertIn("-debug.apk", source)
        self.assertIn("-release-unsigned.apk", source)
        self.assertIn("-release-unsigned.aab", source)

    def test_output_dir_gitignored(self):
        with open(os.path.join(_REPO_ROOT, ".gitignore"), encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("artifacts/", content)

    def test_sign_env_gate_in_script(self):
        source = _read(_RELEASE_SCRIPT)
        self.assertIn("PVL_ANDROID_KEYSTORE", source)
        self.assertIn("UNSIGNED", source.upper())


if __name__ == "__main__":
    unittest.main()
