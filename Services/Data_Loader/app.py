from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from admin_security import (
    AdminLoginRequest,
    AdminLoginResponse,
    create_admin_token,
    require_admin,
    verify_password,
)
from metadata_utils import load_manifest_entries_from_path, sha256_file, source_id
from text_utils import normalize_arabic_text


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Data Loader Service")


def get_cors_origins() -> List[str]:
    raw_origins = os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


DATA_PATH = Path(os.getenv("DATA_PATH", "/app/data"))
MANIFEST_PATH = DATA_PATH / "manifest.json"
SPLITTING_SERVICE_URL = os.getenv("SPLITTING_SERVICE_URL", "http://data-splitting:5002")
EMBEDDING_STORE_URL = os.getenv("EMBEDDING_STORE_URL", "http://embedding-store:5003")


class DocumentModel(BaseModel):
    page_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    chunk_id: Optional[str] = None


class LoadRequest(BaseModel):
    collection_name: str = "arabic_university_docs"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_file(path: Path) -> str:
    return sha256_file(path)


def _source_id(source: str, version: str) -> str:
    return source_id(source, version)


def load_manifest_entries() -> Dict[str, Dict[str, Any]]:
    try:
        return load_manifest_entries_from_path(MANIFEST_PATH)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid Data manifest JSON: {exc}",
        ) from exc


def extract_metadata_from_filename(filename: str) -> Dict[str, str]:
    """Best-effort metadata fallback when a manifest entry is missing."""
    metadata: Dict[str, str] = {}
    normalized_filename = normalize_arabic_text(filename).lower()

    faculty_map = {
        "الصيدلة": ("Pharmacy", "الصيدلة"),
        "pharmacy": ("Pharmacy", "الصيدلة"),
        "الطب البشري": ("Medicine", "الطب البشري"),
        "medicine": ("Medicine", "الطب البشري"),
        "طب الأسنان": ("Dentistry", "طب الأسنان"),
        "dentistry": ("Dentistry", "طب الأسنان"),
        "العلوم الإدارية": ("Business", "العلوم الإدارية"),
        "business": ("Business", "العلوم الإدارية"),
        "هندسة الذكاء الاصطناعي": ("AI Engineering", "هندسة الذكاء الاصطناعي"),
        "ai engineering": ("AI Engineering", "هندسة الذكاء الاصطناعي"),
        "هندسة البترول": ("Petroleum Engineering", "هندسة البترول"),
        "petroleum": ("Petroleum Engineering", "هندسة البترول"),
        "هندسة تكنولوجيا البناء والتشييد": (
            "Construction Engineering",
            "هندسة تكنولوجيا البناء والتشييد",
        ),
        "construction": ("Construction Engineering", "هندسة تكنولوجيا البناء والتشييد"),
    }

    category_map = {
        "الخطة الدراسية": "curriculum",
        "curriculum": "curriculum",
        "توصيف المقررات": "courses_descriptions",
        "course": "courses_descriptions",
        "الرسوم": "fees",
        "fees": "fees",
        "معدلات": "admission",
        "قبول": "admission",
        "admission": "admission",
        "رؤية": "faculty_info",
        "كلية": "faculty_info",
        "faculty": "faculty_info",
        "القرار": "regulation",
        "regulation": "regulation",
        "معلومات التواصل": "uni_info",
        "معلومات الجامعة": "uni_info",
        "contact": "uni_info",
        "متطلبات الجامعة": "req_courses",
        "requirements": "req_courses",
    }

    for keyword, (faculty, faculty_ar) in faculty_map.items():
        if keyword in normalized_filename:
            metadata["faculty"] = faculty
            metadata["faculty_ar"] = faculty_ar
            break

    for keyword, category in category_map.items():
        if keyword in normalized_filename:
            metadata["doc_category"] = category
            break

    metadata["doc_category"] = metadata.get("doc_category", "general")
    return metadata


