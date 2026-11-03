"""A cancelled or too-short training run must never yield a model package."""
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from pvl_export import export_model
from pvl_preprocess import PreprocessSpec
from pvl_train import TrainConfig


class ExportGateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pvl-qa-export-")
        self.output = self.temp.name
        self.model = os.path.join(self.output, "best.keras")
        with open(self.model, "wb") as fh:
            fh.write(b"incomplete training checkpoint")
        self.config = TrainConfig(class_names=["one", "two"])
        self.spec = PreprocessSpec(normalization="raw")

    def tearDown(self):
        self.temp.cleanup()

    def attempt(self):
        return export_model(self.model, self.config, self.spec, self.output,
                            os.path.join(self.output, "split.json"))

    def test_cancelled_run_without_history_is_rejected(self):
        result = self.attempt()
        self.assertFalse(result.success)
        self.assertIn("训练未完成", result.error)
        self.assertFalse(any(name.endswith(".pvlmodel.zip") for name in os.listdir(self.output)))

    def test_completed_history_with_too_few_steps_is_rejected(self):
        with open(os.path.join(self.output, "history.json"), "w", encoding="utf-8") as fh:
            json.dump({"total_steps": 4}, fh)
        result = self.attempt()
        self.assertFalse(result.success)
        self.assertIn("步数不足", result.error)


class ExportUiTest(unittest.TestCase):
    def test_export_runs_off_the_ui_thread(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication, QMessageBox
        from pvl_export import ExportResult
        from qt_client.i18n import Translator
        from qt_client.train_panel import TrainPanel

        app = QApplication.instance() or QApplication([])
        entered, release = threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory(prefix="pvl-qa-export-ui-") as root:
            panel = TrainPanel(Translator(initial_language="zh-CN"))
            panel._current_config = TrainConfig(dataset_root=root, class_names=["one", "two"])
            panel._current_spec = PreprocessSpec(normalization="raw")
            panel._current_output_dir = root
            panel._run_split_path = os.path.join(root, "split.json")
            with open(os.path.join(root, "best.keras"), "wb") as fh:
                fh.write(b"model")

            def fake_export(*_args, **_kwargs):
                entered.set()
                release.wait(5)
                return ExportResult(error="test failure")

            with patch("pvl_export.export_model", side_effect=fake_export), \
                    patch.object(QMessageBox, "critical"):
                try:
                    panel.on_export()
                    self.assertTrue(entered.wait(2))
                    self.assertTrue(panel.export_in_progress())
                    self.assertFalse(panel.start_button.isEnabled())
                    # The Qt event loop can still execute while export is blocked.
                    app.processEvents()
                finally:
                    release.set()
                panel._export_thread.join(5)
                deadline = time.monotonic() + 5
                while panel.export_in_progress() and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(0.01)
                self.assertFalse(panel.export_in_progress())
                panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
