"""Intent router and standalone query rewriter.

Implements Architecture §6.2 and Prompt 4:
- One call through the FAST role of the LLM layer.
- Returns JSON {intent, clarification_message, standalone_query} validated via Pydantic.
- Retries once on invalid output, then fails open to SEARCH with the raw user message.
- Canned GREETING_MESSAGE from config for pure greetings (never free generation).
- Messages mixing a greeting with a question are routed to SEARCH.
- Rewrites pronouns/references using history without adding facts not in the conversation.
- Ignores fallback responses in conversation history so they are not treated as knowledge.
"""
import json
import re
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

from app.core.config import settings
from app.core.logger import logger
from app.models.schemas import (
    ChatMessage,
    MessageKind,
    RouterIntent,
    RouterDecision,
)
from app.services.llm.base import LLMAdapter
from app.services.llm.factory import get_llm_adapter

ROUTER_SYSTEM_PROMPT = """You are an intent routing and query rewriting component for a knowledge base assistant.

Your task is to analyze the user's latest message in the context of recent conversation history and return a JSON object with this exact schema:
{
  "intent": "GREETING" | "CLARIFY" | "SEARCH",
  "clarification_message": string or null,
  "standalone_query": string or null
}

Classification and Rewriting Rules:
1. GREETING:
   - Pure social messages or pleasantries ("hi", "hello", "thanks", "thank you", "goodbye").
   - Set intent to "GREETING", clarification_message to null, and standalone_query to null.
   - EXCEPTION: Messages that mix a greeting with a question (e.g., "Hi, what is a blockchain?") MUST be classified as SEARCH.

2. CLARIFY:
   - The user's query is too vague, ambiguous, or lacks context to search (e.g., "how do I fix it?", "what is the other one?", "why does that happen?" when the previous conversation provides no clear referent).
   - Set intent to "CLARIFY", clarification_message to a polite, specific question asking what they mean, and standalone_query to null.

3. SEARCH:
   - Any question or statement seeking facts or knowledge.
   - Set intent to "SEARCH" and clarification_message to null.
   - Produce a "standalone_query":
     * If the message refers to prior topics via pronouns ("it", "they", "that", "the previous one"), rewrite it into a self-contained question using entities from the history.
     * STRICT CONSTRAINT: Do NOT introduce new facts, assumptions, or external entities not mentioned in the conversation.
     * If the query is already self-contained, standalone_query should match the user's query.

Important:
- Any turn in conversation history marked with [No information found in knowledge base] indicates a fallback where no knowledge was available. Do NOT treat fallback turns as factual knowledge.
- Respond ONLY with the raw JSON object. Do not wrap in markdown codeblocks. Do not include explanation.
"""


@dataclass
class RouterResult:
    """Structured result returned by the IntentRouter."""
    intent: RouterIntent
    standalone_query: str
    reply: Optional[str] = None
    clarification_message: Optional[str] = None
    raw_output: Optional[str] = None
    retries: int = 0
    failed_open: bool = False