def build_document_metadata(file_path: Path, manifest_entries: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    source = file_path.name
    manifest_metadata = deepcopy(manifest_entries.get(source, {}))
    fallback_metadata = extract_metadata_from_filename(source)
    file_checksum = _sha256_file(file_path)
    version = str(manifest_metadata.get("version") or "unversioned")

    expected_checksum = str(manifest_metadata.get("checksum") or "").strip()
    checksum_status = "not_declared"
    if expected_checksum and expected_checksum != "replace-with-sha256":
        checksum_status = "match" if expected_checksum == file_checksum else "mismatch"

    metadata: Dict[str, Any] = {
        "source": source,
        "source_id": _source_id(source, version),
        "source_version": version,
        "document_type": "university_data",
        "format": "markdown",
        "file_size": file_path.stat().st_size,
        "content_checksum": file_checksum,
        "checksum_status": checksum_status,
        "manifest_used": source in manifest_entries,
        "loaded_at": _utc_now(),
        **fallback_metadata,
    }

    for key in (
        "language",
        "faculty",
        "faculty_ar",
        "doc_category",
        "version",
        "official_date",
        "visibility",
        "owner",
        "review_status",
    ):
        if key in manifest_metadata and manifest_metadata[key] is not None:
            metadata[key] = manifest_metadata[key]

    return metadata


def load_md_file(file_path: Path) -> str:
    try:
        content = file_path.read_text(encoding="utf-8")
        logger.info("Loaded Markdown file: %s", file_path.name)
        return content
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{file_path.name} is not valid UTF-8",
        ) from exc


def iter_markdown_files() -> List[Path]:
    if not DATA_PATH.exists() or not DATA_PATH.is_dir():
        raise HTTPException(status_code=404, detail=f"Data folder not found at {DATA_PATH}")
    return sorted(file for file in DATA_PATH.iterdir() if file.is_file() and file.suffix.lower() == ".md")


def collect_documents() -> List[Dict[str, Any]]:
    manifest_entries = load_manifest_entries()
    all_docs: List[Dict[str, Any]] = []

    for file_path in iter_markdown_files():
        md_content = load_md_file(file_path)
        all_docs.append(
            {
                "page_content": md_content,
                "metadata": build_document_metadata(file_path, manifest_entries),
            }
        )

    return all_docs


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "message": "Data Loader service is running",
        "data_path": str(DATA_PATH),
        "data_path_exists": DATA_PATH.exists(),
        "manifest_path": str(MANIFEST_PATH),
        "manifest_exists": MANIFEST_PATH.exists(),
    }


@app.post("/admin/login", response_model=AdminLoginResponse)
def admin_login(request: AdminLoginRequest):
    if not verify_password(request.password):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    expires_in = int(os.getenv("ADMIN_TOKEN_TTL_SECONDS", "3600"))
    return AdminLoginResponse(
        access_token=create_admin_token(expires_in),
        expires_in=expires_in,
    )


@app.get("/scan", dependencies=[Depends(require_admin)])
def scan_data_folder():
    files = []
    manifest_entries = load_manifest_entries()

    for file in iter_markdown_files():
        metadata = build_document_metadata(file, manifest_entries)
        files.append(
            {
                "name": file.name,
                "size_bytes": file.stat().st_size,
                "type": "markdown",
                "metadata": metadata,
            }
        )

    missing_manifest_sources = sorted(
        source for source in manifest_entries if not (DATA_PATH / source).exists()
    )

    return {
        "success": True,
        "total_files": len(files),
        "files": files,
        "missing_manifest_sources": missing_manifest_sources,
    }


@app.get("/load", dependencies=[Depends(require_admin)])
def load_documents():
    all_docs = collect_documents()
    if not all_docs:
        return {
            "success": False,
            "message": "No Markdown documents found or loaded",
        }

    preview = all_docs[0]["page_content"][:300]
    return {
        "success": True,
        "total_documents": len(all_docs),
        "preview_first_document": preview,
        "loaded_files": [
            {
                "file": doc["metadata"]["source"],
                "assigned_metadata": {
                    "faculty": doc["metadata"].get("faculty"),
                    "category": doc["metadata"].get("doc_category"),
                    "source_id": doc["metadata"].get("source_id"),
                    "source_version": doc["metadata"].get("source_version"),
                    "manifest_used": doc["metadata"].get("manifest_used"),
                    "checksum_status": doc["metadata"].get("checksum_status"),
                },
            }
            for doc in all_docs
        ],
        "stats": {
            "avg_char_length": sum(len(doc["page_content"]) for doc in all_docs) / len(all_docs),
            "total_size_bytes": sum(doc["metadata"]["file_size"] for doc in all_docs),
        },
    }


