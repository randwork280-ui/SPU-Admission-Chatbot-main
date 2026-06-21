from datetime import datetime, timezone
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Tuple, Union
import hashlib
import json
import logging
import uuid
import os
import time
import gc
import threading
from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse
from FlagEmbedding import BGEM3FlagModel

from admin_security import require_admin

app = FastAPI(title="Embedding & Vector Store Service (Hybrid)")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("Invalid integer for %s; using %s", name, default)
        return default


# Configuration
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-m3")
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "arabic_university_docs")

QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

MAX_RETRIES = 5
RETRY_DELAY = 2

# Safer defaults to avoid OOM
EMBED_BATCH_SIZE = 4          # outer batching in our loop (safe for WSL/Docker)
MODEL_BATCH_SIZE = 4          # internal batch in model.encode (keep same as outer)
MODEL_MAX_LENGTH = 2048       # reduce from 8192 to prevent RAM spikes

UPSERT_BATCH_SIZE = 100       # Qdrant upsert batch size

QUERY_EMBEDDING_CACHE_ENABLED = env_bool("QUERY_EMBEDDING_CACHE_ENABLED", True)
QUERY_EMBEDDING_CACHE_TTL_SECONDS = env_int("QUERY_EMBEDDING_CACHE_TTL_SECONDS", 3600)
QUERY_EMBEDDING_CACHE_MAX_ENTRIES = env_int("QUERY_EMBEDDING_CACHE_MAX_ENTRIES", 4096)


class DocumentModel(BaseModel):
    page_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    chunk_id: Optional[str] = None


class EmbedRequest(BaseModel):
    documents: List[DocumentModel]
    collection_name: str = COLLECTION_NAME
    replace_source_chunks: bool = True


class EmbedTextRequest(BaseModel):
    texts: List[str]


class MemoryTTLCache:
    def __init__(self, name: str, ttl_seconds: int, max_entries: int) -> None:
        self.name = name
        self.ttl_seconds = max(ttl_seconds, 1)
        self.max_entries = max(max_entries, 1)
        self.items: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.RLock()
        self.hits = 0
        self.misses = 0
        self.sets = 0
        self.evictions = 0

    def get(self, key: str) -> Tuple[Optional[Any], str]:
        now = time.time()
        with self.lock:
            entry = self.items.get(key)
            if entry is None:
                self.misses += 1
                return None, "miss"
            if entry["expires_at"] <= now:
                self.items.pop(key, None)
                self.evictions += 1
                self.misses += 1
                return None, "expired"
            self.hits += 1
            return entry["value"], "hit"

    def set(self, key: str, value: Any) -> None:
        now = time.time()
        with self.lock:
            self.items[key] = {
                "value": value,
                "created_at": now,
                "expires_at": now + self.ttl_seconds,
            }
            self.sets += 1
            self._evict_if_needed()

    def clear(self) -> int:
        with self.lock:
            count = len(self.items)
            self.items.clear()
            return count

    def stats(self) -> Dict[str, Any]:
        self.prune()
        with self.lock:
            requests = self.hits + self.misses
            return {
                "name": self.name,
                "items": len(self.items),
                "max_entries": self.max_entries,
                "ttl_seconds": self.ttl_seconds,
                "hits": self.hits,
                "misses": self.misses,
                "sets": self.sets,
                "evictions": self.evictions,
                "hit_rate": round(self.hits / requests, 4) if requests else 0.0,
            }

    def prune(self) -> int:
        now = time.time()
        with self.lock:
            expired = [key for key, entry in self.items.items() if entry["expires_at"] <= now]
            for key in expired:
                self.items.pop(key, None)
            self.evictions += len(expired)
            return len(expired)

    def _evict_if_needed(self) -> None:
        overflow = len(self.items) - self.max_entries
        if overflow <= 0:
            return
        oldest_keys = sorted(self.items, key=lambda key: self.items[key]["created_at"])[:overflow]
        for key in oldest_keys:
            self.items.pop(key, None)
        self.evictions += len(oldest_keys)


