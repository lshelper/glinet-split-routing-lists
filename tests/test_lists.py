from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_PATH = ROOT / "scripts" / "build.py"

spec = importlib.util.spec_from_file_location("build", BUILD_PATH)
build = importlib.util.module_from_spec(spec)
sys.modules["build"] = build
assert spec.loader is not None
spec.loader.exec_module(build)


class ListBuildTests(unittest.TestCase):
    def test_duplicate_source_entries_are_deduped(self) -> None:
        entries = [
            build.normalize_entry("Example.COM", "test", 1),
            build.normalize_entry("example.com", "test", 2),
        ]

        unique_entries, duplicates = build.dedupe_entries(entries)

        self.assertEqual([entry.value for entry in unique_entries], ["example.com"])
        self.assertEqual(list(duplicates), ["example.com"])

    def test_private_ipv4_entries_are_rejected(self) -> None:
        with self.assertRaisesRegex(build.ListError, "non-public IPv4"):
            build.normalize_entry("10.0.0.1", "test", 1)

    def test_compact_domains_keeps_parent_and_removes_covered_child(self) -> None:
        entries = [
            build.normalize_entry("api.example.com", "test", 1),
            build.normalize_entry("example.com", "test", 2),
            build.normalize_entry("another.example.net", "test", 3),
        ]
        unique_entries, _ = build.dedupe_entries(entries)

        compacted = build.compact_domains(unique_entries)

        self.assertEqual([entry.value for entry in compacted], ["another.example.net", "example.com"])

    def test_current_sources_build_without_validation_errors(self) -> None:
        outputs, manifest, errors = build.build_outputs()

        self.assertEqual(errors, [])
        self.assertTrue(outputs)
        self.assertGreater(manifest["lists"]["ru"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
