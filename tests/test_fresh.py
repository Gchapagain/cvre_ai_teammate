"""Tests for app/fresh.py, which stops a running app from mixing old and new code."""

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

from app import fresh


class TestEnsureFresh(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "app" / "views").mkdir(parents=True)
        (self.root / "services").mkdir()
        self.files = [self.root / "db.py", self.root / "app" / "style.py",
                      self.root / "app" / "views" / "ask_ai.py", self.root / "services" / "qa.py"]
        for path in self.files:
            path.write_text("# made-up module")
        saved_seen, saved_modules = dict(fresh._seen), dict(sys.modules)
        fresh._seen.clear()

        def restore():
            fresh._seen.clear()
            fresh._seen.update(saved_seen)
            sys.modules.update(saved_modules)
        self.addCleanup(restore)

    def change(self, path):
        later = path.stat().st_mtime + 10
        os.utime(path, (later, later))

    def test_first_call_and_unchanged_files_drop_nothing(self):
        self.assertFalse(fresh.ensure(self.root))
        self.assertFalse(fresh.ensure(self.root))

    def test_a_changed_file_anywhere_is_noticed_once(self):
        for path in self.files:
            with self.subTest(path.name):
                fresh.ensure(self.root)
                self.change(path)
                self.assertTrue(fresh.ensure(self.root))
                self.assertFalse(fresh.ensure(self.root))

    def test_a_new_file_is_noticed(self):
        fresh.ensure(self.root)
        (self.root / "app" / "views" / "assistant.py").write_text("# new screen")
        self.assertTrue(fresh.ensure(self.root))

    def test_all_of_our_modules_are_forgotten_together_and_nothing_else(self):
        ours = ["db", "app", "app.style", "app.views.ask_ai", "services", "services.qa"]
        for name in ours:
            sys.modules[name] = types.ModuleType(name)
        sys.modules["application_helper"] = types.ModuleType("application_helper")
        self.addCleanup(sys.modules.pop, "application_helper", None)
        fresh.ensure(self.root)
        self.change(self.files[2])
        fresh.ensure(self.root)
        for name in ours:
            self.assertNotIn(name, sys.modules)
        self.assertIn("application_helper", sys.modules)
        self.assertIn("streamlit", sys.modules)


if __name__ == "__main__":
    unittest.main()
