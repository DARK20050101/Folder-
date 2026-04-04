"""Unit tests for the data models module."""

import time
import unittest

from src.models import DiskDataModel, FileNode, format_size


class TestFormatSize(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(format_size(0), "0 B")
        self.assertEqual(format_size(500), "500.0 B")

    def test_kilobytes(self):
        result = format_size(1024)
        self.assertIn("KB", result)

    def test_megabytes(self):
        result = format_size(1024 * 1024)
        self.assertIn("MB", result)

    def test_gigabytes(self):
        result = format_size(1024 ** 3)
        self.assertIn("GB", result)

    def test_negative(self):
        self.assertEqual(format_size(-1), "0 B")


class TestFileNode(unittest.TestCase):
    def _make_node(self, name="root", path="/root", size=100,
                   is_dir=True, mod_time=None, create_time=None):
        return FileNode(
            name=name,
            path=path,
            size=size,
            is_dir=is_dir,
            mod_time=mod_time or time.time(),
            create_time=create_time or time.time(),
        )

    def test_formatted_size(self):
        node = self._make_node(size=2048)
        self.assertIn("KB", node.formatted_size)

    def test_extension_file(self):
        node = self._make_node(name="report.PDF", is_dir=False)
        self.assertEqual(node.extension, ".pdf")

    def test_extension_no_ext(self):
        node = self._make_node(name="Makefile", is_dir=False)
        self.assertEqual(node.extension, "")

    def test_extension_dir(self):
        node = self._make_node(name="mydir", is_dir=True)
        self.assertEqual(node.extension, "")

    def test_add_child(self):
        parent = self._make_node()
        child = self._make_node(name="child", path="/root/child", size=50)
        parent.add_child(child)
        self.assertEqual(len(parent.children), 1)
        self.assertIs(parent.children[0], child)

    def test_get_children_sorted_by_size(self):
        parent = self._make_node()
        small = self._make_node(name="small", size=10)
        large = self._make_node(name="large", size=999)
        parent.add_child(small)
        parent.add_child(large)
        sorted_children = parent.get_children_sorted("size")
        self.assertEqual(sorted_children[0].name, "large")
        self.assertEqual(sorted_children[1].name, "small")

    def test_get_children_sorted_by_name(self):
        parent = self._make_node()
        b = self._make_node(name="b")
        a = self._make_node(name="a")
        parent.add_child(b)
        parent.add_child(a)
        sorted_children = parent.get_children_sorted("name", reverse=False)
        self.assertEqual(sorted_children[0].name, "a")

    def test_get_children_sorted_invalid_key(self):
        parent = self._make_node()
        child = self._make_node(name="x", size=5)
        parent.add_child(child)
        # Should not raise, defaults to size
        result = parent.get_children_sorted("invalid_key")
        self.assertEqual(len(result), 1)

    def test_get_children_sorted_uses_cache(self):
        parent = self._make_node()
        parent.add_child(self._make_node(name="a", size=1))
        parent.add_child(self._make_node(name="b", size=2))

        first = parent.get_children_sorted("size", reverse=True)
        second = parent.get_children_sorted("size", reverse=True)

        self.assertIs(first, second)

    def test_add_child_invalidates_sorted_cache(self):
        parent = self._make_node()
        parent.add_child(self._make_node(name="a", size=1))
        before = parent.get_children_sorted("size", reverse=True)

        parent.add_child(self._make_node(name="b", size=2))
        after = parent.get_children_sorted("size", reverse=True)

        self.assertIsNot(before, after)
        self.assertEqual(after[0].name, "b")

    def test_iter_all(self):
        root = self._make_node(name="root", path="/r")
        child1 = self._make_node(name="c1", path="/r/c1")
        grandchild = self._make_node(name="gc", path="/r/c1/gc")
        child1.add_child(grandchild)
        root.add_child(child1)

        all_nodes = list(root.iter_all())
        names = [n.name for n in all_nodes]
        self.assertIn("root", names)
        self.assertIn("c1", names)
        self.assertIn("gc", names)
        self.assertEqual(len(all_nodes), 3)

    def test_find_existing(self):
        root = self._make_node(name="root", path="/r")
        child = self._make_node(name="c", path="/r/c")
        root.add_child(child)
        found = root.find("/r/c")
        self.assertIs(found, child)

    def test_find_missing(self):
        root = self._make_node(name="root", path="/r")
        self.assertIsNone(root.find("/does/not/exist"))

    def test_type_distribution(self):
        root = self._make_node(is_dir=True, size=0)
        py_file = self._make_node(name="a.py", path="/r/a.py", is_dir=False, size=100)
        txt_file = self._make_node(name="b.txt", path="/r/b.txt", is_dir=False, size=200)
        root.add_child(py_file)
        root.add_child(txt_file)

        dist = root.type_distribution()
        self.assertEqual(dist.get(".py"), 100)
        self.assertEqual(dist.get(".txt"), 200)

    def test_repr(self):
        node = self._make_node(name="mydir", size=1024, is_dir=True)
        r = repr(node)
        self.assertIn("Dir", r)
        self.assertIn("mydir", r)


class TestDiskDataModel(unittest.TestCase):
    def _make_node(self, name="root", path="/root"):
        return FileNode(name=name, path=path, size=100, is_dir=True,
                        mod_time=time.time(), create_time=time.time())

    def test_set_and_get_root(self):
        model = DiskDataModel()
        node = self._make_node()
        model.set_root("/", node)
        self.assertIs(model.get_root("/"), node)

    def test_get_missing(self):
        model = DiskDataModel()
        self.assertIsNone(model.get_root("/missing"))

    def test_remove(self):
        model = DiskDataModel()
        node = self._make_node()
        model.set_root("/", node)
        model.remove("/")
        self.assertIsNone(model.get_root("/"))

    def test_all_disks(self):
        model = DiskDataModel()
        model.set_root("/a", self._make_node(path="/a"))
        model.set_root("/b", self._make_node(path="/b"))
        disks = model.all_disks()
        self.assertIn("/a", disks)
        self.assertIn("/b", disks)

    def test_clear(self):
        model = DiskDataModel()
        model.set_root("/a", self._make_node(path="/a"))
        model.clear()
        self.assertEqual(len(model), 0)

    def test_len(self):
        model = DiskDataModel()
        self.assertEqual(len(model), 0)
        model.set_root("/a", self._make_node(path="/a"))
        self.assertEqual(len(model), 1)


if __name__ == "__main__":
    unittest.main()
