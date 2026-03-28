"""Unit tests for the FileSystemScanner."""

import os
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path

from src.scanner import FileSystemScanner, ScanCancelledError


class TestFileSystemScanner(unittest.TestCase):
    """Tests for FileSystemScanner using a temporary directory tree."""

    @classmethod
    def setUpClass(cls):
        """Create a small temporary directory tree for testing."""
        cls.tmpdir = tempfile.mkdtemp()
        cls._create_tree(cls.tmpdir)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    @classmethod
    def _create_tree(cls, root: str):
        """
        root/
          file_a.txt    (100 bytes)
          file_b.py     (200 bytes)
          subdir/
            nested.txt  (50 bytes)
            deep/
              deep.dat  (1000 bytes)
        """
        Path(root, "file_a.txt").write_bytes(b"x" * 100)
        Path(root, "file_b.py").write_bytes(b"y" * 200)
        sub = Path(root, "subdir")
        sub.mkdir()
        (sub / "nested.txt").write_bytes(b"z" * 50)
        deep = sub / "deep"
        deep.mkdir()
        (deep / "deep.dat").write_bytes(b"d" * 1000)

    def setUp(self):
        self.scanner = FileSystemScanner(max_workers=2)

    # ------------------------------------------------------------------
    # scan_directory
    # ------------------------------------------------------------------

    def test_scan_directory_returns_root_node(self):
        node = self.scanner.scan_directory(self.tmpdir)
        self.assertEqual(node.path, self.tmpdir)
        self.assertTrue(node.is_dir)

    def test_scan_directory_total_size(self):
        node = self.scanner.scan_directory(self.tmpdir)
        expected = 100 + 200 + 50 + 1000
        self.assertEqual(node.size, expected)

    def test_scan_directory_child_names(self):
        node = self.scanner.scan_directory(self.tmpdir)
        names = {child.name for child in node.children}
        self.assertIn("file_a.txt", names)
        self.assertIn("file_b.py", names)
        self.assertIn("subdir", names)

    def test_scan_directory_file_count(self):
        node = self.scanner.scan_directory(self.tmpdir)
        # 4 files total: file_a.txt, file_b.py, nested.txt, deep.dat
        self.assertEqual(node.file_count, 4)

    def test_scan_directory_nested_size(self):
        node = self.scanner.scan_directory(self.tmpdir)
        subdir = next(c for c in node.children if c.name == "subdir")
        expected_subdir = 50 + 1000
        self.assertEqual(subdir.size, expected_subdir)

    def test_scan_directory_max_depth_zero(self):
        node = self.scanner.scan_directory(self.tmpdir, max_depth=0)
        # At max_depth=0 we use fast_size instead of recursing
        # The node should have no children
        self.assertEqual(len(node.children), 0)

    def test_scan_directory_progress_callback(self):
        counts = []
        def cb(count, path):
            counts.append(count)
        self.scanner.scan_directory(self.tmpdir, progress_callback=cb)
        self.assertGreater(len(counts), 0)

    # ------------------------------------------------------------------
    # scan_directory_threaded
    # ------------------------------------------------------------------

    def test_scan_threaded_total_size(self):
        node = self.scanner.scan_directory_threaded(self.tmpdir)
        expected = 100 + 200 + 50 + 1000
        self.assertEqual(node.size, expected)

    def test_scan_threaded_returns_root(self):
        node = self.scanner.scan_directory_threaded(self.tmpdir)
        self.assertEqual(node.path, self.tmpdir)
        self.assertTrue(node.is_dir)

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    def test_cancel_raises(self):
        scanner = FileSystemScanner(max_workers=1)
        # Cancel the scan via the progress callback (simulates user cancelling during scan)
        def cancel_on_first_progress(count, path):
            scanner.cancel()

        # Ensure cancel flag is clear before starting
        scanner.reset_cancel()
        with self.assertRaises(ScanCancelledError):
            scanner.scan_directory(self.tmpdir, progress_callback=cancel_on_first_progress)

    def test_reset_cancel(self):
        scanner = FileSystemScanner(max_workers=1)
        scanner.cancel()
        scanner.reset_cancel()
        self.assertFalse(scanner._cancel_event.is_set())

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def test_missing_directory_returns_error_node(self):
        node = self.scanner.scan_directory("/nonexistent/path/xyz_12345")
        self.assertIsNotNone(node.error)

    # ------------------------------------------------------------------
    # get_folder_size
    # ------------------------------------------------------------------

    def test_get_folder_size(self):
        total = self.scanner.get_folder_size(self.tmpdir)
        expected = 100 + 200 + 50 + 1000
        self.assertEqual(total, expected)

    def test_get_folder_size_missing(self):
        total = self.scanner.get_folder_size("/nonexistent/xyz_99999")
        self.assertEqual(total, 0)

    # ------------------------------------------------------------------
    # list_disks
    # ------------------------------------------------------------------

    def test_list_disks_returns_list(self):
        disks = FileSystemScanner.list_disks()
        self.assertIsInstance(disks, list)
        self.assertGreater(len(disks), 0)

    # ------------------------------------------------------------------
    # Performance sanity check
    # ------------------------------------------------------------------

    def test_scan_performance(self):
        """Scanning the small test tree should complete in under 2 seconds."""
        start = time.time()
        self.scanner.scan_directory(self.tmpdir)
        elapsed = time.time() - start
        self.assertLess(elapsed, 2.0, f"Scan took too long: {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
