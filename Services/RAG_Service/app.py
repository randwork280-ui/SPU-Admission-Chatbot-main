from __future__ import annotations

import logging
import os
import time
from typing import Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from qdrant_client import QdrantClient


app = FastAPI(title="RAG Service - Document Retrieval")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "arabic_university_docs")
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
EMBEDDING_STORE_URL = os.getenv("EMBEDDING_STORE_URL", "http://embedding-store:5003")
MAX_RETRIES = 5
RETRY_DELAY = 2

qdrant_client: Optional[QdrantClient] = None


class QueryRequest(BaseModel):
    query: str
    k: int = 8
    min_score: float = 0.3
    faculty: Optional[str] = None
    doc_category: Optional[str] = None
    year: Optional[str] = None
    semester: Optional[str] = None


def init_qdrant_client(max_retries: int = MAX_RETRIES) -> QdrantClient:
    for attempt in range(max_retries):
        try:
            client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
            client.get_collections()
            logger.info("Connected to Qdrant at %s:%s", QDRANT_HOST, QDRANT_PORT)
            return client
        except Exception as exc:
            logger.warning("Qdrant connection attempt %s/%s failed: %s", attempt + 1, max_retries, exc)
            if attempt < max_retries - 1:
                time.sleep(RETRY_DELAY)
            else:
                raise


def get_query_embedding(text: str) -> List[float]:
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{EMBEDDING_STORE_URL}/embed", json={"texts": [text]})
            response.raise_for_status()
            data = response.json()
            return data["dense_embeddings"][0]
    except Exception as exc:
        logger.error("Error generating query embedding: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/health")
def health_check():
    qdrant_status = "connected" if qdrant_client else "disconnected"
    embedding_service_status = "unknown"
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{EMBEDDING_STORE_URL}/health")
            embedding_service_status = "connected" if response.status_code == 200 else "error"
    except Exception:
        embedding_service_status = "disconnected"

    return {
        "status": "ok",
        "message": "RAG Service is running",
        "qdrant": qdrant_status,
        "embedding_service": embedding_service_status,
        "model": "BAAI/bge-m3 (via Embedding-Store)",
        "collection": COLLECTION_NAME,
    }


@app.post("/retrieve")
def retrieve(request: QueryRequest):
    try:
        logger.info("Retrieve query: %s...", request.query[:50])
        params = {
            "query": request.query,
            "limit": request.k,
            "min_score": request.min_score,
        }
        params.update(
            {
                key: value
                for key, value in request.model_dump().items()
                if value and key not in {"query", "k", "min_score"}
            }
        )

        response = httpx.get(f"{EMBEDDING_STORE_URL}/search", params=params, timeout=30.0)
        if response.status_code != 200:
            logger.error("Embedding-Store returned %s: %s", response.status_code, response.text)
            raise HTTPException(status_code=502, detail="Search service failed")

        data = response.json()
        if not data.get("success"):
            raise HTTPException(status_code=502, detail=data.get("error", "Search service failed"))

        results = data.get("results", [])
        logger.info("Retrieved %s results via hybrid search", len(results))
        return {
            "success": True,
            "query": request.query,
            "results": results,
            "total_results": len(results),
            "collection_version": data.get("collection_version"),
            "debug": data.get("debug"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Retrieval error")
        return {"success": False, "error": str(exc)}


@app.get("/collection-version")
def collection_version():
    try:
        response = httpx.get(
            f"{EMBEDDING_STORE_URL}/collection-version",
            params={"collection_name": COLLECTION_NAME},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("success"):
            raise HTTPException(status_code=502, detail=data.get("error", "Collection version unavailable"))

        return {
            "success": True,
            "collection_name": data.get("collection_name", COLLECTION_NAME),
            "version": data.get("version"),
            "updated_at": data.get("updated_at"),
            "reason": data.get("reason"),
            "stored_count": data.get("stored_count"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/search-quality")
def search_quality(query: str, limit: int = 10):
    try:
        response = httpx.get(
            f"{EMBEDDING_STORE_URL}/search",
            params={"query": query, "limit": limit, "min_score": 0.0},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("success"):
            raise HTTPException(status_code=502, detail=data.get("error", "Search failed"))

        results = data.get("results", [])
        scores = [float(result.get("score", 0.0)) for result in results]
        return {
            "success": True,
            "query": query,
            "total_results": len(results),
            "score_stats": {
                "max": max(scores) if scores else 0.0,
                "min": min(scores) if scores else 0.0,
                "avg": sum(scores) / len(scores) if scores else 0.0,
                "high_relevance": len([score for score in scores if score >= 0.7]),
                "medium_relevance": len([score for score in scores if 0.3 <= score < 0.7]),
                "low_relevance": len([score for score in scores if score < 0.3]),
            },
            "search_debug": data.get("debug"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/collection-stats")
def collection_stats():
    try:
        if qdrant_client is None:
            raise HTTPException(status_code=500, detail="Qdrant client not initialized")

        info = qdrant_client.get_collection(COLLECTION_NAME)
        try:
            count = qdrant_client.count(collection_name=COLLECTION_NAME, exact=True)
            point_count = count.count
        except Exception:
            point_count = 0

        vectors_config = info.config.params.vectors
        dense_config = vectors_config.get("dense") if isinstance(vectors_config, dict) else vectors_config

        return {
            "success": True,
            "collection_name": COLLECTION_NAME,
            "vector_dimension": getattr(dense_config, "size", None),
            "total_documents": point_count,
            "distance_metric": str(getattr(dense_config, "distance", "unknown")),
            "vectors_config": str(vectors_config),
            "sparse_vectors_config": str(info.config.params.sparse_vectors),
        }
    except HTTPException:
        raise
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.on_event("startup")
async def startup_event():
    global qdrant_client

    logger.info("RAG Service starting up")
    logger.info("Using Embedding-Store service for embeddings")

    try:
        qdrant_client = init_qdrant_client()
    except Exception as exc:
        logger.error("Failed to connect to Qdrant: %s", exc)
        raise

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{EMBEDDING_STORE_URL}/health")
            if response.status_code == 200:
                logger.info("Embedding-Store service connected")
            else:
                logger.warning("Embedding-Store returned status %s", response.status_code)
    except Exception as exc:
        logger.warning("Could not reach Embedding-Store: %s", exc)

    logger.info("RAG Service initialized successfully")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5004)
