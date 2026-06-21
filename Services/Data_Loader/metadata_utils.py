from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for block in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_id(source: str, version: str) -> str:
    raw = f"{source}:{version}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def load_manifest_entries_from_path(manifest_path: Path) -> Dict[str, Dict[str, Any]]:
    if not manifest_path.exists():
        return {}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = manifest.get("documents", [])
    if not isinstance(documents, list):
        raise ValueError("Data manifest documents must be a list")

    entries: Dict[str, Dict[str, Any]] = {}
    for item in documents:
        if not isinstance(item, dict) or not item.get("source"):
            continue
        entries[str(item["source"])] = item
    return entries
