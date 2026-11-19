"""Content-index endpoints (F4): search, stats, and per-domain eviction."""

import structlog
from fastapi import APIRouter

from pawgrab.engine import index as index_engine
from pawgrab.models.index import IndexSearchRequest, IndexSearchResponse, IndexStats

logger = structlog.get_logger()
router = APIRouter(tags=["Index"])


@router.post("/index/search", response_model=IndexSearchResponse)
async def index_search(req: IndexSearchRequest):
    """Search the content index of already-scraped pages without fetching anything."""
    hits = await index_engine.search(req.query, k=req.k, include_content=req.include_content)
    return IndexSearchResponse(success=True, query=req.query, hits=hits, total=len(hits))


@router.get("/index/stats", response_model=IndexStats)
async def index_stats():
    """Return index size and backing store."""
    data = await index_engine.stats()
    return IndexStats(success=True, **data)


@router.delete("/index/{domain}")
async def index_delete_domain(domain: str):
    """Evict every cached page for a domain."""
    removed = await index_engine.delete_domain(domain)
    return {"success": True, "domain": domain, "removed": removed}