# Globals
qdrant_client: Optional[QdrantClient] = None
embedding_model: Optional[BGEM3FlagModel] = None
EMBEDDING_DIM = 1024
query_embedding_cache = MemoryTTLCache(
    "query_embedding",
    QUERY_EMBEDDING_CACHE_TTL_SECONDS,
    QUERY_EMBEDDING_CACHE_MAX_ENTRIES,
)
collection_versions: Dict[str, Dict[str, Any]] = {}


def init_qdrant_client(max_retries: int = MAX_RETRIES) -> QdrantClient:
    """Initialize Qdrant client with connection retry."""
    for attempt in range(max_retries):
        try:
            client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
            client.get_collections()
            logger.info(f"Successfully connected to Qdrant at {QDRANT_HOST}:{QDRANT_PORT}")
            return client
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed to connect to Qdrant: {e}")
            if attempt < max_retries - 1:
                time.sleep(RETRY_DELAY)
            else:
                logger.error("Failed to connect to Qdrant after all retries")
                raise


def init_embedding_model() -> bool:
    """Initialize the BGE-M3 embedding model."""
    global embedding_model, EMBEDDING_DIM

    try:
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL_NAME}")
        embedding_model = BGEM3FlagModel(
            EMBEDDING_MODEL_NAME,
            use_fp16=True
        )

        test_output = embedding_model.encode(
            ["test"],
            max_length=64,
            return_dense=True,
            return_sparse=True, # Enable Sparse
            return_colbert_vecs=False,
        )

        EMBEDDING_DIM = len(test_output["dense_vecs"][0])
        logger.info(f"Embedding model loaded. Dimension: {EMBEDDING_DIM}")
        return True
    except Exception as e:
        logger.error(f"Error loading embedding model: {e}")
        return False


def ensure_collection_exists(collection_name: str) -> None:
    """
    Ensure the Qdrant collection exists with HYBRID config (Dense + Sparse).
    """
    if qdrant_client is None:
        raise RuntimeError("Qdrant client not initialized")

    try:
        qdrant_client.get_collection(collection_name)
        logger.info(f"Collection '{collection_name}' exists")
    except UnexpectedResponse:
        logger.info(f"Creating collection '{collection_name}' with Hybrid Config")
        
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "dense": models.VectorParams(
                    size=EMBEDDING_DIM,
                    distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(
                    index=models.SparseIndexParams(
                        on_disk=False,
                    )
                )
            }
        )
        logger.info(f"Collection '{collection_name}' created")

    ensure_payload_indexes(collection_name)


def ensure_payload_indexes(collection_name: str) -> None:
    """Create payload indexes used by metadata filters. Existing indexes are ignored."""
    if qdrant_client is None:
        raise RuntimeError("Qdrant client not initialized")

    keyword_fields = [
        "metadata.faculty",
        "metadata.doc_category",
        "metadata.source",
        "metadata.source_id",
        "metadata.language",
    ]
    text_fields = [
        "metadata.header_1",
        "metadata.header_2",
        "metadata.header_3",
        "metadata.header_path",
    ]

    for field_name in keyword_fields:
        try:
            qdrant_client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        except Exception as exc:
            logger.debug("Payload keyword index skipped for %s: %s", field_name, exc)

    for field_name in text_fields:
        try:
            qdrant_client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=models.TextIndexParams(
                    type=models.TextIndexType.TEXT,
                    tokenizer=models.TokenizerType.WORD,
                    min_token_len=2,
                    max_token_len=20,
                    lowercase=True,
                ),
            )
        except Exception as exc:
            logger.debug("Payload text index skipped for %s: %s", field_name, exc)


