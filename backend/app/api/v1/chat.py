"""API v1 Chat and Session endpoints.

Implements Architecture §6, §7, §8 and Prompt 4:
- POST /api/v1/chat/stream: SSE chat stream with Layer 1, Layer 2 (sentinel), Layer 3 (retract),
  canned greeting, clarification, telemetry logging, and conversation memory.
- GET /api/v1/chat/sessions: Retrieve the caller's active sessions.
- DELETE /api/v1/chat/sessions/{session_id}: Clear a session (strictly owner only).
"""
import json
import time
import uuid
from typing import List, Dict, Optional, AsyncIterator
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.core.config import settings
from app.core.logger import logger
from app.core.security import require_user
from app.db.session import AsyncSessionLocal
from app.models.schemas import (
    ErrorResponse,
    SessionSummaryResponse,
    SessionRenameRequest,
    ChatMessageItemResponse,
    SessionDeleteResponse,
    ChatStreamRequest,
    RouterIntent,
    MessageKind,
)
from app.models.sql_models import User, Document, QueryLog
from app.services.session_manager import get_session_manager, SessionManager
from app.services.intent_router import get_intent_router, IntentRouter
from app.services.rag_engine import get_rag_engine, RAGEngine
from app.services.citation_service import get_citation_service, CitationService
from app.services.generation_service import (
    build_answer_prompt,
    stream_with_sentinel_buffer,
    SentinelMatch,
)
from app.services.llm.factory import get_llm_adapter
from app.services.llm.base import (
    LLMError,
    LLMUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMAuthError,
)

router = APIRouter(prefix="/chat", tags=["chat"])


async def _record_query_log(
    user_id: Optional[str],
    session_id: str,
    intent: str,
    original_query: str,
    standalone_query: Optional[str] = None,
    top_score: Optional[float] = None,
    threshold: Optional[float] = None,
    fallback_layer: Optional[int] = None,
    cited_chunk_ids: Optional[List[str]] = None,
    latency_ms_router: Optional[float] = None,
    latency_ms_retrieval: Optional[float] = None,
    latency_ms_rerank: Optional[float] = None,
    latency_ms_generation: Optional[float] = None,
) -> None:
    """Asynchronously persist an audit & telemetry row to query_logs table."""
    try:
        user_uuid = None
        if user_id:
            try:
                user_uuid = uuid.UUID(user_id)
            except (ValueError, TypeError):
                pass

        async with AsyncSessionLocal() as session:
            log_entry = QueryLog(
                user_id=user_uuid,
                session_id=session_id,
                intent=intent,
                original_query=original_query,
                standalone_query=standalone_query,
                top_score=top_score,
                threshold=threshold,
                fallback_layer=fallback_layer,
                cited_chunk_ids=cited_chunk_ids,
                latency_ms_router=latency_ms_router,
                latency_ms_retrieval=latency_ms_retrieval,
                latency_ms_rerank=latency_ms_rerank,
                latency_ms_generation=latency_ms_generation,
            )
            session.add(log_entry)
            await session.commit()
    except Exception as exc:
        logger.warning(f"Failed to persist query_log telemetry: {exc}")


async def _lookup_document_names(doc_ids: List[str]) -> Dict[str, str]:
    """Look up human-readable document filenames from PostgreSQL."""
    if not doc_ids:
        return {}
    valid_uuids = []
    for d in doc_ids:
        try:
            valid_uuids.append(uuid.UUID(d))
        except (ValueError, TypeError):
            pass
    if not valid_uuids:
        return {}
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(Document.id, Document.name).where(Document.id.in_(valid_uuids))
            result = await session.execute(stmt)
            return {str(row[0]): row[1] for row in result.all()}
    except Exception as exc:
        logger.warning(f"Failed to lookup document names: {exc}")
        return {}


