"""Regression coverage for actual dataset creation and camera capture flows."""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from pvl_dataset import DatasetStore, list_datasets
from qt_client.dataset_panel import DatasetPanel
from qt_client.i18n import Translator


class DatasetPanelCaptureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pvl-qa-dataset-")
        self.env = patch.dict(os.environ, {"PVL_DATA_DIR": self.temp.name})
        self.env.start()
        self.number = 1
        self.frame = np.full((8, 8, 3), 80, dtype=np.uint8)
        self.panel = DatasetPanel(Translator(initial_language="zh-CN"),
                                  frame_provider=lambda: (self.frame, self.number))

    def tearDown(self):
        self.panel.on_stop_capture()
        self.panel.deleteLater()
        self.env.stop()
        self.temp.cleanup()

    def create(self, name):
        self.panel._ask_text = lambda *_: (name, True)
        self.panel.on_create_dataset()
        return self.panel.dataset_root()

    def test_new_datasets_are_distinct_and_discoverable(self):
        first = self.create("one")
        self.panel.class_input.setText("apple")
        self.panel.on_add_class()
        second = self.create("two")
        self.assertNotEqual(first, second)
        self.assertEqual({entry["root"] for entry in list_datasets()}, {first, second})
        self.assertEqual(DatasetStore(first).open(first).class_names(), ["apple"])

    def test_single_capture_creates_batch_and_ignores_duplicate_frame(self):
        self.create("capture")
        self.panel.class_input.setText("apple")
        self.panel.on_add_class()
        self.panel.on_single_capture()
        self.assertEqual(self.panel.store.dataset.count_images("apple"), 1)
        self.assertIsNone(self.panel.current_batch)
        self.panel.on_single_capture()
        self.assertEqual(self.panel.store.dataset.count_images("apple"), 1)
        self.assertIn("等待", self.panel.capture_status.text())
        self.number = 2
        self.panel.on_single_capture()
        self.assertEqual(self.panel.store.dataset.count_images("apple"), 2)
        self.assertEqual(len(self.panel.store.dataset.batches), 2)

    def test_burst_deduplicates_and_stops_when_camera_disconnects(self):
        self.create("burst")
        self.panel.class_input.setText("apple")
        self.panel.on_add_class()
        self.panel.on_start_capture()
        self.assertTrue(self.panel.is_capturing())
        self.assertFalse(self.panel.capture_class_combo.isEnabled())
        self.panel._on_capture_tick()
        self.panel._on_capture_tick()
        self.assertEqual(self.panel.store.dataset.count_images("apple"), 1)
        self.frame, self.number = None, None
        self.panel._on_capture_tick()
        self.assertFalse(self.panel.is_capturing())
        self.assertTrue(self.panel.capture_class_combo.isEnabled())
        self.assertIn("没有", self.panel.capture_status.text())

    def test_legacy_parent_dataset_remains_discoverable(self):
        root = os.path.join(self.temp.name, "datasets")
        legacy = DatasetStore(root)
        legacy.create("old", ["apple"])
        self.assertEqual([entry["root"] for entry in list_datasets()], [root])

    def test_workspace_actions_remain_reachable_on_a_small_window(self):
        from PySide6.QtWidgets import QScrollArea
        from qt_client.main_window import MainWindow

        window = MainWindow("http://127.0.0.1:1/stream", "http://127.0.0.1:1/ping", {})
        try:
            window.resize(960, 640)
            window.show()
            self.app.processEvents()
            scroll = window.tabs.widget(0)
            self.assertIsInstance(scroll, QScrollArea)
            self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
            scroll.ensureWidgetVisible(window.dataset_panel.split_button)
            self.app.processEvents()
            button = window.dataset_panel.split_button
            center = button.mapTo(scroll.viewport(), button.rect().center())
            self.assertTrue(scroll.viewport().rect().contains(center))
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