def stable_point_id(doc: DocumentModel, collection_name: str) -> str:
    metadata = doc.metadata or {}
    identity = (
        doc.chunk_id
        or metadata.get("chunk_hash")
        or metadata.get("content_hash")
        or f"{metadata.get('source', 'unknown')}:{doc.page_content}"
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{collection_name}:{identity}"))


def stable_json_hash(payload: Dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def collection_identity_for_doc(doc: DocumentModel, collection_name: str) -> Dict[str, Any]:
    metadata = doc.metadata or {}
    return {
        "point_id": stable_point_id(doc, collection_name),
        "chunk_id": doc.chunk_id,
        "source_id": metadata.get("source_id"),
        "source": metadata.get("source"),
        "chunk_hash": metadata.get("chunk_hash"),
        "content_hash": metadata.get("content_hash"),
    }


def set_collection_version(
    collection_name: str,
    documents: List[DocumentModel],
    ingested_at: str,
    sources_replaced: List[str],
) -> Dict[str, Any]:
    payload = {
        "collection_name": collection_name,
        "model": EMBEDDING_MODEL_NAME,
        "embedding_dim": EMBEDDING_DIM,
        "ingested_at": ingested_at,
        "sources_replaced": sorted(sources_replaced),
        "documents": sorted(
            [collection_identity_for_doc(doc, collection_name) for doc in documents],
            key=lambda item: item["point_id"],
        ),
    }
    version = stable_json_hash(payload)
    collection_versions[collection_name] = {
        "version": version,
        "updated_at": ingested_at,
        "reason": "ingestion",
        "stored_count": len(documents),
    }
    return collection_versions[collection_name]


def compute_collection_version_from_points(collection_name: str) -> Dict[str, Any]:
    if qdrant_client is None:
        raise HTTPException(status_code=500, detail="Qdrant client not initialized")

    points: List[Dict[str, Any]] = []
    next_page = None
    while True:
        records, next_page = qdrant_client.scroll(
            collection_name=collection_name,
            limit=256,
            offset=next_page,
            with_payload=True,
            with_vectors=False,
        )
        for record in records:
            payload = record.payload or {}
            metadata = payload.get("metadata") or {}
            points.append(
                {
                    "point_id": str(record.id),
                    "chunk_id": payload.get("chunk_id"),
                    "source_id": metadata.get("source_id"),
                    "source": metadata.get("source"),
                    "chunk_hash": metadata.get("chunk_hash"),
                    "content_hash": metadata.get("content_hash"),
                    "ingested_at": metadata.get("ingested_at"),
                }
            )
        if next_page is None:
            break

    payload = {
        "collection_name": collection_name,
        "model": EMBEDDING_MODEL_NAME,
        "embedding_dim": EMBEDDING_DIM,
        "points": sorted(points, key=lambda item: item["point_id"]),
    }
    return {
        "version": stable_json_hash(payload),
        "updated_at": max(
            [point["ingested_at"] for point in points if point.get("ingested_at")],
            default=None,
        ),
        "reason": "payload_scan",
        "stored_count": len(points),
    }


def get_collection_version_value(collection_name: str) -> Dict[str, Any]:
    existing = collection_versions.get(collection_name)
    if existing:
        return existing

    if qdrant_client is None:
        raise HTTPException(status_code=500, detail="Qdrant client not initialized")

    collection_versions[collection_name] = compute_collection_version_from_points(collection_name)
    return collection_versions[collection_name]


def query_embedding_cache_key(query: str) -> str:
    return stable_json_hash(
        {
            "query": " ".join((query or "").split()).lower(),
            "model": EMBEDDING_MODEL_NAME,
            "max_length": MODEL_MAX_LENGTH,
            "embedding_dim": EMBEDDING_DIM,
        }
    )


def encode_query_hybrid(query: str) -> Tuple[List[float], models.SparseVector, str]:
    if embedding_model is None:
        raise HTTPException(status_code=500, detail="Embedding model not loaded")

    key = query_embedding_cache_key(query)
    if QUERY_EMBEDDING_CACHE_ENABLED:
        cached, status = query_embedding_cache.get(key)
        if cached is not None:
            return (
                cached["dense"],
                models.SparseVector(indices=cached["sparse"]["indices"], values=cached["sparse"]["values"]),
                status,
            )
    else:
        status = "disabled"

    output = embedding_model.encode(
        [query],
        max_length=MODEL_MAX_LENGTH,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    query_dense = output["dense_vecs"][0].tolist()
    sparse_weights = output["lexical_weights"][0]
    query_sparse = models.SparseVector(
        indices=[int(k) for k in sparse_weights.keys()],
        values=[float(v) for v in sparse_weights.values()],
    )

    if QUERY_EMBEDDING_CACHE_ENABLED:
        query_embedding_cache.set(
            key,
            {
                "dense": query_dense,
                "sparse": {
                    "indices": query_sparse.indices,
                    "values": query_sparse.values,
                },
            },
        )
        status = "stored"

    return query_dense, query_sparse, status


def delete_existing_source_chunks(collection_name: str, source_ids: List[str]) -> List[str]:
    if qdrant_client is None or not source_ids:
        return []

    conditions = [
        models.FieldCondition(
            key="metadata.source_id",
            match=models.MatchValue(value=source_id),
        )
        for source_id in sorted(set(source_ids))
    ]
    qdrant_client.delete(
        collection_name=collection_name,
        points_selector=models.FilterSelector(
            filter=models.Filter(should=conditions),
        ),
        wait=True,
    )
    return sorted(set(source_ids))


def get_embeddings_batch(
    texts: List[str],
    batch_size: int = EMBED_BATCH_SIZE,
    model_batch_size: int = MODEL_BATCH_SIZE,
    max_length: int = MODEL_MAX_LENGTH,
) -> Tuple[List[List[float]], List[models.SparseVector]]:
    """
    Generate Hybrid embeddings (Dense + Sparse) in batches.
    Returns: (dense_vectors, sparse_vectors)
    """
    if not texts:
        return [], []

    if embedding_model is None:
        raise HTTPException(status_code=500, detail="Embedding model not loaded")

    all_dense: List[List[float]] = []
    all_sparse: List[models.SparseVector] = []
    
    total = len(texts)
    total_batches = (total - 1) // batch_size + 1

    logger.info(f"Starting hybrid embedding: total={total}")

    for b, i in enumerate(range(0, total, batch_size), start=1):
        batch = texts[i:i + batch_size]

        output = embedding_model.encode(
            batch,
            batch_size=model_batch_size,
            max_length=max_length,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False
        )

        # Dense Processing
        batch_dense = output["dense_vecs"].tolist()
        all_dense.extend(batch_dense)
        
        # Sparse Processing (Lexical Weights)
        # BGE-M3 returns a list of dicts {word_id: weight} for sparse
        lexical_weights = output["lexical_weights"]
        
        for weights in lexical_weights:
            # Convert str keys to int indices if needed, BGE-M3 uses token IDs (int)
            # Actually BGEM3FlagModel.encode returns dict of {str(token_id): weight} or {token_id: weight}
            # qdrant expects integer indices.
            # BGE-M3 library sparse output keys are strings of token IDs.
            
            indices = []
            values = []
            for k, v in weights.items():
                indices.append(int(k))
                values.append(float(v))
            
            all_sparse.append(models.SparseVector(indices=indices, values=values))

        # Explicit cleanup
        del output
        del batch_dense
        del lexical_weights
        gc.collect()

        if total > 50 and b % 5 == 0:
            logger.info(f"Progress: {len(all_dense)}/{total} processed")

    return all_dense, all_sparse


@app.get("/health")
def health_check():
    """Health check endpoint."""
    qdrant_status = "connected" if qdrant_client else "disconnected"
    model_status = "loaded" if embedding_model else "not loaded"
    return {
        "status": "ok",
        "service": "Embedding Store (Hybrid)",
        "qdrant": qdrant_status,
        "embedding_model": model_status,
        "query_embedding_cache": {
            "enabled": QUERY_EMBEDDING_CACHE_ENABLED,
            "stats": query_embedding_cache.stats(),
        },
    }


@app.post("/embed")
def embed_texts(request: EmbedTextRequest):
    """
    Generate embeddings without storing.
    Returns both dense and sparse for inspection.
    """
    try:
        dense, sparse = get_embeddings_batch(request.texts)
        
        # Convert sparse to serializable
        sparse_serializable = []
        for sv in sparse:
            sparse_serializable.append({
                "indices": sv.indices,
                "values": sv.values
            })

        return {
            "success": True,
            "dense_embeddings": dense,
            "sparse_embeddings": sparse_serializable,
            "count": len(dense),
        }

    except Exception as e:
        logger.error(f"Error in embed: {e}")
        return {"success": False, "error": str(e)}


@app.post("/embed-and-store", dependencies=[Depends(require_admin)])
def embed_and_store(request: EmbedRequest):
    """Embed documents and store in Qdrant (Hybrid)."""
    try:
        if qdrant_client is None:
            raise HTTPException(status_code=500, detail="Qdrant client not initialized")

        valid_docs = []
        texts = []
        for doc in request.documents:
            content = (doc.page_content or "").strip()
            if content and len(content) >= 10:
                valid_docs.append(doc)
                texts.append(content)

        if not texts:
            return {"success": False, "error": "No valid documents"}

        # Generate Hybrid Embeddings
        dense_vecs, sparse_vecs = get_embeddings_batch(texts)
        
        ensure_collection_exists(request.collection_name)

        source_ids = [
            str(doc.metadata.get("source_id"))
            for doc in valid_docs
            if doc.metadata and doc.metadata.get("source_id")
        ]
        sources_replaced: List[str] = []
        if request.replace_source_chunks:
            sources_replaced = delete_existing_source_chunks(request.collection_name, source_ids)

        points: List[models.PointStruct] = []
        ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for doc, dense, sparse in zip(valid_docs, dense_vecs, sparse_vecs):
            point_id = stable_point_id(doc, request.collection_name)
            payload = {
                "content": doc.page_content,
                "metadata": {
                    **(doc.metadata or {}),
                    "content_length": len(doc.page_content),
                    "ingested_at": ingested_at,
                },
                "chunk_id": doc.chunk_id,
            }
            
            # Hybrid Point
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector={
                        "dense": dense,
                        "sparse": sparse
                    },
                    payload=payload,
                )
            )

        # Upsert in batches
        for i in range(0, len(points), UPSERT_BATCH_SIZE):
            batch = points[i:i + UPSERT_BATCH_SIZE]
            qdrant_client.upsert(
                collection_name=request.collection_name,
                points=batch
            )

        collection_version = set_collection_version(
            request.collection_name,
            valid_docs,
            ingested_at,
            sources_replaced,
        )

        return {
            "success": True,
            "stored_count": len(points),
            "mode": "hybrid",
            "stable_point_ids": True,
            "sources_replaced": sources_replaced,
            "collection_version": collection_version["version"],
        }

    except Exception as e:
        logger.error(f"Error in embed_and_store: {e}")
        return {"success": False, "error": str(e)}


@app.get("/search")
def search(
    query: str, 
    limit: int = 8, 
    min_score: float = 0.3,
    faculty: Optional[str] = None,
    doc_category: Optional[str] = None,
    year: Optional[str] = None,
    semester: Optional[str] = None
):
    """
    Hybrid Search with optional metadata filtering.
    Filters by faculty and/or document category to prevent cross-faculty confusion.
    """
    try:
        if qdrant_client is None or embedding_model is None:
            raise HTTPException(status_code=500, detail="Service not ready")

        # Encode Query (Hybrid)
        query_dense, query_sparse, query_cache_status = encode_query_hybrid(query)
        
        # Build metadata filter
        filter_conditions = []
        if faculty:
            filter_conditions.append(
                models.FieldCondition(
                    key="metadata.faculty",
                    match=models.MatchValue(value=faculty)
                )
            )
        if doc_category:
            filter_conditions.append(
                models.FieldCondition(
                    key="metadata.doc_category",
                    match=models.MatchValue(value=doc_category)
                )
            )
            
        # Self-Querying: Map Year and Semester to headers
        # Year usually appears in header_2, Semester in header_3 based on MD structure
        if year:
            filter_conditions.append(
                models.FieldCondition(
                    key="metadata.header_2",
                    match=models.MatchText(text=year)
                )
            )
        if semester:
            filter_conditions.append(
                models.FieldCondition(
                    key="metadata.header_3",
                    match=models.MatchText(text=semester)
                )
            )
        
        query_filter = models.Filter(must=filter_conditions) if filter_conditions else None
        
        # Execute Hybrid Search with filters
        search_results = qdrant_client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                models.Prefetch(
                    query=query_dense,
                    using="dense",
                    limit=limit * 2,
                    filter=query_filter,  # Apply filter to dense search
                ),
                models.Prefetch(
                    query=query_sparse,
                    using="sparse",
                    limit=limit * 2,
                    filter=query_filter,  # Apply filter to sparse search
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
        ).points

        raw_count = len(search_results)
        score_values = [float(hit.score) for hit in search_results]
        filtered_results = [hit for hit in search_results if float(hit.score) >= min_score]

        # Format results
        results = []
        for hit in filtered_results:
            results.append({
                "content": hit.payload.get("content", ""),
                "metadata": hit.payload.get("metadata", {}),
                "score": float(hit.score),
                "chunk_id": hit.payload.get("chunk_id"),
            })

        return {
            "success": True,
            "query": query,
            "results": results,
            "count": len(results),
            "collection_version": get_collection_version_value(COLLECTION_NAME)["version"],
            "debug": {
                "raw_count": raw_count,
                "min_score": min_score,
                "min_score_applied": True,
                "query_embedding_cache": query_cache_status,
                "score_stats": {
                    "max": max(score_values) if score_values else 0.0,
                    "min": min(score_values) if score_values else 0.0,
                    "avg": sum(score_values) / len(score_values) if score_values else 0.0,
                },
            },
        }

    except Exception as e:
        logger.error(f"Error in hybrid search: {e}")
        return {"success": False, "error": str(e)}


@app.get("/collections")
def get_collections():
    """List all collections."""
    try:
        if qdrant_client is None:
            raise HTTPException(status_code=500, detail="Qdrant client not initialized")
        collections = qdrant_client.get_collections()
        return {"success": True, "collections": [col.name for col in collections.collections]}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/collection-info")
def collection_info(collection_name: str = COLLECTION_NAME):
    """Get collection information."""
    try:
        if qdrant_client is None:
            raise HTTPException(status_code=500, detail="Qdrant client not initialized")

        info = qdrant_client.get_collection(collection_name)
        vectors_config = info.config.params.vectors
        dense_config = vectors_config.get("dense") if isinstance(vectors_config, dict) else vectors_config
        return {
            "success": True,
            "collection_name": collection_name,
            "vector_size": getattr(dense_config, "size", None),
            "point_count": info.points_count,
            "status": str(info.status),
            "vectors_config": str(vectors_config),
            "sparse_vectors_config": str(info.config.params.sparse_vectors),
            "collection_version": get_collection_version_value(collection_name)["version"],
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/collection-version")
def collection_version(collection_name: str = COLLECTION_NAME):
    try:
        version_info = get_collection_version_value(collection_name)
        return {
            "success": True,
            "collection_name": collection_name,
            "version": version_info["version"],
            "updated_at": version_info.get("updated_at"),
            "reason": version_info.get("reason"),
            "stored_count": version_info.get("stored_count"),
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/cache/stats")
def cache_stats():
    return {
        "success": True,
        "query_embedding_cache": {
            "enabled": QUERY_EMBEDDING_CACHE_ENABLED,
            "stats": query_embedding_cache.stats(),
        },
        "collection_versions": collection_versions,
    }


@app.delete("/collection/{collection_name}", dependencies=[Depends(require_admin)])
def delete_collection(collection_name: str, confirm: str):
    """Delete a collection."""
    try:
        if confirm != collection_name:
            raise HTTPException(
                status_code=400,
                detail="Collection deletion requires confirm=<collection_name>",
            )
        if qdrant_client is None:
            raise HTTPException(status_code=500, detail="Qdrant client not initialized")
        qdrant_client.delete_collection(collection_name)
        collection_versions.pop(collection_name, None)
        logger.info(f"Deleted collection: {collection_name}")
        return {"success": True, "message": f"Collection '{collection_name}' deleted"}
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    global qdrant_client
    logger.info("Starting Embedding & Vector Store service (HYBRID)...")

    if not init_embedding_model():
        raise RuntimeError("Embedding model initialization failed")

    qdrant_client = init_qdrant_client()
    ensure_collection_exists(COLLECTION_NAME)
    get_collection_version_value(COLLECTION_NAME)
    logger.info("Service initialized successfully")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5003)
