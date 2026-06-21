from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from langchain.text_splitter import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field

from text_utils import normalize_arabic_text


app = FastAPI(title="Data Splitting Service")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200

headers_to_split_on = [
    ("#", "header_1"),
    ("##", "header_2"),
    ("###", "header_3"),
    ("####", "header_4"),
]

header_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=headers_to_split_on,
    strip_headers=False,
)

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", " ", ""],
)


class DocumentModel(BaseModel):
    page_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    chunk_id: Optional[str] = None


CHUNKS_STORAGE: List[DocumentModel] = []


FACULTY_MAP = {
    "الصيدلة": ("Pharmacy", "الصيدلة"),
    "الطب البشري": ("Medicine", "الطب البشري"),
    "طب الأسنان": ("Dentistry", "طب الأسنان"),
    "العلوم الإدارية": ("Business", "العلوم الإدارية"),
    "هندسة الذكاء الاصطناعي": ("AI Engineering", "هندسة الذكاء الاصطناعي"),
    "هندسة البترول": ("Petroleum Engineering", "هندسة البترول"),
    "هندسة تكنولوجيا البناء والتشييد": (
        "Construction Engineering",
        "هندسة تكنولوجيا البناء والتشييد",
    ),
}


def _content_hash(content: str) -> str:
    normalized = normalize_arabic_text(content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _header_path(metadata: Dict[str, Any]) -> str:
    return " > ".join(
        str(metadata.get(f"header_{idx}", "")).strip()
        for idx in range(1, 5)
        if metadata.get(f"header_{idx}")
    )


def _stable_chunk_id(metadata: Dict[str, Any], chunk_index: int, content: str) -> str:
    source = str(metadata.get("source_id") or metadata.get("source") or "unknown-source")
    version = str(metadata.get("source_version") or metadata.get("version") or "unversioned")
    page = str(metadata.get("page") or metadata.get("page_number") or "")
    raw = "|".join(
        [
            source,
            version,
            page,
            _header_path(metadata),
            str(chunk_index),
            _content_hash(content)[:24],
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def enrich_faculty_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(metadata)
    header_text = normalize_arabic_text(" ".join(str(enriched.get(f"header_{idx}", "")) for idx in range(1, 5)))
    for keyword, (faculty, faculty_ar) in FACULTY_MAP.items():
        if keyword in header_text:
            enriched["faculty"] = faculty
            enriched["faculty_ar"] = faculty_ar
            break
    return enriched


def smart_split_markdown(content: str, source_metadata: Dict[str, Any], start_index: int):
    header_docs = header_splitter.split_text(content)
    final_chunks: List[DocumentModel] = []
    chunk_index = start_index

    for doc in header_docs:
        current_metadata = enrich_faculty_metadata({**source_metadata, **doc.metadata})
        sub_chunks = text_splitter.split_text(doc.page_content)

        for sub_chunk in sub_chunks:
            chunk_hash = _content_hash(sub_chunk)
            chunk_id = _stable_chunk_id(current_metadata, chunk_index, sub_chunk)
            chunk_metadata = {
                **current_metadata,
                "chunk_index": chunk_index,
                "chunk_hash": chunk_hash,
                "content_hash": chunk_hash,
                "header_path": _header_path(current_metadata),
                "chunk_size": len(sub_chunk),
                "splitter": "MarkdownHeaderAwareRecursive",
                "splitter_chunk_size": CHUNK_SIZE,
                "splitter_chunk_overlap": CHUNK_OVERLAP,
                "split_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            final_chunks.append(
                DocumentModel(
                    page_content=sub_chunk,
                    metadata=chunk_metadata,
                    chunk_id=chunk_id,
                )
            )
            chunk_index += 1

    return final_chunks, chunk_index


@app.post("/split")
def split_documents(documents: List[DocumentModel]):
    try:
        logger.info("Received %s documents for splitting", len(documents))
        all_chunks: List[DocumentModel] = []
        current_index = 0

        for doc in documents:
            chunks, current_index = smart_split_markdown(
                doc.page_content,
                doc.metadata,
                current_index,
            )
            all_chunks.extend(chunks)

        CHUNKS_STORAGE.clear()
        CHUNKS_STORAGE.extend(all_chunks)

        logger.info("Generated %s deterministic chunks", len(all_chunks))
        return {
            "success": True,
            "chunks": [chunk.model_dump() for chunk in all_chunks],
            "total_chunks": len(all_chunks),
        }
    except Exception as exc:
        logger.exception("Error during splitting")
        return {"success": False, "error": str(exc)}


@app.get("/all-chunks", response_model=Dict[str, Any])
def get_all_chunks():
    return {
        "total_count": len(CHUNKS_STORAGE),
        "chunks": [chunk.model_dump() for chunk in CHUNKS_STORAGE],
    }


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "Data Splitting"}


@app.get("/config")
def get_config():
    return {
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "headers_tracked": [header[1] for header in headers_to_split_on],
        "splitter_type": "MarkdownHeaderAwareRecursive",
        "deterministic_chunk_ids": True,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5002)
