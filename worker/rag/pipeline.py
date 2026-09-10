"""Local hybrid RAG: dense (fastembed, on-disk model) + BM25 lexical, fused with
Reciprocal Rank Fusion. Qdrant stores the vectors; Postgres stores chunk text and
page metadata so citations survive a Qdrant rebuild.

Everything runs inside the container. No embedding API, no remote reranker.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Sequence

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, PointStruct, VectorParams
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.db_models import KnowledgeChunk
from worker.rag.chunking import chunk_pages, extract_text_pages

logger = logging.getLogger("sovereign.rag")

COLLECTION_NAME = "knowledge_chunks"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

HYBRID_CANDIDATES = 12   # plan.md: top-12 hybrid candidates...
FINAL_TOP_K = 5          # ...reranked down to 5
RRF_K = 60

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-_.]*")


def _tokenize(text: str) -> List[str]:
    return _WORD_RE.findall(text.lower())


# ─── BM25 over the Postgres-resident corpus ──────────────────────────────────

class BM25Index:
    """Small-corpus BM25. Rebuilt from Postgres whenever ingestion changes it."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.doc_ids: List[str] = []
        self.doc_tokens: List[Counter] = []
        self.doc_lengths: List[int] = []
        self.avg_length = 0.0
        self.doc_freq: Counter = Counter()
        self.n_docs = 0

    def build(self, docs: Sequence[tuple[str, str]]) -> None:
        self.doc_ids = [d[0] for d in docs]
        self.doc_tokens = [Counter(_tokenize(d[1])) for d in docs]
        self.doc_lengths = [sum(c.values()) for c in self.doc_tokens]
        self.n_docs = len(docs)
        self.avg_length = (sum(self.doc_lengths) / self.n_docs) if self.n_docs else 0.0
        self.doc_freq = Counter()
        for counter in self.doc_tokens:
            self.doc_freq.update(counter.keys())

    def search(self, query: str, top_k: int) -> List[tuple[str, float]]:
        if not self.n_docs:
            return []
        q_tokens = _tokenize(query)
        scores: List[tuple[str, float]] = []
        for i, counter in enumerate(self.doc_tokens):
            score = 0.0
            length = self.doc_lengths[i] or 1
            for token in q_tokens:
                tf = counter.get(token, 0)
                if not tf:
                    continue
                df = self.doc_freq.get(token, 0)
                idf = math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))
                denom = tf + self.k1 * (1 - self.b + self.b * length / (self.avg_length or 1))
                score += idf * (tf * (self.k1 + 1)) / denom
            if score > 0:
                scores.append((self.doc_ids[i], score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


# ─── Pipeline ────────────────────────────────────────────────────────────────

class LocalRAGPipeline:
    def __init__(self) -> None:
        self._embedder = None
        self._embedder_lock = threading.Lock()
        self._qdrant: QdrantClient | None = None
        self._bm25 = BM25Index()
        self._bm25_dirty = True
        self._session_factory = sessionmaker(
            bind=create_engine(settings.sync_database_url, pool_pre_ping=True)
        )

    # ── lazily-built dependencies ────────────────────────────────────────────

    @property
    def qdrant(self) -> QdrantClient | None:
        if self._qdrant is None:
            try:
                self._qdrant = QdrantClient(url=settings.qdrant_url)
                self._ensure_collection()
            except Exception as e:
                logger.error("Qdrant unavailable: %s", e)
                self._qdrant = None
        return self._qdrant

    def _ensure_collection(self) -> None:
        assert self._qdrant is not None
        existing = {c.name for c in self._qdrant.get_collections().collections}
        if COLLECTION_NAME not in existing:
            self._qdrant.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
            )
            logger.info("Created Qdrant collection %s", COLLECTION_NAME)

    def _get_embedder(self):
        """One process-wide fastembed model, loaded from the image's on-disk cache."""
        if self._embedder is None:
            with self._embedder_lock:
                if self._embedder is None:
                    from fastembed import TextEmbedding

                    self._embedder = TextEmbedding(model_name=EMBEDDING_MODEL)
                    logger.info("Loaded local embedding model %s", EMBEDDING_MODEL)
        return self._embedder

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        return [v.tolist() for v in self._get_embedder().embed(list(texts))]

    def health(self) -> Dict[str, Any]:
        try:
            collections = [c.name for c in self.qdrant.get_collections().collections] if self.qdrant else []
            return {"qdrant_reachable": self.qdrant is not None, "collections": collections}
        except Exception as e:
            return {"qdrant_reachable": False, "error": str(e)}

    # ── ingestion ────────────────────────────────────────────────────────────

    def ingest_file(self, file_path: str, source_name: str | None = None,
                    mime_type: str | None = None) -> Dict[str, Any]:
        """Extract -> chunk -> embed -> Qdrant + Postgres. Re-ingesting a file
        with the same content hash replaces its previous chunks."""
        path = Path(file_path)
        if not path.exists():
            return {"status": "error", "error": f"File not found: {file_path}", "chunks": 0}

        source_file = source_name or path.name
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()

        try:
            pages = extract_text_pages(path, mime_type)
        except Exception as e:
            logger.exception("Extraction failed for %s", path)
            return {"status": "error", "error": f"Text extraction failed: {e}", "chunks": 0}

        chunks = chunk_pages(pages, source_file)
        if not chunks:
            return {
                "status": "error",
                "error": "No extractable text found in the document.",
                "chunks": 0,
                "pages_seen": len(pages),
            }

        vectors = self.embed([c["text"] for c in chunks])

        points: List[PointStruct] = []
        rows: List[KnowledgeChunk] = []
        for chunk, vector in zip(chunks, vectors):
            point_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{source_hash}:{chunk['page_number']}:{hashlib.sha1(chunk['text'].encode()).hexdigest()}",
            ))
            points.append(PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "chunk_id": point_id,
                    "source_file": chunk["source_file"],
                    "source_hash": source_hash,
                    "page_number": chunk["page_number"],
                    "heading": chunk["heading"],
                    "text": chunk["text"],
                },
            ))
            rows.append(KnowledgeChunk(
                source_file=chunk["source_file"],
                source_hash=source_hash,
                page_number=chunk["page_number"],
                heading=chunk["heading"],
                text=chunk["text"],
                qdrant_point_id=point_id,
            ))

        if self.qdrant is None:
            return {"status": "error", "error": "Qdrant is unreachable", "chunks": 0}

        # Re-ingesting a document REPLACES it, whether or not its bytes changed —
        # otherwise an edited SOP would leave its superseded clauses citable.
        with self._session_factory() as session:  # type: Session
            superseded = list(session.execute(
                select(KnowledgeChunk.qdrant_point_id)
                .where(KnowledgeChunk.source_file == source_file)
            ).scalars().all())
            session.execute(
                delete(KnowledgeChunk).where(KnowledgeChunk.source_file == source_file)
            )
            session.add_all(rows)
            session.commit()

        if superseded:
            try:
                self.qdrant.delete(collection_name=COLLECTION_NAME,
                                   points_selector=superseded, wait=True)
            except Exception as e:
                logger.warning("Could not remove %d superseded vectors: %s",
                               len(superseded), e)

        self.qdrant.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)

        self._bm25_dirty = True
        methods = sorted({p.get("extraction_method", "?") for p in pages})
        logger.info("Ingested %s: %d chunks over %d pages (%s)",
                    source_file, len(points), len(pages), ", ".join(methods))
        return {
            "status": "success",
            "source_file": source_file,
            "source_hash": source_hash,
            "pages": len(pages),
            "chunks": len(points),
            "replaced_chunks": len(superseded),
            "extraction_methods": methods,
        }

    # ── retrieval ────────────────────────────────────────────────────────────

    def _refresh_bm25(self) -> Dict[str, KnowledgeChunk]:
        with self._session_factory() as session:
            rows = list(session.execute(select(KnowledgeChunk)).scalars().all())
            session.expunge_all()
        if self._bm25_dirty:
            self._bm25.build([(r.qdrant_point_id, f"{r.heading or ''} {r.text}") for r in rows])
            self._bm25_dirty = False
        return {r.qdrant_point_id: r for r in rows}

    def search(self, query: str, top_k: int = FINAL_TOP_K) -> List[Dict[str, Any]]:
        """Hybrid dense + BM25 retrieval fused with RRF, trimmed to top_k."""
        by_id = self._refresh_bm25()
        if not by_id:
            return []

        dense_ranked: List[str] = []
        if self.qdrant is not None:
            try:
                hits = self.qdrant.query_points(
                    collection_name=COLLECTION_NAME,
                    query=self.embed([query])[0],
                    limit=HYBRID_CANDIDATES,
                    with_payload=True,
                ).points
                dense_ranked = [str(h.id) for h in hits]
                for h in hits:  # payload is the fallback if Postgres lost a row
                    if str(h.id) not in by_id and h.payload:
                        by_id[str(h.id)] = KnowledgeChunk(
                            qdrant_point_id=str(h.id),
                            source_file=h.payload.get("source_file", "unknown"),
                            source_hash=h.payload.get("source_hash", ""),
                            page_number=h.payload.get("page_number"),
                            heading=h.payload.get("heading"),
                            text=h.payload.get("text", ""),
                        )
            except Exception as e:
                logger.warning("Dense retrieval failed, falling back to BM25 only: %s", e)

        lexical_ranked = [cid for cid, _ in self._bm25.search(query, HYBRID_CANDIDATES)]

        # Reciprocal Rank Fusion
        fused: Dict[str, float] = {}
        contributors: Dict[str, List[str]] = {}
        for source, ranking in (("dense", dense_ranked), ("bm25", lexical_ranked)):
            for rank, cid in enumerate(ranking, start=1):
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank)
                contributors.setdefault(cid, []).append(source)

        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]

        results: List[Dict[str, Any]] = []
        for cid, score in ordered:
            row = by_id.get(cid)
            if row is None:
                continue
            results.append({
                "chunk_id": cid,
                "score": round(score, 6),
                "retrieved_by": contributors.get(cid, []),
                "source_file": row.source_file,
                "page_number": row.page_number,
                "heading": row.heading,
                "excerpt": row.text[:400] + ("…" if len(row.text) > 400 else ""),
                "text": row.text,
            })
        return results

    def get_chunk(self, chunk_id: str) -> Dict[str, Any] | None:
        with self._session_factory() as session:
            row = session.execute(
                select(KnowledgeChunk).where(KnowledgeChunk.qdrant_point_id == chunk_id)
            ).scalar_one_or_none()
            if row is None:
                return None
            return {
                "chunk_id": chunk_id,
                "source_file": row.source_file,
                "page_number": row.page_number,
                "heading": row.heading,
                "text": row.text,
            }


rag_pipeline = LocalRAGPipeline()
