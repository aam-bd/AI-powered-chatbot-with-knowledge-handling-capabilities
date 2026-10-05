"""LLM connectivity and latency verification script.

Sends a minimal test prompt through both 'router' and 'answer' roles.
Prints provider, model, and measured latency.
Strictly ensures the API key is NEVER printed or leaked into stdout/stderr.
"""
import asyncio
import sys
import time
from app.services.llm.factory import get_llm_adapter
from app.services.llm.base import LLMError
from app.core.config import settings


async def check_role(role: str) -> bool:
    """Send a tiny test prompt through the specified role and report latency."""
    print(f"\n--- Checking LLM role: '{role}' ---")
    try:
        adapter, model = get_llm_adapter(role)
        provider = getattr(adapter, "provider", None) or adapter.__class__.__name__
        base_url = getattr(adapter, "base_url", "default")

        print(f"  Provider: {provider}")
        print(f"  Base URL: {base_url}")
        print(f"  Model:    {model}")

        start_time = time.perf_counter()
        response = await adapter.complete(
            system="You are a test assistant.",
            messages=[{"role": "user", "content": "Reply with only the word: OK"}],
            model=model,
            max_tokens=10,
            temperature=0.0,
        )
        latency_ms = (time.perf_counter() - start_time) * 1000.0

        cleaned_response = response.strip().replace("\n", " ")
        print(f"  Latency:  {latency_ms:.1f} ms")
        print(f"  Response: {cleaned_response}")
        print(f"  Status:   SUCCESS")
        return True

    except LLMError as err:
        print(f"  Status:   FAILED (LLM Error)")
        print(f"  Detail:   {err}")
        return False
    except ValueError as err:
        print(f"  Status:   FAILED (Configuration Error)")
        print(f"  Detail:   {err}")
        return False
    except Exception as err:
        print(f"  Status:   FAILED (Unexpected Exception)")
        print(f"  Detail:   {type(err).__name__}: {err}")
        return False


async def main():
    print("==================================================")
    print("Knowledge-Base Chatbot: LLM Provider Health Check")
    print("==================================================")

    router_ok = await check_role("router")
    answer_ok = await check_role("answer")

    print("\n==================================================")
    if router_ok and answer_ok:
        print("RESULT: Both roles verified successfully!")
        sys.exit(0)
    else:
        print("RESULT: Verification failed for one or more roles.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
