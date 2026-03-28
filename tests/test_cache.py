"""Unit tests for ScanCache."""

import pickle
import tempfile
import time
import unittest
from pathlib import Path

from src.cache import ScanCache, _CACHE_VERSION
from src.models import FileNode


def _make_node(name="root", path="/root", size=1024):
    return FileNode(
        name=name,
        path=path,
        size=size,
        is_dir=True,
        mod_time=time.time(),
        create_time=time.time(),
    )


class TestScanCache(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache = ScanCache(cache_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ------------------------------------------------------------------
    # save / load round-trip
    # ------------------------------------------------------------------

    def test_save_and_load(self):
        node = _make_node(size=4096)
        self.cache.save("/dev/sda", node)
        loaded = self.cache.load("/dev/sda")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.size, 4096)

    def test_load_missing_returns_none(self):
        result = self.cache.load("/nonexistent/path")
        self.assertIsNone(result)

    def test_load_preserves_node_type(self):
        node = _make_node()
        self.cache.save("/test", node)
        loaded = self.cache.load("/test")
        self.assertIsInstance(loaded, FileNode)

    # ------------------------------------------------------------------
    # max_age_seconds
    # ------------------------------------------------------------------

    def test_load_fresh_entry_within_age(self):
        node = _make_node()
        self.cache.save("/test", node)
        loaded = self.cache.load("/test", max_age_seconds=3600)
        self.assertIsNotNone(loaded)

    def test_load_stale_entry_returns_none(self):
        node = _make_node()
        self.cache.save("/test", node)
        # Load with a max age of 0 seconds → should be stale immediately
        loaded = self.cache.load("/test", max_age_seconds=0)
        self.assertIsNone(loaded)

    # ------------------------------------------------------------------
    # invalidate / clear_all
    # ------------------------------------------------------------------

    def test_invalidate_removes_entry(self):
        self.cache.save("/test", _make_node())
        self.cache.invalidate("/test")
        self.assertIsNone(self.cache.load("/test"))

    def test_invalidate_missing_is_noop(self):
        # Should not raise
        self.cache.invalidate("/does/not/exist")

    def test_clear_all(self):
        self.cache.save("/a", _make_node(path="/a"))
        self.cache.save("/b", _make_node(path="/b"))
        self.cache.clear_all()
        self.assertIsNone(self.cache.load("/a"))
        self.assertIsNone(self.cache.load("/b"))

    # ------------------------------------------------------------------
    # cache_age_seconds
    # ------------------------------------------------------------------

    def test_cache_age_seconds(self):
        self.cache.save("/test", _make_node())
        age = self.cache.cache_age_seconds("/test")
        self.assertIsNotNone(age)
        self.assertGreaterEqual(age, 0)
        self.assertLess(age, 5)

    def test_cache_age_missing_returns_none(self):
        result = self.cache.cache_age_seconds("/missing")
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # Corrupt / incompatible cache
    # ------------------------------------------------------------------

    def test_corrupt_cache_returns_none(self):
        cache_file = self.cache._cache_path("/corrupt")
        cache_file.write_bytes(b"not valid pickle data!!!")
        result = self.cache.load("/corrupt")
        self.assertIsNone(result)

    def test_wrong_version_returns_none(self):
        node = _make_node()
        # Write with wrong version number
        payload = (999, time.time(), node)
        cache_file = self.cache._cache_path("/version_test")
        with open(cache_file, "wb") as fh:
            pickle.dump(payload, fh)
        result = self.cache.load("/version_test")
        self.assertIsNone(result)

    def test_wrong_type_in_payload_returns_none(self):
        payload = (_CACHE_VERSION, time.time(), "not a FileNode")
        cache_file = self.cache._cache_path("/type_test")
        with open(cache_file, "wb") as fh:
            pickle.dump(payload, fh)
        result = self.cache.load("/type_test")
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # Path escaping
    # ------------------------------------------------------------------

    def test_different_paths_different_files(self):
        self.cache.save("/path/a", _make_node(path="/path/a", size=10))
        self.cache.save("/path/b", _make_node(path="/path/b", size=20))
        a = self.cache.load("/path/a")
        b = self.cache.load("/path/b")
        self.assertEqual(a.size, 10)
        self.assertEqual(b.size, 20)

    def test_windows_style_path(self):
        node = _make_node(path="C:\\Users")
        self.cache.save("C:\\Users", node)
        loaded = self.cache.load("C:\\Users")
        self.assertIsNotNone(loaded)


if __name__ == "__main__":
    unittest.main()
