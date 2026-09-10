"""Local knowledge-base retrieval tools. Reads only the locally ingested corpus."""
from __future__ import annotations

from typing import Any, Dict, List

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from worker.rag.pipeline import rag_pipeline


class SearchKnowledgeInput(BaseModel):
    query: str = Field(..., description="What to look for in the local SOP/manual corpus")
    top_k: int = Field(5, ge=1, le=10, description="How many excerpts to return")


class ReadSourceExcerptInput(BaseModel):
    chunk_id: str = Field(..., description="chunk_id returned by search_knowledge")


@tool("search_knowledge", args_schema=SearchKnowledgeInput)
def search_knowledge(query: str, top_k: int = 5) -> Dict[str, Any]:
    """Hybrid (dense + BM25) search over locally ingested SOPs and manuals.
    Every hit carries its source file and page number for citation."""
    hits: List[Dict[str, Any]] = rag_pipeline.search(query, top_k=top_k)
    return {
        "status": "success",
        "query": query,
        "result_count": len(hits),
        "results": hits,
        "note": "" if hits else
                "The local knowledge base returned nothing. Ingest an SOP via "
                "POST /api/knowledge/ingest before relying on citations.",
    }


@tool("read_source_excerpt", args_schema=ReadSourceExcerptInput)
def read_source_excerpt(chunk_id: str) -> Dict[str, Any]:
    """Return the full text of one retrieved chunk, with its source and page."""
    chunk = rag_pipeline.get_chunk(chunk_id)
    if chunk is None:
        return {"status": "error", "error": f"Unknown chunk_id: {chunk_id}"}
    return {"status": "success", **chunk}
