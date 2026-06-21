from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


def normalize_cache_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def stable_json_hash(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_cache_key(namespace: str, cache_type: str, payload: Mapping[str, Any]) -> str:
    digest = stable_json_hash(payload)
    return f"{namespace}:{cache_type}:{digest}"


def document_signature(documents: Iterable[Mapping[str, Any]]) -> str:
    identities: List[Dict[str, Any]] = []
    for index, document in enumerate(documents):
        metadata = document.get("metadata") or {}
        identities.append(
            {
                "index": index,
                "chunk_id": document.get("chunk_id"),
                "source": metadata.get("source"),
                "source_id": metadata.get("source_id"),
                "chunk_hash": metadata.get("chunk_hash"),
                "content_hash": metadata.get("content_hash"),
                "ingested_at": metadata.get("ingested_at"),
                "score": round(float(document.get("score", 0.0)), 6),
            }
        )
    return stable_json_hash({"documents": identities})


@dataclass
class CacheEntry:
    value: Any
    expires_at: float
    created_at: float


class TTLCache:
    def __init__(self, name: str, ttl_seconds: int, max_entries: int = 1024) -> None:
        self.name = name
        self.ttl_seconds = max(ttl_seconds, 1)
        self.max_entries = max(max_entries, 1)
        self._items: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0
        self.sets = 0
        self.evictions = 0

    def get(self, key: str) -> Tuple[Optional[Any], str]:
        now = time.time()
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                self.misses += 1
                return None, "miss"
            if entry.expires_at <= now:
                self._items.pop(key, None)
                self.evictions += 1
                self.misses += 1
                return None, "expired"
            self.hits += 1
            return entry.value, "hit"

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        ttl = max(ttl_seconds or self.ttl_seconds, 1)
        now = time.time()
        with self._lock:
            self._items[key] = CacheEntry(value=value, created_at=now, expires_at=now + ttl)
            self.sets += 1
            self._evict_if_needed()

    def clear(self) -> int:
        with self._lock:
            count = len(self._items)
            self._items.clear()
            return count

    def prune(self) -> int:
        now = time.time()
        with self._lock:
            expired_keys = [key for key, entry in self._items.items() if entry.expires_at <= now]
            for key in expired_keys:
                self._items.pop(key, None)
            self.evictions += len(expired_keys)
            return len(expired_keys)

    def stats(self) -> Dict[str, Any]:
        self.prune()
        with self._lock:
            requests = self.hits + self.misses
            return {
                "name": self.name,
                "items": len(self._items),
                "max_entries": self.max_entries,
                "ttl_seconds": self.ttl_seconds,
                "hits": self.hits,
                "misses": self.misses,
                "sets": self.sets,
                "evictions": self.evictions,
                "hit_rate": round(self.hits / requests, 4) if requests else 0.0,
            }

    def _evict_if_needed(self) -> None:
        overflow = len(self._items) - self.max_entries
        if overflow <= 0:
            return
        oldest_keys = sorted(self._items, key=lambda key: self._items[key].created_at)[:overflow]
        for key in oldest_keys:
            self._items.pop(key, None)
        self.evictions += len(oldest_keys)