def _clean_json_text(text: str) -> str:
    """Strip markdown codeblock formatting if present."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


class IntentRouter:
    """Routes user queries, produces canned replies, and rewrites follow-ups."""

    def __init__(self, adapter: Optional[LLMAdapter] = None, model: Optional[str] = None):
        self._adapter = adapter
        self._model = model

    def _get_llm(self):
        if self._adapter and self._model:
            return self._adapter, self._model
        return get_llm_adapter("router")

    def _format_history_for_prompt(self, history: List[ChatMessage]) -> str:
        """Format history turns, marking fallback messages so the LLM does not treat them as knowledge."""
        if not history:
            return "(No previous conversation history)"

        formatted_turns = []
        for msg in history:
            role = "User" if msg.role.lower() == "user" else "Assistant"
            if msg.kind == MessageKind.FALLBACK:
                formatted_turns.append(f"{role}: [No information found in knowledge base - fallback]")
            elif msg.kind == MessageKind.CLARIFY:
                formatted_turns.append(f"{role} (Clarification Request): {msg.content}")
            else:
                formatted_turns.append(f"{role}: {msg.content}")

        return "\n".join(formatted_turns)

    async def route(
        self,
        message: str,
        history: Optional[List[ChatMessage]] = None,
        request_id: Optional[str] = None,
    ) -> RouterResult:
        """Analyze message, determine intent, and rewrite if SEARCH."""
        clean_msg = message.strip()
        hist = history or []
        formatted_history = self._format_history_for_prompt(hist)

        prompt_content = (
            f"Conversation History:\n{formatted_history}\n\n"
            f"New User Message:\n\"{clean_msg}\"\n\n"
            "Return JSON matching {intent, clarification_message, standalone_query}:"
        )

        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": prompt_content}
        ]

        retries = 0
        raw_response: Optional[str] = None

        try:
            adapter, model = self._get_llm()

            # Attempt 1
            raw_response = await adapter.complete(
                system=ROUTER_SYSTEM_PROMPT,
                messages=messages,
                model=model,
                max_tokens=300,
                temperature=0.0,
            )

            decision = self._parse_and_validate(raw_response)

            if decision is None:
                # Retry once on invalid JSON / validation error
                retries += 1
                logger.info("Router output invalid, retrying once...", request_id=request_id)
                messages.append({"role": "assistant", "content": raw_response})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your previous response was not valid JSON matching the schema. "
                        "Please return ONLY a valid JSON object matching: "
                        "{\"intent\": \"GREETING\"|\"CLARIFY\"|\"SEARCH\", "
                        "\"clarification_message\": string or null, \"standalone_query\": string or null}"
                    ),
                })

                raw_response = await adapter.complete(
                    system=ROUTER_SYSTEM_PROMPT,
                    messages=messages,
                    model=model,
                    max_tokens=300,
                    temperature=0.0,
                )
                decision = self._parse_and_validate(raw_response)

            if decision is not None:
                return self._build_result(decision, clean_msg, raw_response, retries)

        except Exception as exc:
            logger.warning(
                f"Router LLM execution failed: {exc}. Failing open to SEARCH.",
                request_id=request_id,
            )

        # Persistent failure or exception: fail open to SEARCH with raw user message
        logger.warning(
            "Intent router failed open to SEARCH with raw query.",
            request_id=request_id,
            query=clean_msg,
        )
        return RouterResult(
            intent=RouterIntent.SEARCH,
            standalone_query=clean_msg,
            reply=None,
            clarification_message=None,
            raw_output=raw_response,
            retries=retries,
            failed_open=True,
        )

    def _parse_and_validate(self, text: str) -> Optional[RouterDecision]:
        """Attempt to parse and validate router output using Pydantic."""
        try:
            cleaned = _clean_json_text(text)
            data = json.loads(cleaned)
            return RouterDecision.model_validate(data)
        except Exception:
            return None

    def _build_result(
        self,
        decision: RouterDecision,
        raw_msg: str,
        raw_output: str,
        retries: int,
    ) -> RouterResult:
        """Construct RouterResult from valid RouterDecision."""
        if decision.intent == RouterIntent.GREETING:
            # GREETING returns canned GREETING_MESSAGE from config (never free generation)
            return RouterResult(
                intent=RouterIntent.GREETING,
                standalone_query=raw_msg,
                reply=settings.GREETING_MESSAGE,
                clarification_message=None,
                raw_output=raw_output,
                retries=retries,
                failed_open=False,
            )
        elif decision.intent == RouterIntent.CLARIFY:
            clarify_text = decision.clarification_message or (
                "Could you please provide more details or clarify what specific concept you mean?"
            )
            return RouterResult(
                intent=RouterIntent.CLARIFY,
                standalone_query=raw_msg,
                reply=clarify_text,
                clarification_message=clarify_text,
                raw_output=raw_output,
                retries=retries,
                failed_open=False,
            )
        else:  # SEARCH
            standalone = (decision.standalone_query or raw_msg).strip()
            return RouterResult(
                intent=RouterIntent.SEARCH,
                standalone_query=standalone or raw_msg,
                reply=None,
                clarification_message=None,
                raw_output=raw_output,
                retries=retries,
                failed_open=False,
            )


_intent_router_instance: Optional[IntentRouter] = None


def get_intent_router() -> IntentRouter:
    """Return the global IntentRouter singleton."""
    global _intent_router_instance
    if _intent_router_instance is None:
        _intent_router_instance = IntentRouter()
    return _intent_router_instance