@app.get("/get-all-documents", dependencies=[Depends(require_admin)])
def get_all_documents():
    documents = collect_documents()
    return {
        "success": True,
        "documents": documents,
        "total_documents": len(documents),
    }


@app.post("/auto-pipeline", dependencies=[Depends(require_admin)])
def auto_pipeline(
    dry_run: bool = False,
    authorization: Optional[str] = Header(default=None),
):
    try:
        logger.info("Step 1: Loading Markdown documents")
        all_docs_response = get_all_documents()
        documents = all_docs_response["documents"]

        if not documents:
            return {"success": False, "message": "No Markdown documents found"}

        logger.info("Step 2: Sending %s documents to splitting service", len(documents))
        split_response = requests.post(
            f"{SPLITTING_SERVICE_URL}/split",
            json=documents,
            timeout=120,
        )
        if split_response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Splitting failed: {split_response.text}",
            )

        split_result = split_response.json()
        if not split_result.get("success"):
            raise HTTPException(
                status_code=502,
                detail=f"Splitting service error: {split_result}",
            )

        split_docs = split_result["chunks"]
        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "original_documents": len(documents),
                "split_chunks": len(split_docs),
                "sample_chunk_ids": [chunk.get("chunk_id") for chunk in split_docs[:5]],
            }

        logger.info("Step 3: Sending %s chunks to embedding service", len(split_docs))
        headers = {"Authorization": authorization} if authorization else {}
        embed_response = requests.post(
            f"{EMBEDDING_STORE_URL}/embed-and-store",
            json={"documents": split_docs, "replace_source_chunks": True},
            headers=headers,
            timeout=1200,
        )
        if embed_response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Embedding failed: {embed_response.text}",
            )

        embed_result = embed_response.json()
        if not embed_result.get("success"):
            raise HTTPException(
                status_code=502,
                detail=f"Embedding service error: {embed_result}",
            )

        return {
            "success": True,
            "message": "Complete pipeline executed successfully",
            "original_documents": len(documents),
            "split_chunks": len(split_docs),
            "stored_in_vector_db": embed_result.get("stored_count", len(split_docs)),
            "sources_replaced": embed_result.get("sources_replaced", []),
            "steps_completed": ["loading_markdown", "splitting", "embedding", "storage"],
        }
    except HTTPException:
        raise
    except requests.exceptions.Timeout as exc:
        raise HTTPException(status_code=504, detail=f"Request timeout: {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Request error: {exc}") from exc
    except Exception as exc:
        logger.exception("Pipeline error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/stats", dependencies=[Depends(require_admin)])
async def get_loading_stats():
    try:
        files = iter_markdown_files()
        total_documents = len(files)

        last_update = datetime.now()
        if files:
            timestamps = [file_path.stat().st_mtime for file_path in files]
            if timestamps:
                last_update = datetime.fromtimestamp(max(timestamps))

        vector_db_docs = 0
        debug_error = None
        try:
            response = requests.get(f"{EMBEDDING_STORE_URL}/collection-info", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    vector_db_docs = data.get("point_count", 0)
                else:
                    debug_error = f"API error: {data.get('error')}"
            else:
                debug_error = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            debug_error = f"Connection failed: {exc}"
            logger.error("Failed to connect to embedding service: %s", exc)

        return {
            "total_documents": total_documents,
            "total_chunks": vector_db_docs,
            "vector_db_docs": vector_db_docs,
            "last_update": last_update.strftime("%Y-%m-%d %H:%M"),
            "avg_chunk_size": int(os.getenv("AVG_CHUNK_SIZE", "1500")),
            "debug_error": debug_error,
            "manifest_exists": MANIFEST_PATH.exists(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error generating stats")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.on_event("startup")
def startup_event():
    logger.info("Data Loader Service starting up")
    logger.info("Data path: %s", DATA_PATH)
    logger.info("Data path exists: %s", DATA_PATH.exists())
    logger.info("Manifest path exists: %s", MANIFEST_PATH.exists())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5001)
