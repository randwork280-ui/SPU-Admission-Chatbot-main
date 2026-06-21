import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_LOADER_DIR = ROOT / "Services" / "Data_Loader"
sys.path.insert(0, str(DATA_LOADER_DIR))

import metadata_utils


class DataLoaderMetadataTests(unittest.TestCase):
    def test_source_id_is_stable_and_versioned(self):
        first = metadata_utils.source_id("admission.md", "2026.1")
        second = metadata_utils.source_id("admission.md", "2026.1")
        changed = metadata_utils.source_id("admission.md", "2026.2")
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)
        self.assertEqual(len(first), 24)

    def test_sha256_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.md"
            path.write_text("hello", encoding="utf-8")
            digest = metadata_utils.sha256_file(path)
        self.assertEqual(digest, "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")

    def test_load_manifest_entries_indexes_by_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "documents": [
                            {
                                "source": "admission.md",
                                "language": "mixed",
                                "doc_category": "admission",
                                "version": "2026.1",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            entries = metadata_utils.load_manifest_entries_from_path(manifest_path)

        self.assertIn("admission.md", entries)
        self.assertEqual(entries["admission.md"]["doc_category"], "admission")


if __name__ == "__main__":
    unittest.main()
