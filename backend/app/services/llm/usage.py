"""LLM usage and cost tracking service for Prompt 7e-2.

Records token counts and calculates estimated costs based on provider_models pricing.
Guarantees non-blocking, best-effort async persistence without slowing or breaking SSE streams.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.logger import logger
from app.db.session import AsyncSessionLocal
from app.models.sql_models import LLMUsage, ProviderModel, LLMProvider
from app.models.schemas import LLMUsageResponse, LLMUsageSummaryItem


async def record_llm_usage(
    provider_id: Optional[uuid.UUID],
    model_id: str,
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
    latency_ms: float,
    status: str,
    error_class: Optional[str] = None,
) -> None:
    """Best-effort async recording of LLM generation usage and estimated cost."""
    try:
        total_tokens = None
        if prompt_tokens is not None or completion_tokens is not None:
            total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

        estimated_cost: Optional[float] = None
        async with AsyncSessionLocal() as session:
            # Look up model pricing from provider_models if tokens are available
            if provider_id and (prompt_tokens is not None or completion_tokens is not None):
                res = await session.execute(
                    select(ProviderModel).where(
                        ProviderModel.provider_id == provider_id,
                        ProviderModel.model_id == model_id,
                    )
                )
                pm = res.scalars().first()
                if pm and (pm.price_prompt_per_1m is not None or pm.price_completion_per_1m is not None):
                    prompt_price = pm.price_prompt_per_1m or 0.0
                    comp_price = pm.price_completion_per_1m or 0.0
                    cost = (
                        ((prompt_tokens or 0) / 1_000_000.0 * prompt_price) +
                        ((completion_tokens or 0) / 1_000_000.0 * comp_price)
                    )
                    estimated_cost = round(cost, 6)

            usage_record = LLMUsage(
                id=uuid.uuid4(),
                timestamp=datetime.now(timezone.utc),
                provider_id=provider_id,
                model_id=model_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=round(latency_ms, 2),
                status=status,
                error_class=error_class,
                estimated_cost=estimated_cost,
            )
            session.add(usage_record)
            await session.commit()
    except Exception as exc:
        logger.warning(f"Failed to record LLM usage log (best-effort): {exc}")


async def get_usage_summary(session: Optional[AsyncSession] = None, range_str: str = "24h") -> LLMUsageResponse:
    """Aggregate token usage and cost metrics for the specified time range."""
    now = datetime.now(timezone.utc)
    if range_str == "7d":
        since = now - timedelta(days=7)
    elif range_str == "30d":
        since = now - timedelta(days=30)
    else:
        since = now - timedelta(hours=24)
        range_str = "24h"

    async def _query_with_session(sess: AsyncSession) -> LLMUsageResponse:
        # Load providers for name mapping
        prov_res = await sess.execute(select(LLMProvider))
        prov_map = {p.id: p.name for p in prov_res.scalars().all()}

        # Load model pricing lookup
        pm_res = await sess.execute(select(ProviderModel))
        pm_lookup = {(pm.provider_id, pm.model_id): pm for pm in pm_res.scalars().all()}

        # Query aggregated stats
        stmt = (
            select(
                LLMUsage.provider_id,
                LLMUsage.model_id,
                func.count(LLMUsage.id).label("total_requests"),
                func.sum(LLMUsage.prompt_tokens).label("total_prompt_tokens"),
                func.sum(LLMUsage.completion_tokens).label("total_completion_tokens"),
                func.sum(LLMUsage.total_tokens).label("total_tokens"),
                func.sum(case((LLMUsage.status == "error", 1), else_=0)).label("total_errors"),
                func.avg(LLMUsage.latency_ms).label("avg_latency_ms"),
                func.sum(LLMUsage.estimated_cost).label("estimated_cost"),
            )
            .where(LLMUsage.timestamp >= since)
            .group_by(LLMUsage.provider_id, LLMUsage.model_id)
            .order_by(func.count(LLMUsage.id).desc())
        )
        res = await sess.execute(stmt)
        rows = res.all()

        items: List[LLMUsageSummaryItem] = []
        overall_requests = 0
        overall_prompt_tokens = 0
        overall_comp_tokens = 0
        overall_total_tokens = 0
        overall_errors = 0
        total_latencies = 0.0
        overall_cost: Optional[float] = None

        has_any_tokens = False
        has_any_cost = False

        for row in rows:
            p_id = row.provider_id
            m_id = row.model_id
            req_count = row.total_requests or 0
            p_tokens = int(row.total_prompt_tokens) if row.total_prompt_tokens is not None else None
            c_tokens = int(row.total_completion_tokens) if row.total_completion_tokens is not None else None
            t_tokens = int(row.total_tokens) if row.total_tokens is not None else None
            err_count = row.total_errors or 0
            avg_lat = round(float(row.avg_latency_ms or 0.0), 2)
            est_cost = round(float(row.estimated_cost), 4) if row.estimated_cost is not None else None

            cost_reason = None
            if est_cost is None:
                pm = pm_lookup.get((p_id, m_id))
                if not pm or (pm.price_prompt_per_1m is None and pm.price_completion_per_1m is None):
                    cost_reason = "No pricing data provided by provider or manual override"
                elif p_tokens is None:
                    cost_reason = "Token counts not returned by upstream provider"

            overall_requests += req_count
            overall_errors += err_count
            total_latencies += (avg_lat * req_count)

            if p_tokens is not None or c_tokens is not None:
                has_any_tokens = True
                overall_prompt_tokens += (p_tokens or 0)
                overall_comp_tokens += (c_tokens or 0)
                overall_total_tokens += (t_tokens or 0)

            if est_cost is not None:
                has_any_cost = True
                overall_cost = (overall_cost or 0.0) + est_cost

            items.append(
                LLMUsageSummaryItem(
                    provider_id=p_id,
                    provider_name=prov_map.get(p_id, "Unknown Provider"),
                    model_id=m_id,
                    total_requests=req_count,
                    total_prompt_tokens=p_tokens,
                    total_completion_tokens=c_tokens,
                    total_tokens=t_tokens,
                    total_errors=err_count,
                    avg_latency_ms=avg_lat,
                    estimated_cost=est_cost,
                    cost_reason=cost_reason,
                )
            )

        avg_latency = round(total_latencies / max(overall_requests, 1), 2)
        total_estimated = round(overall_cost, 4) if has_any_cost else None

        return LLMUsageResponse(
            range=range_str,
            total_requests=overall_requests,
            total_prompt_tokens=overall_prompt_tokens if has_any_tokens else None,
            total_completion_tokens=overall_comp_tokens if has_any_tokens else None,
            total_tokens=overall_total_tokens if has_any_tokens else None,
            total_errors=overall_errors,
            avg_latency_ms=avg_latency,
            total_estimated_cost=total_estimated,
            items=items,
        )

    if session is not None:
        return await _query_with_session(session)
    async with AsyncSessionLocal() as sess:
        return await _query_with_session(sess)

