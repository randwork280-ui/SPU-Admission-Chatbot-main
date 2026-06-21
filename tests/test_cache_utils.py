import sys
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Services" / "QA_Chatting"))

from cache_utils import TTLCache, build_cache_key, document_signature, stable_json_hash


class CacheUtilsTests(unittest.TestCase):
    def test_stable_hash_ignores_dict_order(self):
        left = stable_json_hash({"query": "fees", "filters": {"faculty": "Medicine", "k": 8}})
        right = stable_json_hash({"filters": {"k": 8, "faculty": "Medicine"}, "query": "fees"})
        self.assertEqual(left, right)

    def test_cache_key_is_hashed_and_namespaced(self):
        key = build_cache_key("spu", "retrieval", {"query": "What are the fees?", "k": 8})
        self.assertTrue(key.startswith("spu:retrieval:"))
        self.assertEqual(len(key.rsplit(":", 1)[-1]), 64)
        self.assertNotIn("What are the fees?", key)

    def test_ttl_cache_hit_expire_and_evict(self):
        cache = TTLCache("test", ttl_seconds=60, max_entries=1)
        cache.set("a", 1)
        value, status = cache.get("a")
        self.assertEqual((value, status), (1, "hit"))

        cache.set("b", 2)
        value, status = cache.get("a")
        self.assertEqual(value, None)
        self.assertEqual(status, "miss")

        cache.set("c", 3, ttl_seconds=1)
        cache._items["c"].expires_at = time.time() - 1
        value, status = cache.get("c")
        self.assertEqual(value, None)
        self.assertEqual(status, "expired")

    def test_document_signature_uses_source_identity_not_content(self):
        docs = [
            {
                "content": "long source text that should not appear in cache key",
                "chunk_id": "chunk-1",
                "score": 0.81234567,
                "metadata": {
                    "source": "fees.md",
                    "source_id": "fees-2026",
                    "chunk_hash": "abc",
                    "ingested_at": "2026-06-21T00:00:00Z",
                },
            }
        ]
        signature = document_signature(docs)
        self.assertEqual(len(signature), 64)
        self.assertNotIn("long source text", signature)


if __name__ == "__main__":
    unittest.main()
