"""POST /agent — agentic, multi-step structured extraction."""

import structlog
from fastapi import APIRouter

from pawgrab.dependencies import try_browser_pool
from pawgrab.exceptions import ErrorCode, PawgrabError
from pawgrab.models.agent import AgentRequest, AgentResponse
from pawgrab.models.common import ErrorResponse

logger = structlog.get_logger()
router = APIRouter(tags=["Agent"])


@router.post(
    "/agent",
    response_model=AgentResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Validation error"},
        502: {"model": ErrorResponse, "description": "Agent run failed"},
        503: {"model": ErrorResponse, "description": "LLM provider unavailable"},
    },
)
async def agent(req: AgentRequest):
    """Run a bounded research agent that navigates pages to satisfy a goal/schema.

    Supersedes the old single-shot ``/extract``: give a natural-language ``prompt``
    (optionally with seed ``urls`` and a JSON ``schema``) and an ``effort`` budget;
    the agent fetches, searches, and follows links until it can return the data.
    """
    from pawgrab.ai.agent import run_agent
    from pawgrab.engine.metrics import metrics

    metrics.agent_total.inc()
    pool = await try_browser_pool()
    try:
        return await run_agent(
            prompt=req.prompt,
            urls=[str(u) for u in req.urls],
            json_schema=req.json_schema,
            effort=req.effort,
            max_steps=req.max_steps,
            allowed_domains=req.allowed_domains,
            timeout=req.timeout,
            browser_pool=pool,
        )
    except RuntimeError as exc:
        # Raised when no LLM provider is configured.
        logger.warning("agent_provider_unavailable", error=str(exc))
        raise PawgrabError(
            status_code=503,
            code=ErrorCode.LLM_UNAVAILABLE,
            message="LLM provider unavailable — configure PAWGRAB_OPENAI_API_KEY (or another provider)",
        ) from exc
    except Exception as exc:
        logger.error("agent_failed", error=str(exc))
        raise PawgrabError(
            status_code=502,
            code=ErrorCode.AGENT_FAILED,
            message=f"Agent run failed: {type(exc).__name__}",
        ) from exc
