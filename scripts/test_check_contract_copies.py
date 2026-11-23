"""Database-free stdlib tests: python -m unittest discover -s scripts -p test_check_contract_copies.py."""

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from check_contract_copies import CONTRACT_FILES, MANIFEST, check

SCRIPT = Path(__file__).with_name("check_contract_copies.py").resolve()


class ContractCopiesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        entries = ["source: SaaS repo, commit 5fa72f7"]
        for name in CONTRACT_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            data = f"{name}\nArabic: مرحبا\n".encode("utf-8")
            path.write_bytes(data)
            entries.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
        self.manifest = self.root / MANIFEST
        self.manifest.write_text("\n".join(entries) + "\n", encoding="utf-8")

    def run_script(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root)],
            cwd=self.tmp.name,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_matching_hashes_pass(self) -> None:
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("contract copies OK", result.stdout)

    def test_crlf_checkout_passes(self) -> None:
        for name in (*CONTRACT_FILES, MANIFEST):
            path = self.root / name
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(check(self.root), [])

    def test_each_changed_file_fails_with_filename(self) -> None:
        for name in CONTRACT_FILES:
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(original + b"drift\r\n")
                result = self.run_script()
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"{name}: SHA256 mismatch", result.stderr)
                path.write_bytes(original)

    def test_missing_file_fails_with_filename(self) -> None:
        (self.root / CONTRACT_FILES[0]).unlink()
        self.assertIn(CONTRACT_FILES[0], "\n".join(check(self.root)))
        self.assertEqual(self.run_script().returncode, 1)

    def test_missing_manifest_fails(self) -> None:
        self.manifest.unlink()
        self.assertIn(MANIFEST, "\n".join(check(self.root)))
        self.assertEqual(self.run_script().returncode, 1)

    def test_missing_entry_fails_closed(self) -> None:
        lines = self.manifest.read_text(encoding="utf-8").splitlines()
        self.manifest.write_text("\n".join(lines[:-1]), encoding="utf-8")
        self.assertIn(f"{CONTRACT_FILES[-1]}: missing SHA256 entry", "\n".join(check(self.root)))

    def test_invalid_manifest_entries_fail_closed(self) -> None:
        original = self.manifest.read_text(encoding="utf-8")
        for entry in ("invalid", original.splitlines()[1], "0" * 64 + "  ../outside"):
            with self.subTest(entry=entry):
                self.manifest.write_text(original + entry + "\n", encoding="utf-8")
                self.assertTrue(check(self.root))

    def test_lone_cr_is_real_drift(self) -> None:
        path = self.root / CONTRACT_FILES[0]
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r"))
        self.assertIn("SHA256 mismatch", "\n".join(check(self.root)))


if __name__ == "__main__":
    unittest.main()
