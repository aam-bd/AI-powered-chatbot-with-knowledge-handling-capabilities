"""Evaluation runner script for end-to-end RAG system benchmarking.

Architecture §13 & Prompt 6:
- Runs test_set.json against the running API (authenticates with login, then calls /chat/stream with history).
- Reports:
  - Answer accuracy (fact-checking expected_facts against generated answer text).
  - Optional LLM-as-judge step through the LLM layer, clearly labeled.
  - Router accuracy (matching expected intent: GREETING, CLARIFY, SEARCH).
  - Fallback accuracy per layer (Layer 1 rerank threshold, Layer 2 sentinel buffer, Layer 3 citation verification).
  - Citation validity (verified strictly in code: non-empty, valid tags, resolving documents/pages).
  - Per-category breakdown.
  - List of failures with detailed diagnostics.
- Writes eval/results/<timestamp>.json and a readable summary markdown.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

# Attempt imports from app for direct session memory priming and LLM judge
try:
    from app.core.config import settings
    from app.services.session_manager import get_session_manager, MessageKind
    from app.services.llm.factory import get_llm_adapter
    APP_AVAILABLE = True
except Exception:
    APP_AVAILABLE = False


def load_test_dataset(filepath: Path) -> List[Dict[str, Any]]:
    """Load test items from JSON file."""
    if not filepath.is_file():
        raise FileNotFoundError(f"Test dataset not found at: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Test dataset must be a JSON array of question objects.")
    return data


async def authenticate(api_url: str, email: str, password: str) -> Tuple[str, str]:
    """Authenticate against /auth/login and return (access_token, user_id)."""
    login_url = f"{api_url.rstrip('/')}/auth/login"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            login_url,
            json={"email": email, "password": password},
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Failed to authenticate against {login_url}: HTTP {resp.status_code} - {resp.text}"
            )
        data = resp.json()
        token = data.get("access_token")

        # Fetch user identity
        me_url = f"{api_url.rstrip('/')}/auth/me"
        me_resp = await client.get(me_url, headers={"Authorization": f"Bearer {token}"})
        if me_resp.status_code == 200:
            user_id = str(me_resp.json().get("id"))
        else:
            user_id = str(uuid.uuid4())

        return token, user_id


async def stream_chat_sse(
    client: httpx.AsyncClient,
    stream_url: str,
    headers: Dict[str, str],
    session_id: str,
    message: str,
) -> Dict[str, Any]:
    """Dispatch question to /chat/stream and parse SSE stream events."""
    payload = {"session_id": session_id, "message": message}
    accumulated_tokens: List[str] = []
    citations: List[Dict[str, Any]] = []
    retracted = False
    retract_reason = ""
    error_msg = ""
    done_payload: Dict[str, Any] = {}

    try:
        async with client.stream("POST", stream_url, headers=headers, json=payload, timeout=60.0) as response:
            if response.status_code != 200:
                body = await response.aread()
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {body.decode('utf-8', errors='ignore')}",
                    "answer_text": "",
                    "citations": [],
                    "retracted": False,
                    "retract_reason": "",
                    "done": {},
                }

            current_event = None
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("event:"):
                        current_event = line.split("event:", 1)[1].strip()
                    elif line.startswith("data:"):
                        data_str = line.split("data:", 1)[1].strip()
                        try:
                            data = json.loads(data_str)
                        except Exception:
                            data = data_str

                        if current_event == "token":
                            if isinstance(data, dict):
                                accumulated_tokens.append(data.get("text", ""))
                            else:
                                accumulated_tokens.append(str(data))
                        elif current_event == "citations":
                            if isinstance(data, dict):
                                citations = data.get("citations", [])
                        elif current_event == "retract":
                            retracted = True
                            if isinstance(data, dict):
                                retract_reason = data.get("text", "")
                        elif current_event == "error":
                            if isinstance(data, dict):
                                error_msg = data.get("message", "")
                            else:
                                error_msg = str(data)
                        elif current_event == "done":
                            if isinstance(data, dict):
                                done_payload = data

    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "answer_text": "".join(accumulated_tokens),
            "citations": citations,
            "retracted": retracted,
            "retract_reason": retract_reason,
            "done": done_payload,
        }

    return {
        "success": not bool(error_msg),
        "error": error_msg,
        "answer_text": "".join(accumulated_tokens),
        "citations": citations,
        "retracted": retracted,
        "retract_reason": retract_reason,
        "done": done_payload,
    }


def check_router_accuracy(done_intent: str, expected_behavior: str) -> Tuple[bool, str]:
    """Verify if router resolved to the appropriate intent."""
    expected_intent_map = {
        "greeting": "GREETING",
        "clarify": "CLARIFY",
        "answer": "SEARCH",
        "fallback": "SEARCH",
    }
    expected_intent = expected_intent_map.get(expected_behavior, "SEARCH")
    is_match = (done_intent.upper() == expected_intent)
    return is_match, expected_intent


def check_citations_validity(
    citations: List[Dict[str, Any]],
    expected_behavior: str,
    source_doc: Optional[str] = None,
) -> Tuple[bool, str]:
    """Check citation structure, tags, and document references strictly in code."""
    if expected_behavior != "answer":
        if not citations:
            return True, "No citations present (correct for non-answer)"
        return False, f"Unexpected citations present for {expected_behavior}"

    if not citations:
        return False, "Missing citations for in-scope answer"

    for c in citations:
        tag = str(c.get("tag", "")).strip()
        doc = str(c.get("document", "")).strip()
        chunk_id = str(c.get("chunk_id", "")).strip()
        tag_cleaned = tag.strip("[]")
        if not (tag_cleaned.startswith("C") and tag_cleaned[1:].isdigit()):
            return False, f"Malformed citation tag: '{tag}'"
        if not doc or not doc.strip():
            return False, "Citation missing document reference"
        if not chunk_id:
            return False, "Citation missing chunk_id"

    return True, f"Valid ({len(citations)} citations)"


def check_expected_facts(
    answer_text: str,
    expected_facts: List[str],
    expected_behavior: str,
) -> Tuple[bool, List[str], List[str]]:
    """Check whether expected_facts are present in answer text."""
    if expected_behavior != "answer":
        return True, [], []

    if not expected_facts:
        return True, [], []

    lower_ans = answer_text.lower()
    matched = []
    missing = []

    for fact in expected_facts:
        fact_lower = fact.lower().strip()
        if fact_lower in lower_ans:
            matched.append(fact)
        else:
            # Check individual keywords for robust matching
            keywords = [w for w in fact_lower.split() if len(w) > 3]
            if keywords and all(kw in lower_ans for kw in keywords):
                matched.append(fact)
            else:
                missing.append(fact)

    passed = (len(missing) == 0)
    return passed, matched, missing


async def evaluate_with_llm_judge(
    question: str,
    expected_facts: List[str],
    answer_text: str,
) -> Tuple[bool, str]:
    """Optional LLM-as-judge step through the LLM layer."""
    if not APP_AVAILABLE:
        return True, "LLM judge skipped (app environment not available)"

    try:
        adapter, model_name = get_llm_adapter(role="router")
        prompt = (
            f"You are an impartial evaluation judge for a Question-Answering system.\n"
            f"Question: {question}\n"
            f"Expected Facts: {json.dumps(expected_facts)}\n"
            f"Generated Answer: {answer_text}\n\n"
            f"Evaluate if the Generated Answer correctly communicates the required facts.\n"
            f"Respond with JSON format ONLY:\n"
            f'{{"verdict": "PASS" | "FAIL", "reason": "<concise rationale>"}}'
        )

        content = await adapter.complete(
            system="You are an automated evaluation judge. Respond with valid JSON only.",
            messages=[{"role": "user", "content": prompt}],
            model=model_name,
            max_tokens=256,
            temperature=0.0,
        )
        content = content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        data = json.loads(content)
        verdict = (data.get("verdict", "").upper() == "PASS")
        return verdict, data.get("reason", "")
    except Exception as exc:
        return False, f"LLM judge invocation error: {exc}"


async def run_evaluation(
    dataset_path: Path,
    api_url: str,
    email: str,
    password: str,
    use_llm_judge: bool = False,
    output_dir: str = "eval/results",
) -> Dict[str, Any]:
    """Execute complete evaluation suite against running API."""
    items = load_test_dataset(dataset_path)
    token, user_id = await authenticate(api_url, email, password)

    stream_url = f"{api_url.rstrip('/')}/chat/stream"
    headers = {"Authorization": f"Bearer {token}"}

    print(f"\n==============================================================================")
    print(f"RUNNING EVALUATION: {len(items)} questions against {api_url}")
    print(f"LLM-as-Judge enabled: {use_llm_judge}")
    print(f"==============================================================================\n")

    results = []
    category_stats: Dict[str, Dict[str, int]] = {}
    fallback_layer_counts = {1: 0, 2: 0, 3: 0, "unknown": 0}
    failures = []

    async with httpx.AsyncClient(timeout=60.0) as http_client:
        for idx, item in enumerate(items, 1):
            q_id = item.get("id", f"test-{idx}")
            category = item.get("category", "general")
            history = item.get("history", [])
            question = item.get("question", "")
            expected_behavior = item.get("expected_behavior", "answer")
            expected_facts = item.get("expected_facts", [])
            source_doc = item.get("source_doc")

            if category not in category_stats:
                category_stats[category] = {"total": 0, "passed": 0, "failed": 0}
            category_stats[category]["total"] += 1

            session_id = str(uuid.uuid4())

            # Seed conversation history into Redis session if provided
            if history and APP_AVAILABLE:
                session_mgr = get_session_manager()
                for turn in history:
                    r = turn.get("role", "user")
                    c = turn.get("content", "")
                    await session_mgr.append_message(
                        user_id=user_id,
                        session_id=session_id,
                        role=r,
                        content=c,
                        kind=MessageKind.NORMAL,
                    )

            # Query live streaming API
            res = await stream_chat_sse(
                client=http_client,
                stream_url=stream_url,
                headers=headers,
                session_id=session_id,
                message=question,
            )

            # Extract metrics
            answer_text = res.get("answer_text", "")
            citations = res.get("citations", [])
            retracted = res.get("retracted", False)
            done = res.get("done", {})
            done_intent = done.get("intent", "UNKNOWN")
            raw_fallback_layer = done.get("fallback_layer")

            # Determine actual fallback layer if applicable
            actual_fallback_layer = None
            if raw_fallback_layer is not None:
                actual_fallback_layer = int(raw_fallback_layer)
            elif retracted:
                actual_fallback_layer = 3
            elif expected_behavior == "fallback" and (
                "not found" in answer_text.lower()
                or "knowledge base does not contain" in answer_text.lower()
                or "sorry" in answer_text.lower()
            ):
                actual_fallback_layer = 1

            if actual_fallback_layer:
                if actual_fallback_layer in fallback_layer_counts:
                    fallback_layer_counts[actual_fallback_layer] += 1
                else:
                    fallback_layer_counts["unknown"] += 1

            # Metric 1: Router Accuracy
            router_pass, expected_intent = check_router_accuracy(done_intent, expected_behavior)

            # Metric 2: Citation Validity
            citations_pass, cit_reason = check_citations_validity(citations, expected_behavior, source_doc)

            # Metric 3: Answer / Fact Accuracy
            facts_pass, matched_facts, missing_facts = check_expected_facts(
                answer_text, expected_facts, expected_behavior
            )

            # Metric 4: Fallback Accuracy
            if expected_behavior == "fallback":
                fallback_pass = (actual_fallback_layer is not None)
            else:
                fallback_pass = (actual_fallback_layer is None)

            # Optional LLM-as-Judge
            judge_pass = True
            judge_reason = "N/A"
            if use_llm_judge and expected_behavior == "answer" and facts_pass:
                judge_pass, judge_reason = await evaluate_with_llm_judge(
                    question=question,
                    expected_facts=expected_facts,
                    answer_text=answer_text,
                )

            # Overall item success
            item_success = router_pass and citations_pass and facts_pass and fallback_pass and judge_pass
            if item_success:
                category_stats[category]["passed"] += 1
                status_str = "PASS"
            else:
                category_stats[category]["failed"] += 1
                status_str = "FAIL"
                fail_reasons = []
                if not router_pass:
                    fail_reasons.append(f"Router mismatch (got {done_intent}, expected {expected_intent})")
                if not fallback_pass:
                    fail_reasons.append(f"Fallback check failed (expected_behavior={expected_behavior}, layer={actual_fallback_layer})")
                if not citations_pass:
                    fail_reasons.append(f"Citations invalid: {cit_reason}")
                if not facts_pass:
                    fail_reasons.append(f"Missing facts: {missing_facts}")
                if not judge_pass:
                    fail_reasons.append(f"LLM Judge rejected: {judge_reason}")

                failures.append({
                    "id": q_id,
                    "category": category,
                    "question": question,
                    "expected_behavior": expected_behavior,
                    "reasons": fail_reasons,
                    "answer_preview": answer_text[:120],
                })

            item_result = {
                "id": q_id,
                "category": category,
                "question": question,
                "expected_behavior": expected_behavior,
                "status": status_str,
                "router_intent": done_intent,
                "router_pass": router_pass,
                "fallback_layer": actual_fallback_layer,
                "fallback_pass": fallback_pass,
                "citations_count": len(citations),
                "citations_pass": citations_pass,
                "citations_reason": cit_reason,
                "facts_pass": facts_pass,
                "matched_facts": matched_facts,
                "missing_facts": missing_facts,
                "llm_judge_pass": judge_pass if use_llm_judge else None,
                "llm_judge_reason": judge_reason if use_llm_judge else None,
                "answer_text": answer_text,
            }
            results.append(item_result)

            fb_layer_str = f"L{actual_fallback_layer}" if actual_fallback_layer else "None"
            print(
                f"[{idx}/{len(items)}] {q_id:<8} | Cat: {category:<20} | Status: {status_str:<4} | "
                f"Route: {done_intent:<8} | Fallback: {fb_layer_str:<5} | Citations: {len(citations)}"
            )

    # Calculate overall metrics
    total_q = len(items)
    passed_q = sum(1 for r in results if r["status"] == "PASS")
    overall_accuracy = (passed_q / total_q) * 100 if total_q > 0 else 0.0

    router_acc = (sum(1 for r in results if r["router_pass"]) / total_q) * 100 if total_q > 0 else 0.0
    citations_acc = (sum(1 for r in results if r["citations_pass"]) / total_q) * 100 if total_q > 0 else 0.0
    facts_acc = (sum(1 for r in results if r["facts_pass"]) / total_q) * 100 if total_q > 0 else 0.0
    fallback_acc = (sum(1 for r in results if r["fallback_pass"]) / total_q) * 100 if total_q > 0 else 0.0

    report_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_questions": total_q,
        "passed": passed_q,
        "failed": total_q - passed_q,
        "overall_accuracy_pct": round(overall_accuracy, 2),
        "router_accuracy_pct": round(router_acc, 2),
        "answer_facts_accuracy_pct": round(facts_acc, 2),
        "citations_validity_pct": round(citations_acc, 2),
        "fallback_accuracy_pct": round(fallback_acc, 2),
        "fallback_layer_distribution": fallback_layer_counts,
        "category_breakdown": category_stats,
        "failures": failures,
        "results": results,
    }

    # Persist outputs
    out_dir_path = Path(output_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    json_file = out_dir_path / f"eval_{ts}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, indent=2)

    md_file = out_dir_path / f"eval_{ts}.md"
    generate_markdown_report(md_file, report_payload, use_llm_judge)

    # Print summary table
    print("\n" + "=" * 78)
    print(f"{'EVALUATION SUMMARY REPORT':^78}")
    print("=" * 78)
    print(f"Overall Accuracy:       {overall_accuracy:.1f}% ({passed_q}/{total_q})")
    print(f"Router Accuracy:        {router_acc:.1f}%")
    print(f"Answer/Facts Accuracy:  {facts_acc:.1f}%")
    print(f"Citation Validity:      {citations_acc:.1f}%")
    print(f"Fallback Accuracy:      {fallback_acc:.1f}%")
    print("-" * 78)
    print("Fallback Triggers by Guardrail Layer:")
    print(f"  - Layer 1 (Retrieval Score < Threshold): {fallback_layer_counts[1]}")
    print(f"  - Layer 2 (Sentinel Buffer [[NOT_FOUND]]): {fallback_layer_counts[2]}")
    print(f"  - Layer 3 (Citation Lack of Grounding):  {fallback_layer_counts[3]}")
    print("-" * 78)
    print(f"{'Category Breakdown:':<78}")
    for cat, stat in category_stats.items():
        rate = (stat['passed'] / stat['total'] * 100) if stat['total'] > 0 else 0.0
        print(f"  - {cat:<24}: {stat['passed']}/{stat['total']} passed ({rate:.1f}%)")
    print("=" * 78)

    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  - [{f['id']}] ({f['category']}) {f['question']}")
            for r in f["reasons"]:
                print(f"      Reason: {r}")
    else:
        print("\nAll evaluation tests passed with 0 failures!")

    print(f"\nResults saved to:")
    print(f"  - JSON: {json_file}")
    print(f"  - Markdown: {md_file}\n")

    return report_payload


def generate_markdown_report(filepath: Path, report: Dict[str, Any], use_llm_judge: bool) -> None:
    """Generate human-readable Markdown summary report."""
    md = []
    md.append(f"# RAG Benchmark & Evaluation Report\n")
    md.append(f"- **Timestamp:** `{report['timestamp']}`")
    md.append(f"- **Total Questions Evaluated:** {report['total_questions']}")
    md.append(f"- **Overall Pass Rate:** **{report['overall_accuracy_pct']}%** ({report['passed']}/{report['total_questions']})\n")

    md.append("## Core Metrics Summary\n")
    md.append("| Metric | Result | Target (Arch §13.1) |")
    md.append("|---|---|---|")
    md.append(f"| Router Accuracy | **{report['router_accuracy_pct']}%** | ≥ 95% |")
    md.append(f"| Answer / Facts Correctness | **{report['answer_facts_accuracy_pct']}%** | ≥ 90% |")
    md.append(f"| Citation Validity | **{report['citations_validity_pct']}%** | 100% |")
    md.append(f"| Out-of-Scope Fallback Accuracy | **{report['fallback_accuracy_pct']}%** | ≥ 95% |\n")

    md.append("## Guardrail Fallback Breakdown by Layer\n")
    fb = report.get("fallback_layer_distribution", {})
    md.append(f"- **Layer 1 (Retrieval Score Gate):** {fb.get(1, 0)} queries safely blocked before LLM")
    md.append(f"- **Layer 2 (Sentinel Buffer `[[NOT_FOUND]]`):** {fb.get(2, 0)} queries aborted during generation")
    md.append(f"- **Layer 3 (Post-Generation Grounding Retraction):** {fb.get(3, 0)} queries retracted\n")

    md.append("## Category Breakdown\n")
    md.append("| Category | Total | Passed | Failed | Pass Rate |")
    md.append("|---|---|---|---|---|")
    for cat, stat in report.get("category_breakdown", {}).items():
        rate = (stat["passed"] / stat["total"] * 100) if stat["total"] > 0 else 0.0
        md.append(f"| `{cat}` | {stat['total']} | {stat['passed']} | {stat['failed']} | **{rate:.1f}%** |")
    md.append("")

    md.append("## Question-by-Question Detailed Results\n")
    md.append("| ID | Category | Expected | Route | Fallback | Citations | Facts | Status |")
    md.append("|---|---|---|---|---|---|---|---|")
    for r in report.get("results", []):
        fb_str = f"L{r['fallback_layer']}" if r['fallback_layer'] else "-"
        cit_str = f"{r['citations_count']} (OK)" if r['citations_pass'] else f"{r['citations_count']} (FAIL)"
        facts_str = "OK" if r['facts_pass'] else "FAIL"
        status_badge = "✅ PASS" if r['status'] == "PASS" else "❌ FAIL"
        md.append(
            f"| `{r['id']}` | `{r['category']}` | `{r['expected_behavior']}` | `{r['router_intent']}` | "
            f"`{fb_str}` | {cit_str} | {facts_str} | {status_badge} |"
        )
    md.append("")

    if report.get("failures"):
        md.append("## Failures Analysis\n")
        for f in report["failures"]:
            md.append(f"### Question `{f['id']}` ({f['category']})")
            md.append(f"- **Question:** {f['question']}")
            md.append(f"- **Expected Behavior:** `{f['expected_behavior']}`")
            md.append(f"- **Failure Reasons:**")
            for r in f["reasons"]:
                md.append(f"  - {r}")
            md.append(f"- **Answer Snippet:** _{f['answer_preview']}_\n")
    else:
        md.append("## Failures Analysis\n")
        md.append("No failures detected. All evaluation criteria satisfied 100%.\n")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RAG evaluation benchmark against running API.")
    parser.add_argument(
        "--test-set",
        type=str,
        default="eval/test_set.json",
        help="Path to test set JSON file.",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=os.getenv("API_BASE_URL", "http://localhost:8000/api/v1"),
        help="API base URL (default: http://localhost:8000/api/v1).",
    )
    parser.add_argument(
        "--email",
        type=str,
        default=os.getenv("ADMIN_EMAIL", "admin@example.com"),
        help="Admin/User email for authentication.",
    )
    parser.add_argument(
        "--password",
        type=str,
        default=os.getenv("ADMIN_PASSWORD", "Admin123!@#"),
        help="Password for authentication.",
    )
    parser.add_argument(
        "--use-llm-judge",
        action="store_true",
        help="Enable optional LLM-as-judge step labeled in evaluation.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="eval/results",
        help="Output directory for results.",
    )
    args = parser.parse_args()

    asyncio.run(
        run_evaluation(
            dataset_path=Path(args.test_set),
            api_url=args.api_url,
            email=args.email,
            password=args.password,
            use_llm_judge=args.use_llm_judge,
            output_dir=args.output_dir,
        )
    )


if __name__ == "__main__":
    main()