def _format_sse(event: str, data: dict) -> str:
    """Format SSE event string according to W3C specification."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post(
    "/stream",
    summary="Stream chat completion via SSE",
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Server-Sent Events stream (token, citations, retract, error, done)",
        },
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
@router.post(
    "/stream",
    summary="Stream chat completion via SSE",
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Server-Sent Events stream (token, citations, retract, error, done)",
        },
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Session not found"},
    },
)
async def chat_stream(
    body: ChatStreamRequest,
    current_user: User = Depends(require_user),
    session_manager: SessionManager = Depends(get_session_manager),
    intent_router: IntentRouter = Depends(get_intent_router),
    rag_engine: RAGEngine = Depends(get_rag_engine),
    citation_service: CitationService = Depends(get_citation_service),
) -> StreamingResponse:
    """Execute end-to-end RAG chat pipeline and stream results over SSE."""
    user_id = str(current_user.id)
    user_message = body.message

    # Validate or assign session (raises 404 if client-provided session_id is unknown or foreign)
    chat_session = await session_manager.get_or_create_session(
        user_id=user_id,
        session_id=body.session_id,
        initial_title=user_message,
    )
    session_id = str(chat_session.id)
    session_uuid = chat_session.id

    async def event_generator() -> AsyncIterator[str]:
        latency_router: Optional[float] = None
        latency_retrieval: Optional[float] = None
        latency_rerank: Optional[float] = None
        latency_generation: Optional[float] = None

        try:
            # 1. Fetch prior conversation history from Redis (or reconstructed from PG on cache miss)
            history = await session_manager.get_history(user_id, session_id)

            # 2. Persist user message to PostgreSQL and append to Redis BEFORE generation
            await session_manager.persist_user_message(
                session_id=session_uuid,
                content=user_message,
            )
            await session_manager.append_message(
                user_id=user_id,
                session_id=session_id,
                role="user",
                content=user_message,
                kind=MessageKind.NORMAL,
            )

            # 3. Intent routing & query rewriting (FAST role)
            router_start = time.perf_counter()
            decision = await intent_router.route(message=user_message, history=history)
            latency_router = (time.perf_counter() - router_start) * 1000.0

            # ------------------------------------------------------------------
            # Branch A: Pure Greeting
            # ------------------------------------------------------------------
            if decision.intent == RouterIntent.GREETING:
                greeting_text = settings.GREETING_MESSAGE
                yield _format_sse("token", {"text": greeting_text})
                yield _format_sse("done", {"session_id": session_id, "intent": "GREETING", "fallback_layer": None})

                await session_manager.persist_assistant_message(
                    session_id=session_uuid,
                    content=greeting_text,
                    kind="normal",
                )
                await session_manager.append_message(
                    user_id=user_id,
                    session_id=session_id,
                    role="assistant",
                    content=greeting_text,
                    kind=MessageKind.NORMAL,
                )
                await _record_query_log(
                    user_id=user_id,
                    session_id=session_id,
                    intent="GREETING",
                    original_query=user_message,
                    standalone_query=decision.standalone_query,
                    latency_ms_router=latency_router,
                )
                return

            # ------------------------------------------------------------------
            # Branch B: Clarification Required
            # ------------------------------------------------------------------
            if decision.intent == RouterIntent.CLARIFY:
                clarify_text = decision.clarification_message or (
                    "Could you please provide more details or clarify your question?"
                )
                yield _format_sse("token", {"text": clarify_text})
                yield _format_sse("done", {"session_id": session_id, "intent": "CLARIFY", "fallback_layer": None})

                await session_manager.persist_assistant_message(
                    session_id=session_uuid,
                    content=clarify_text,
                    kind="clarify",
                )
                await session_manager.append_message(
                    user_id=user_id,
                    session_id=session_id,
                    role="assistant",
                    content=clarify_text,
                    kind=MessageKind.CLARIFY,
                )
                await _record_query_log(
                    user_id=user_id,
                    session_id=session_id,
                    intent="CLARIFY",
                    original_query=user_message,
                    standalone_query=decision.standalone_query,
                    latency_ms_router=latency_router,
                )
                return

            # ------------------------------------------------------------------
            # Branch C: Search & RAG
            # ------------------------------------------------------------------
            standalone_query = decision.standalone_query or user_message

            # Retrieve & rerank (Hybrid + CrossEncoder)
            retrieval_res = rag_engine.retrieve(query=standalone_query)
            latency_retrieval = retrieval_res.latency_ms_retrieval
            latency_rerank = retrieval_res.latency_ms_rerank

            # Layer 1 Fallback (score < RERANK_THRESHOLD or no chunks)
            if retrieval_res.is_fallback:
                logger.info(
                    f"Layer 1 fallback triggered (top_score={retrieval_res.top_score}, "
                    f"threshold={settings.RERANK_THRESHOLD})"
                )
                fallback_text = settings.FALLBACK_MESSAGE
                yield _format_sse("token", {"text": fallback_text})
                yield _format_sse("done", {"session_id": session_id, "intent": "SEARCH", "fallback_layer": 1})

                await session_manager.persist_assistant_message(
                    session_id=session_uuid,
                    content=fallback_text,
                    kind="fallback",
                    fallback_layer=1,
                )
                await session_manager.append_message(
                    user_id=user_id,
                    session_id=session_id,
                    role="assistant",
                    content=fallback_text,
                    kind=MessageKind.FALLBACK,
                )
                await _record_query_log(
                    user_id=user_id,
                    session_id=session_id,
                    intent="SEARCH",
                    original_query=user_message,
                    standalone_query=standalone_query,
                    top_score=retrieval_res.top_score,
                    threshold=settings.RERANK_THRESHOLD,
                    fallback_layer=1,
                    latency_ms_router=latency_router,
                    latency_ms_retrieval=latency_retrieval,
                    latency_ms_rerank=latency_rerank,
                )
                return

            # Context assembly
            context_chunks = retrieval_res.chunks[: settings.RERANK_TOP_N]
            sys_prompt, user_prompt = build_answer_prompt(
                standalone_query=standalone_query,
                chunks=context_chunks,
            )

            # Pre-fetch document names for citation resolution
            doc_ids = list({c.document_id for c in context_chunks if c.document_id})
            doc_names = await _lookup_document_names(doc_ids)

            # Stream generation through ANSWER model
            adapter, answer_model = get_llm_adapter(role="answer")
            gen_start = time.perf_counter()
            token_stream = adapter.stream(
                system=sys_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                model=answer_model,
                max_tokens=1024,
                temperature=0.2,
            )

            # Layer 2 Sentinel Buffering
            buffered_stream = stream_with_sentinel_buffer(token_stream)
            accumulated_tokens: List[str] = []
            sentinel_hit = False

            async for item in buffered_stream:
                if isinstance(item, SentinelMatch):
                    sentinel_hit = True
                    break
                accumulated_tokens.append(item)
                yield _format_sse("token", {"text": item})

            latency_generation = (time.perf_counter() - gen_start) * 1000.0

            # Layer 2 Sentinel Triggered: abort and send fallback
            if sentinel_hit:
                logger.info("Layer 2 Sentinel triggered abort. Sending fallback.")
                fallback_text = settings.FALLBACK_MESSAGE
                yield _format_sse("token", {"text": fallback_text})
                yield _format_sse("done", {"session_id": session_id, "intent": "SEARCH", "fallback_layer": 2})

                await session_manager.persist_assistant_message(
                    session_id=session_uuid,
                    content=fallback_text,
                    kind="fallback",
                    fallback_layer=2,
                )
                await session_manager.append_message(
                    user_id=user_id,
                    session_id=session_id,
                    role="assistant",
                    content=fallback_text,
                    kind=MessageKind.FALLBACK,
                )
                await _record_query_log(
                    user_id=user_id,
                    session_id=session_id,
                    intent="SEARCH",
                    original_query=user_message,
                    standalone_query=standalone_query,
                    top_score=retrieval_res.top_score,
                    threshold=settings.RERANK_THRESHOLD,
                    fallback_layer=2,
                    latency_ms_router=latency_router,
                    latency_ms_retrieval=latency_retrieval,
                    latency_ms_rerank=latency_rerank,
                    latency_ms_generation=latency_generation,
                )
                return

            # Layer 3 Citation Verification & Retraction
            full_answer = "".join(accumulated_tokens)
            resolution = citation_service.resolve_citations(
                text=full_answer,
                context_chunks=context_chunks,
                doc_name_lookup=doc_names,
            )

            if resolution.is_retracted:
                # Layer 3 Triggered: ungrounded answer retracted
                logger.info("Layer 3: Ungrounded answer retracted. Emitting retract event.")
                fallback_text = settings.FALLBACK_MESSAGE
                yield _format_sse("retract", {"text": fallback_text})
                yield _format_sse("done", {"session_id": session_id, "intent": "SEARCH", "fallback_layer": 3})

                await session_manager.persist_assistant_message(
                    session_id=session_uuid,
                    content=fallback_text,
                    kind="fallback",
                    fallback_layer=3,
                )
                await session_manager.append_message(
                    user_id=user_id,
                    session_id=session_id,
                    role="assistant",
                    content=fallback_text,
                    kind=MessageKind.FALLBACK,
                )
                await _record_query_log(
                    user_id=user_id,
                    session_id=session_id,
                    intent="SEARCH",
                    original_query=user_message,
                    standalone_query=standalone_query,
                    top_score=retrieval_res.top_score,
                    threshold=settings.RERANK_THRESHOLD,
                    fallback_layer=3,
                    cited_chunk_ids=[],
                    latency_ms_router=latency_router,
                    latency_ms_retrieval=latency_retrieval,
                    latency_ms_rerank=latency_rerank,
                    latency_ms_generation=latency_generation,
                )
                return

            # Success: Emit resolved citations
            citations_payload = [c.model_dump() for c in resolution.citations]
            yield _format_sse("citations", {"citations": citations_payload})
            yield _format_sse("done", {"session_id": session_id, "intent": "SEARCH", "fallback_layer": None})

            await session_manager.persist_assistant_message(
                session_id=session_uuid,
                content=full_answer,
                kind="normal",
                citations=citations_payload,
            )
            await session_manager.append_message(
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                content=full_answer,
                kind=MessageKind.NORMAL,
            )
            await _record_query_log(
                user_id=user_id,
                session_id=session_id,
                intent="SEARCH",
                original_query=user_message,
                standalone_query=standalone_query,
                top_score=retrieval_res.top_score,
                threshold=settings.RERANK_THRESHOLD,
                fallback_layer=None,
                cited_chunk_ids=resolution.cited_chunk_ids,
                latency_ms_router=latency_router,
                latency_ms_retrieval=latency_retrieval,
                latency_ms_rerank=latency_rerank,
                latency_ms_generation=latency_generation,
            )

        except (LLMError, Exception) as exc:
            logger.error(f"Error in chat streaming pipeline: {type(exc).__name__}: {exc}")
            if isinstance(exc, LLMUnavailableError):
                code = "LLM_UNAVAILABLE"
            elif isinstance(exc, LLMRateLimitError):
                code = "LLM_RATE_LIMIT"
            elif isinstance(exc, LLMTimeoutError):
                code = "LLM_TIMEOUT"
            elif isinstance(exc, LLMAuthError):
                code = "LLM_AUTH_ERROR"
            else:
                code = getattr(exc, "error_code", "LLM_ERROR")

            yield _format_sse(
                "error",
                {
                    "message": settings.SYSTEM_ERROR_MESSAGE,
                    "code": code,
                },
            )
            yield _format_sse("done", {"session_id": session_id, "intent": "SEARCH", "fallback_layer": None})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Session-ID": session_id,
        },
    )


@router.get(
    "/sessions",
    response_model=List[SessionSummaryResponse],
    summary="List active user sessions",
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
async def list_chat_sessions(
    current_user: User = Depends(require_user),
    session_manager: SessionManager = Depends(get_session_manager),
) -> List[SessionSummaryResponse]:
    """Retrieve all active conversation sessions belonging to the authenticated caller."""
    return await session_manager.list_sessions(user_id=str(current_user.id))


@router.get(
    "/sessions/{session_id}/messages",
    response_model=List[ChatMessageItemResponse],
    summary="Get full conversation history for a session",
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Session not found"},
    },
)
async def get_session_messages(
    session_id: str,
    current_user: User = Depends(require_user),
    session_manager: SessionManager = Depends(get_session_manager),
) -> List[ChatMessageItemResponse]:
    """Retrieve all messages in a session in chronological order with citations. Strictly owner-only."""
    return await session_manager.get_session_messages(
        user_id=str(current_user.id),
        session_id=session_id,
    )


@router.patch(
    "/sessions/{session_id}",
    response_model=SessionSummaryResponse,
    summary="Rename conversation session",
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Session not found"},
        422: {"model": ErrorResponse, "description": "Invalid title"},
    },
)
async def rename_chat_session(
    session_id: str,
    body: SessionRenameRequest,
    current_user: User = Depends(require_user),
    session_manager: SessionManager = Depends(get_session_manager),
) -> SessionSummaryResponse:
    """Rename a conversation session title. Strictly owner-only."""
    return await session_manager.rename_session(
        user_id=str(current_user.id),
        session_id=session_id,
        title=body.title,
    )


@router.delete(
    "/sessions/{session_id}",
    response_model=SessionDeleteResponse,
    summary="Clear a chat session",
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Session not found"},
    },
)
async def delete_chat_session(
    session_id: str,
    current_user: User = Depends(require_user),
    session_manager: SessionManager = Depends(get_session_manager),
) -> SessionDeleteResponse:
    """Clear a conversation session. Enforces strict owner isolation."""
    cleared = await session_manager.clear_session(
        user_id=str(current_user.id),
        session_id=session_id,
    )
    if not cleared:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
            headers={"code": "SESSION_NOT_FOUND"},
        )
    return SessionDeleteResponse(
        detail="Session deleted successfully.",
        session_id=session_id,
    )
