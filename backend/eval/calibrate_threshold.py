"""Threshold calibration script for Layer 1 retrieval guardrail.

Architecture §13 & Prompt 6:
- Reads calibration_set.json ONLY.
- It must NEVER read test_set.json (strictly enforced).
- Runs retrieval and reranking for each question.
- Sweeps candidate thresholds from 0.05 to 0.95.
- Reports precision, recall, F1, and out-of-scope fallback accuracy.
- Writes the recommended RERANK_THRESHOLD to results files and stdout.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

from app.core.logger import logger
from app.services.rag_engine import get_rag_engine


def validate_input_path(filepath: str) -> Path:
    """Validate that the calibration file is NOT test_set.json."""
    path = Path(filepath).resolve()
    if "test_set.json" in path.name.lower():
        raise ValueError(
            "VIOLATION OF ARCHITECTURE §13: calibrate_threshold.py is strictly prohibited "
            "from reading test_set.json! Calibration must only be performed on calibration_set.json."
        )
    if not path.is_file():
        raise FileNotFoundError(f"Calibration file not found at: {path}")
    return path


def load_calibration_dataset(filepath: Path) -> List[Dict[str, Any]]:
    """Load calibration items from JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Calibration dataset must be a JSON array of question objects.")
    return data


def run_retrieval_and_rerank(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Run RAG engine hybrid retrieval and reranking for each question in calibration set."""
    rag = get_rag_engine()
    scored_items = []

    print(f"\nEvaluating {len(items)} calibration questions with hybrid search + cross-encoder...")
    for idx, item in enumerate(items, 1):
        q_id = item.get("id", f"q-{idx}")
        category = item.get("category", "unknown")
        question = item.get("question", "")
        expected_behavior = item.get("expected_behavior", "answer")

        # Run hybrid retrieval
        candidates, _ = rag.hybrid_search(question)
        # Run cross-encoder rerank
        reranked, _ = rag.rerank(question, candidates)

        top_chunk = reranked[0] if reranked else None
        top_score = top_chunk.rerank_score if top_chunk else 0.0
        raw_top_score = top_chunk.raw_rerank_score if top_chunk else -999.0

        top_doc = top_chunk.document_name if top_chunk else "None"
        scored_items.append({
            "id": q_id,
            "category": category,
            "question": question,
            "expected_behavior": expected_behavior,
            "top_score": round(top_score, 4),
            "raw_top_score": round(raw_top_score, 4),
            "top_document": top_doc,
            "chunk_count": len(candidates),
        })

        print(
            f"  [{idx}/{len(items)}] ID: {q_id:<8} | Expected: {expected_behavior:<8} | "
            f"Top Score: {top_score:.4f} (raw: {raw_top_score:.2f}) | Doc: {top_doc}"
        )

    return scored_items


def sweep_thresholds(
    scored_items: List[Dict[str, Any]],
    step: float = 0.05,
) -> List[Dict[str, Any]]:
    """Sweep threshold values from 0.05 to 0.95 and calculate classification metrics."""
    sweep_results = []
    thresholds = [round(t * step, 2) for t in range(1, int(1.0 / step))]

    for t in thresholds:
        tp = 0
        fp = 0
        tn = 0
        fn = 0

        for item in scored_items:
            expected_answer = (item["expected_behavior"] == "answer")
            predicted_answer = (item["top_score"] >= t)

            if expected_answer and predicted_answer:
                tp += 1
            elif not expected_answer and predicted_answer:
                fp += 1
            elif not expected_answer and not predicted_answer:
                tn += 1
            elif expected_answer and not predicted_answer:
                fn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        fallback_acc = tn / (tn + fp) if (tn + fp) > 0 else 0.0

        sweep_results.append({
            "threshold": t,
            "tp": tp,
            "fp": fp,
            "tn": tn,
            "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "fallback_accuracy": round(fallback_acc, 4),
        })

    return sweep_results


def find_recommended_threshold(sweep_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Find threshold that maximizes F1 while prioritizing fallback accuracy (>= 1.0 if possible)."""
    if not sweep_results:
        return {"threshold": 0.50, "f1": 0.0, "fallback_accuracy": 0.0}

    # Primary goal: Maximize F1 with fallback_accuracy == 1.0 (no false positives admitted to LLM)
    safe_candidates = [r for r in sweep_results if r["fallback_accuracy"] >= 1.0 and r["recall"] > 0]
    if safe_candidates:
        # Sort by F1 descending, then closest to 0.50
        safe_candidates.sort(key=lambda r: (r["f1"], -abs(r["threshold"] - 0.50)), reverse=True)
        return safe_candidates[0]

    # Fallback: Maximize F1 overall
    sorted_by_f1 = sorted(sweep_results, key=lambda r: (r["f1"], r["fallback_accuracy"]), reverse=True)
    return sorted_by_f1[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate RERANK_THRESHOLD using calibration_set.json.")
    parser.add_argument(
        "--dataset",
        type=str,
        default="eval/calibration_set.json",
        help="Path to calibration dataset (MUST NOT be test_set.json).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="eval/results",
        help="Output directory for calibration results.",
    )
    args = parser.parse_args()

    # 1. Validation & Strict Isolation Check
    dataset_path = validate_input_path(args.dataset)
    items = load_calibration_dataset(dataset_path)

    # 2. Retrieval & Reranking
    scored_items = run_retrieval_and_rerank(items)

    # 3. Threshold Sweep
    sweep_results = sweep_thresholds(scored_items, step=0.05)
    best_candidate = find_recommended_threshold(sweep_results)
    recommended_threshold = best_candidate["threshold"]

    # 4. Print Summary Table
    print("\n" + "=" * 78)
    print(f"{'THRESHOLD SWEEP RESULTS':^78}")
    print("=" * 78)
    print(f"{'Threshold':<11} | {'Precision':<10} | {'Recall':<10} | {'F1':<10} | {'Fallback Acc':<14} | {'TP/FP/TN/FN'}")
    print("-" * 78)

    # Print a sample of thresholds around the best candidate
    for r in sweep_results:
        marker = " <== RECOMMENDED" if r["threshold"] == recommended_threshold else ""
        print(
            f"{r['threshold']:<11.2f} | {r['precision']:<10.4f} | {r['recall']:<10.4f} | "
            f"{r['f1']:<10.4f} | {r['fallback_accuracy']:<14.4f} | "
            f"{r['tp']}/{r['fp']}/{r['tn']}/{r['fn']}{marker}"
        )

    print("=" * 78)
    print(f"\nRECOMMENDED RERANK_THRESHOLD: {recommended_threshold:.2f}")
    print(f"Metrics at {recommended_threshold:.2f}:")
    print(f"  - Precision:         {best_candidate['precision'] * 100:.1f}%")
    print(f"  - Recall:            {best_candidate['recall'] * 100:.1f}%")
    print(f"  - F1 Score:          {best_candidate['f1']:.4f}")
    print(f"  - Fallback Accuracy: {best_candidate['fallback_accuracy'] * 100:.1f}%\n")

    # 5. Persist Results
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    result_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset_evaluated": str(dataset_path),
        "total_questions": len(items),
        "recommended_threshold": recommended_threshold,
        "recommended_metrics": best_candidate,
        "scored_items": scored_items,
        "sweep_table": sweep_results,
    }

    result_file = out_dir / f"calibration_{timestamp}.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result_payload, f, indent=2)

    recommended_file = out_dir / "recommended_threshold.json"
    with open(recommended_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "recommended_threshold": recommended_threshold,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "calibration_file": str(result_file),
            },
            f,
            indent=2,
        )

    print(f"Calibration results written to: {result_file}")
    print(f"Recommended threshold stored in: {recommended_file}")


if __name__ == "__main__":
    main()
