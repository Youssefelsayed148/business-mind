"""Database-free stdlib tests: python -m unittest discover -s scripts -p test_check_instagram_frozen.py."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from check_instagram_frozen import FROZEN_FILES

SCRIPT = Path(__file__).with_name("check_instagram_frozen.py").resolve()


class FrozenFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.test")
        self.git("config", "user.name", "Test")
        for name in FROZEN_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {name}\n", encoding="utf-8")
        (self.root / "backend/app/other.py").write_text("x = 1\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def run_script(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *extra],
            capture_output=True, text=True, check=False,
        )

    def test_clean_tree_passes(self) -> None:
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("OK", result.stdout)

    def test_unrelated_change_passes(self) -> None:
        (self.root / "backend/app/other.py").write_text("x = 2\n", encoding="utf-8")
        self.git("commit", "-q", "-am", "other")
        self.assertEqual(self.run_script().returncode, 0)

    def test_unstaged_edit_fails(self) -> None:
        (self.root / FROZEN_FILES[0]).write_text("# edited\n", encoding="utf-8")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn(FROZEN_FILES[0], result.stdout)

    def test_committed_edit_fails(self) -> None:
        (self.root / FROZEN_FILES[2]).write_text("# edited\n", encoding="utf-8")
        self.git("commit", "-q", "-am", "edit")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn(FROZEN_FILES[2], result.stdout)

    def test_deleted_file_fails(self) -> None:
        (self.root / FROZEN_FILES[4]).unlink()
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing", result.stdout)

    def test_unknown_base_is_an_error(self) -> None:
        result = self.run_script("--base", "no-such-ref")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
