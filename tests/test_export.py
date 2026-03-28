"""Unit tests for ExportHandler."""

import csv
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from src.export import ExportHandler
from src.models import FileNode


def _make_tree():
    """Build a small FileNode tree for export tests.

    root/ (3000 bytes, 3 files)
      ├─ file_a.txt  (1000 bytes)
      ├─ subdir/     (2000 bytes)
      │    ├─ file_b.py  (1500 bytes)
      │    └─ file_c.log (500 bytes)
    """
    now = time.time()

    root = FileNode(
        name="root", path="/tmp/root", size=3000, is_dir=True,
        mod_time=now, create_time=now, file_count=3,
    )
    file_a = FileNode(
        name="file_a.txt", path="/tmp/root/file_a.txt", size=1000, is_dir=False,
        mod_time=now, create_time=now, file_count=0,
    )
    subdir = FileNode(
        name="subdir", path="/tmp/root/subdir", size=2000, is_dir=True,
        mod_time=now, create_time=now, file_count=2,
    )
    file_b = FileNode(
        name="file_b.py", path="/tmp/root/subdir/file_b.py", size=1500, is_dir=False,
        mod_time=now, create_time=now, file_count=0,
    )
    file_c = FileNode(
        name="file_c.log", path="/tmp/root/subdir/file_c.log", size=500, is_dir=False,
        mod_time=now, create_time=now, file_count=0,
    )
    subdir.add_child(file_b)
    subdir.add_child(file_c)
    root.add_child(file_a)
    root.add_child(subdir)
    return root


class TestExportCSV(unittest.TestCase):
    def setUp(self):
        self.exporter = ExportHandler()
        self.tree = _make_tree()

    def test_csv_string_contains_header(self):
        csv_str = self.exporter.export_csv_string(self.tree)
        self.assertIn("path", csv_str)
        self.assertIn("size_bytes", csv_str)

    def test_csv_string_contains_root(self):
        csv_str = self.exporter.export_csv_string(self.tree)
        self.assertIn("root", csv_str)

    def test_csv_string_contains_child(self):
        csv_str = self.exporter.export_csv_string(self.tree)
        self.assertIn("file_a.txt", csv_str)

    def test_csv_file_export(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as fh:
            tmp_path = fh.name
        try:
            self.exporter.export_csv(self.tree, tmp_path)
            self.assertTrue(os.path.exists(tmp_path))
            with open(tmp_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            # Should have root + 2 children at depth 1 + 2 children of subdir
            self.assertGreater(len(rows), 0)
            self.assertEqual(rows[0]["name"], "root")
        finally:
            os.unlink(tmp_path)

    def test_csv_size_bytes_field(self):
        csv_str = self.exporter.export_csv_string(self.tree, max_depth=0)
        reader = csv.DictReader(io.StringIO(csv_str))
        rows = list(reader)
        self.assertEqual(int(rows[0]["size_bytes"]), 3000)

    def test_csv_max_depth_zero_only_root(self):
        csv_str = self.exporter.export_csv_string(self.tree, max_depth=0)
        reader = csv.DictReader(io.StringIO(csv_str))
        rows = list(reader)
        # max_depth=0 → only root row
        self.assertEqual(len(rows), 1)


class TestExportJSON(unittest.TestCase):
    def setUp(self):
        self.exporter = ExportHandler()
        self.tree = _make_tree()

    def test_json_string_is_valid_json(self):
        json_str = self.exporter.export_json_string(self.tree)
        data = json.loads(json_str)
        self.assertIsInstance(data, dict)

    def test_json_root_name(self):
        json_str = self.exporter.export_json_string(self.tree)
        data = json.loads(json_str)
        self.assertEqual(data["name"], "root")

    def test_json_size_bytes(self):
        json_str = self.exporter.export_json_string(self.tree)
        data = json.loads(json_str)
        self.assertEqual(data["size_bytes"], 3000)

    def test_json_children_present(self):
        json_str = self.exporter.export_json_string(self.tree)
        data = json.loads(json_str)
        self.assertIn("children", data)
        self.assertEqual(len(data["children"]), 2)

    def test_json_children_sorted_by_size(self):
        json_str = self.exporter.export_json_string(self.tree)
        data = json.loads(json_str)
        # subdir (2000) should come before file_a.txt (1000)
        self.assertEqual(data["children"][0]["name"], "subdir")

    def test_json_file_export(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            tmp_path = fh.name
        try:
            self.exporter.export_json(self.tree, tmp_path)
            with open(tmp_path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["name"], "root")
        finally:
            os.unlink(tmp_path)

    def test_json_max_depth_zero_no_children(self):
        json_str = self.exporter.export_json_string(self.tree, max_depth=0)
        data = json.loads(json_str)
        self.assertNotIn("children", data)


class TestExportHTML(unittest.TestCase):
    def setUp(self):
        self.exporter = ExportHandler()
        self.tree = _make_tree()

    def test_html_string_contains_doctype(self):
        html = self.exporter.export_html_string(self.tree)
        self.assertIn("<!DOCTYPE html>", html)

    def test_html_string_contains_title(self):
        html = self.exporter.export_html_string(self.tree)
        self.assertIn("DiskExplorer Report", html)

    def test_html_string_contains_root_name(self):
        html = self.exporter.export_html_string(self.tree)
        self.assertIn("root", html)

    def test_html_string_contains_child_name(self):
        html = self.exporter.export_html_string(self.tree)
        self.assertIn("file_a.txt", html)

    def test_html_file_export(self):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as fh:
            tmp_path = fh.name
        try:
            self.exporter.export_html(self.tree, tmp_path)
            self.assertTrue(os.path.exists(tmp_path))
            content = Path(tmp_path).read_text(encoding="utf-8")
            self.assertIn("</html>", content)
        finally:
            os.unlink(tmp_path)

    def test_html_contains_size_human(self):
        html = self.exporter.export_html_string(self.tree)
        # 3000 bytes → should appear as something like "2.9 KB" or "3.0 KB"
        self.assertIn("KB", html)


if __name__ == "__main__":
    unittest.main()
