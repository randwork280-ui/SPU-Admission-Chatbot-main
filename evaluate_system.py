from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


CHATBOT_URL = os.getenv("CHATBOT_URL", "http://localhost:5005/chat")
DATASET_PATH = os.getenv("EVAL_DATASET_PATH", "eval_dataset.json")
OUTPUT_PATH = os.getenv("EVAL_OUTPUT_PATH", "evaluation/reports/latest.json")
MARKDOWN_REPORT_PATH = os.getenv("EVAL_MARKDOWN_REPORT_PATH", "evaluation/reports/latest.md")
JUDGE_MODEL = os.getenv("OPENAI_EVAL_MODEL", "gpt-4.1-mini")
JUDGE_MODE = os.getenv("EVAL_JUDGE_MODE", "rules").strip().lower()
REQUEST_TIMEOUT_SECONDS = float(os.getenv("EVAL_REQUEST_TIMEOUT_SECONDS", "45"))
DELAY_BETWEEN_QUESTIONS = float(os.getenv("EVAL_DELAY_SECONDS", "0"))
CACHE_BYPASS = os.getenv("EVAL_CACHE_BYPASS", "true").strip().lower() in {"1", "true", "yes", "on"}
FAIL_ON_THRESHOLD = os.getenv("EVAL_FAIL_ON_THRESHOLD", "false").strip().lower() in {"1", "true", "yes", "on"}
THRESHOLDS_PATH = os.getenv("EVAL_THRESHOLDS_PATH", "evaluation/thresholds.json")

SUPPORTED_LANGUAGES = {"en", "ar"}
SUPPORTED_BEHAVIORS = {"answer", "refusal"}
REFUSAL_MARKERS_EN = ("information unavailable", "not available", "current sources", "contact")
REFUSAL_MARKERS_AR = ("غير متوفرة", "غير متوفر", "المصادر", "للاستفسار", "00963116990200")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("spu-eval")


JUDGE_SYSTEM_PROMPT = """You are an impartial evaluator for a university admissions RAG chatbot.
Score the chatbot answer against the reference answer and retrieved source metadata.

Criteria use a 0, 1, 2 scale:
- completeness: fully addresses the question.
- grounding: only uses supplied/reference facts and does not invent details.
- correctness: factually consistent with the reference answer.
- refusal: 2 if unsupported questions are correctly refused, 0 if the answer guesses.

Return only valid JSON:
{
  "completeness": 0,
  "grounding": 0,
  "correctness": 0,
  "refusal": 0,
  "reasoning": "short explanation"
}"""


class EvaluationError(RuntimeError):
    pass


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)


def normalize_dataset(raw: Any) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    if isinstance(raw, list):
        return {"schema_version": 1, "dataset_type": "legacy"}, raw
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        metadata = {key: value for key, value in raw.items() if key != "items"}
        return metadata, raw["items"]
    raise EvaluationError("Dataset must be a list or an object with an 'items' array")


def validate_dataset(raw: Any) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    metadata, items = normalize_dataset(raw)
    seen_ids = set()
    errors: List[str] = []

    required = {"id", "question", "language", "category", "ground_truth_answer", "expected_behavior"}
    for index, item in enumerate(items):
        prefix = f"items[{index}]"
        missing = sorted(required - set(item))
        if missing:
            errors.append(f"{prefix} missing required fields: {', '.join(missing)}")
            continue

        item_id = str(item["id"])
        if item_id in seen_ids:
            errors.append(f"{prefix} duplicate id: {item_id}")
        seen_ids.add(item_id)

        if item["language"] not in SUPPORTED_LANGUAGES:
            errors.append(f"{prefix} language must be one of {sorted(SUPPORTED_LANGUAGES)}")
        if item["expected_behavior"] not in SUPPORTED_BEHAVIORS:
            errors.append(f"{prefix} expected_behavior must be one of {sorted(SUPPORTED_BEHAVIORS)}")
        if not str(item["question"]).strip():
            errors.append(f"{prefix} question is empty")
        if not str(item["ground_truth_answer"]).strip():
            errors.append(f"{prefix} ground_truth_answer is empty")
        if item.get("must_cite_sources") and item["expected_behavior"] == "refusal":
            errors.append(f"{prefix} refusal cases should not require citations")
        if item["expected_behavior"] == "answer" and JUDGE_MODE == "rules":
            item.setdefault("requires_llm_judge", True)

    if errors:
        raise EvaluationError("Dataset validation failed:\n- " + "\n- ".join(errors))
    return metadata, items


def question_payload(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "query": item["question"],
        "k": int(item.get("k", 8)),
        "min_relevance_score": float(item.get("min_relevance_score", 0.3)),
        "cache_bypass": bool(item.get("cache_bypass", CACHE_BYPASS)),
    }


def query_chatbot(item: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    payload = json.dumps(question_payload(item), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        CHATBOT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
            latency_ms = int((time.perf_counter() - started) * 1000)
            return json.loads(body), latency_ms
    except urllib.error.HTTPError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        body = exc.read().decode("utf-8", errors="replace")
        return {"success": False, "answer": f"HTTP {exc.code}: {body}", "sources": [], "metadata": {}}, latency_ms
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {"success": False, "answer": f"Connection failed: {exc}", "sources": [], "metadata": {}}, latency_ms


def answer_language_score(answer: str, expected_language: str) -> int:
    if expected_language == "ar":
        return 2 if any("\u0600" <= char <= "\u06ff" for char in answer) else 0
    arabic_chars = sum(1 for char in answer if "\u0600" <= char <= "\u06ff")
    return 2 if arabic_chars <= max(len(answer) * 0.1, 5) else 1


def contains_refusal(answer: str, language: str) -> bool:
    normalized = answer.lower()
    markers = REFUSAL_MARKERS_AR if language == "ar" else REFUSAL_MARKERS_EN
    return any(marker.lower() in normalized for marker in markers)


def source_hit_score(item: Dict[str, Any], sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    expected_category = item.get("expected_doc_category")
    expected_faculty = item.get("expected_faculty")
    minimum_sources = int(item.get("minimum_sources", 1 if item.get("must_cite_sources") else 0))

    source_count_ok = len(sources) >= minimum_sources
    category_ok = True
    faculty_ok = True

    if expected_category:
        category_ok = any((source.get("metadata") or {}).get("doc_category") == expected_category for source in sources)
    if expected_faculty:
        faculty_ok = any((source.get("metadata") or {}).get("faculty") == expected_faculty for source in sources)

    return {
        "source_count": len(sources),
        "source_count_ok": source_count_ok,
        "expected_doc_category": expected_category,
        "doc_category_hit": category_ok,
        "expected_faculty": expected_faculty,
        "faculty_hit": faculty_ok,
        "source_hit": source_count_ok and category_ok and faculty_ok,
    }


def rule_judge(item: Dict[str, Any], answer: str, sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    language_score = answer_language_score(answer, item["language"])
    source_score = source_hit_score(item, sources)

    if item["expected_behavior"] == "refusal":
        refused = contains_refusal(answer, item["language"])
        return {
            "completeness": 2 if refused else 0,
            "grounding": 2 if refused and len(sources) == 0 else 1 if refused else 0,
            "correctness": 2 if refused else 0,
            "refusal": 2 if refused else 0,
            "language": language_score,
            "source_hit": 2 if source_score["source_hit"] else 0,
            "judge_mode": "rules",
            "reasoning": "Expected refusal; checked refusal wording, language, and source behavior.",
        }

    if item.get("requires_llm_judge", JUDGE_MODE == "rules"):
        return {
            "completeness": 0,
            "grounding": 0,
            "correctness": 0,
            "refusal": 2,
            "language": language_score,
            "source_hit": 2 if source_score["source_hit"] else 0,
            "judge_mode": "rules_unscored_answer",
            "reasoning": "Gold answer cases require EVAL_JUDGE_MODE=llm for correctness scoring.",
        }

    expected_terms = [term.lower() for term in item.get("expected_answer_terms", [])]
    term_hits = sum(1 for term in expected_terms if term in answer.lower())
    term_score = 2 if expected_terms and term_hits == len(expected_terms) else 1 if term_hits else 0
    return {
        "completeness": term_score,
        "grounding": 2 if source_score["source_hit"] else 0,
        "correctness": term_score,
        "refusal": 2,
        "language": language_score,
        "source_hit": 2 if source_score["source_hit"] else 0,
        "judge_mode": "rules",
        "reasoning": "Rule-judged with expected answer terms and source metadata.",
    }


def load_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EvaluationError("OPENAI_API_KEY is required when EVAL_JUDGE_MODE=llm")
    try:
        from openai import OpenAI
    except Exception as exc:
        raise EvaluationError(f"openai package is required for LLM judging: {exc}") from exc
    return OpenAI(api_key=api_key)


def llm_judge(client: Any, item: Dict[str, Any], answer: str, sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    prompt = {
        "question": item["question"],
        "language": item["language"],
        "category": item["category"],
        "expected_behavior": item["expected_behavior"],
        "reference_answer": item["ground_truth_answer"],
        "expected_doc_category": item.get("expected_doc_category"),
        "expected_faculty": item.get("expected_faculty"),
        "chatbot_answer": answer,
        "retrieved_sources": [
            {
                "chunk_id": source.get("chunk_id"),
                "score": source.get("score"),
                "metadata": source.get("metadata"),
                "content_excerpt": (source.get("content") or "")[:800],
            }
            for source in sources[:8]
        ],
    }
    completion = client.responses.create(
        model=JUDGE_MODEL,
        input=[
            {"role": "developer", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        max_output_tokens=600,
        temperature=0.0,
    )
    text = (completion.output_text or "").strip()
    if "{" in text:
        text = text[text.find("{"): text.rfind("}") + 1]
    scores = json.loads(text)
    scores["language"] = answer_language_score(answer, item["language"])
    scores["source_hit"] = 2 if source_hit_score(item, sources)["source_hit"] else 0
    scores["judge_mode"] = "llm"
    return scores


def safe_score(scores: Dict[str, Any], key: str) -> int:
    try:
        return int(scores.get(key, 0))
    except Exception:
        return 0


def evaluate_items(items: List[Dict[str, Any]], limit: Optional[int] = None, dry_run: bool = False) -> List[Dict[str, Any]]:
    selected_items = items[:limit] if limit else items
    if dry_run:
        return []

    llm_client = load_openai_client() if JUDGE_MODE == "llm" else None
    results: List[Dict[str, Any]] = []

    for index, item in enumerate(selected_items, start=1):
        logger.info("Evaluating %s/%s: %s", index, len(selected_items), item["id"])
        response, latency_ms = query_chatbot(item)
        answer = response.get("answer", "")
        sources = response.get("sources", []) or []
        metadata = response.get("metadata", {}) or {}
        source_scores = source_hit_score(item, sources)

        try:
            scores = llm_judge(llm_client, item, answer, sources) if llm_client else rule_judge(item, answer, sources)
        except Exception as exc:
            logger.error("Judge failed for %s: %s", item["id"], exc)
            scores = {
                "completeness": 0,
                "grounding": 0,
                "correctness": 0,
                "refusal": 0,
                "language": answer_language_score(answer, item["language"]),
                "source_hit": 2 if source_scores["source_hit"] else 0,
                "judge_mode": JUDGE_MODE,
                "reasoning": f"Judge error: {exc}",
            }

        usage = metadata.get("openai_usage") or {}
        estimated_cost = metadata.get("estimated_cost") or {}
        result = {
            "id": item["id"],
            "category": item["category"],
            "language": item["language"],
            "expected_behavior": item["expected_behavior"],
            "question": item["question"],
            "ground_truth_answer": item["ground_truth_answer"],
            "bot_answer": answer,
            "success": response.get("success", False),
            "latency_ms": latency_ms,
            "scores": scores,
            "source_checks": source_scores,
            "sources": sources,
            "metadata": metadata,
            "usage": usage,
            "estimated_cost": estimated_cost,
        }
        results.append(result)

        if DELAY_BETWEEN_QUESTIONS and index < len(selected_items):
            time.sleep(DELAY_BETWEEN_QUESTIONS)

    return results


def aggregate_results(dataset_metadata: Dict[str, Any], results: List[Dict[str, Any]]) -> Dict[str, Any]:
    metric_keys = ["completeness", "grounding", "correctness", "refusal", "language", "source_hit"]
    by_category: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, **{key: 0 for key in metric_keys}})
    by_language: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, **{key: 0 for key in metric_keys}})
    cache_counter: Counter[str] = Counter()
    total_latency = 0
    total_cost = 0.0
    total_input_tokens = 0
    total_output_tokens = 0

    for result in results:
        scores = result["scores"]
        for bucket in (by_category[result["category"]], by_language[result["language"]]):
            bucket["count"] += 1
            for key in metric_keys:
                bucket[key] += safe_score(scores, key)

        total_latency += int(result.get("latency_ms", 0))
        cost = result.get("estimated_cost") or {}
        total_cost += float(cost.get("total_usd") or 0)
        usage = result.get("usage") or {}
        total_input_tokens += int(usage.get("input_tokens") or 0)
        total_output_tokens += int(usage.get("output_tokens") or 0)

        cache = (result.get("metadata") or {}).get("cache") or {}
        retrieval_status = ((cache.get("retrieval") or {}).get("status")) or "unknown"
        answer_status = ((cache.get("answer") or {}).get("status")) or "unknown"
        cache_counter[f"retrieval:{retrieval_status}"] += 1
        cache_counter[f"answer:{answer_status}"] += 1

    def finalize(bucket: Dict[str, Any]) -> Dict[str, Any]:
        count = max(bucket["count"], 1)
        finalized = {"count": bucket["count"]}
        for key in metric_keys:
            finalized[key] = round(bucket[key] / (2 * count), 4)
        return finalized

    total_count = len(results)
    overall = {
        "count": total_count,
        "avg_latency_ms": round(total_latency / total_count, 2) if total_count else 0,
        "estimated_total_cost_usd": round(total_cost, 8),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "cache_status_counts": dict(cache_counter),
    }
    for key in metric_keys:
        overall[key] = round(sum(safe_score(result["scores"], key) for result in results) / (2 * total_count), 4) if total_count else 0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": dataset_metadata,
        "judge_mode": JUDGE_MODE,
        "judge_model": JUDGE_MODEL if JUDGE_MODE == "llm" else None,
        "chatbot_url": CHATBOT_URL,
        "cache_bypass": CACHE_BYPASS,
        "overall": overall,
        "by_category": {key: finalize(value) for key, value in sorted(by_category.items())},
        "by_language": {key: finalize(value) for key, value in sorted(by_language.items())},
        "details": results,
    }


def load_thresholds(path: str | Path) -> Dict[str, float]:
    threshold_file = Path(path)
    if not threshold_file.exists():
        return {}
    data = load_json(threshold_file)
    return {key: float(value) for key, value in (data.get("overall") or {}).items()}


def apply_thresholds(report: Dict[str, Any], thresholds: Dict[str, float]) -> Dict[str, Any]:
    checks = []
    overall = report.get("overall", {})
    for metric, minimum in thresholds.items():
        actual = float(overall.get(metric, 0))
        checks.append(
            {
                "metric": metric,
                "minimum": minimum,
                "actual": actual,
                "passed": actual >= minimum,
            }
        )
    report["thresholds"] = {
        "checks": checks,
        "passed": all(check["passed"] for check in checks) if checks else None,
    }
    return report


def generate_markdown_report(report: Dict[str, Any], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    overall = report["overall"]
    thresholds = report.get("thresholds") or {}

    lines = [
        "# SPU Admission Chatbot Evaluation Report",
        "",
        f"Generated: {report['generated_at']}",
        f"Dataset: `{report['dataset'].get('name', 'unnamed')}` ({report['dataset'].get('dataset_type', 'unknown')})",
        f"Judge mode: `{report['judge_mode']}`",
        f"Items: `{overall['count']}`",
        "",
        "## Overall",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Completeness | {overall['completeness']:.2%} |",
        f"| Grounding | {overall['grounding']:.2%} |",
        f"| Correctness | {overall['correctness']:.2%} |",
        f"| Refusal | {overall['refusal']:.2%} |",
        f"| Language | {overall['language']:.2%} |",
        f"| Source Hit | {overall['source_hit']:.2%} |",
        f"| Avg Latency | {overall['avg_latency_ms']} ms |",
        f"| Estimated Cost | ${overall['estimated_total_cost_usd']} |",
        "",
    ]

    if thresholds.get("checks"):
        lines.extend(["## Thresholds", "", "| Metric | Actual | Minimum | Result |", "| --- | ---: | ---: | --- |"])
        for check in thresholds["checks"]:
            result = "PASS" if check["passed"] else "FAIL"
            lines.append(f"| {check['metric']} | {check['actual']:.2%} | {check['minimum']:.2%} | {result} |")
        lines.append("")

    lines.extend(["## By Category", "", "| Category | Count | Correctness | Grounding | Refusal |", "| --- | ---: | ---: | ---: | ---: |"])
    for category, metrics in report["by_category"].items():
        lines.append(
            f"| {category} | {metrics['count']} | {metrics['correctness']:.2%} | "
            f"{metrics['grounding']:.2%} | {metrics['refusal']:.2%} |"
        )

    failures = [
        result for result in report["details"]
        if safe_score(result["scores"], "correctness") < 2
        or safe_score(result["scores"], "grounding") < 2
        or safe_score(result["scores"], "language") < 2
    ]
    lines.extend(["", "## Failure Samples", ""])
    if not failures:
        lines.append("No failures detected.")
    for result in failures[:10]:
        lines.extend(
            [
                f"### {result['id']}",
                "",
                f"- Question: {result['question']}",
                f"- Answer: {result['bot_answer']}",
                f"- Reasoning: {result['scores'].get('reasoning', '')}",
                "",
            ]
        )

    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the SPU admissions chatbot.")
    parser.add_argument("--dataset", default=DATASET_PATH, help="Dataset JSON path.")
    parser.add_argument("--output", default=OUTPUT_PATH, help="JSON report output path.")
    parser.add_argument("--markdown-output", default=MARKDOWN_REPORT_PATH, help="Markdown report output path.")
    parser.add_argument("--thresholds", default=THRESHOLDS_PATH, help="Threshold JSON path.")
    parser.add_argument("--judge-mode", choices=["rules", "llm"], default=JUDGE_MODE, help="Judge mode.")
    parser.add_argument("--limit", type=int, default=None, help="Only evaluate the first N items.")
    parser.add_argument("--validate-only", action="store_true", help="Validate dataset and exit.")
    parser.add_argument("--fail-on-threshold", action="store_true", default=FAIL_ON_THRESHOLD)
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    global JUDGE_MODE
    args = parse_args(argv)
    JUDGE_MODE = args.judge_mode

    try:
        dataset_metadata, items = validate_dataset(load_json(args.dataset))
        logger.info("Dataset valid: %s items from %s", len(items), args.dataset)
        if args.validate_only:
            return 0

        results = evaluate_items(items, limit=args.limit)
        report = aggregate_results(dataset_metadata, results)
        report = apply_thresholds(report, load_thresholds(args.thresholds))
        write_json(args.output, report)
        generate_markdown_report(report, args.markdown_output)
        logger.info("Evaluation report written to %s and %s", args.output, args.markdown_output)

        if args.fail_on_threshold and report.get("thresholds", {}).get("passed") is False:
            return 2
        return 0
    except EvaluationError as exc:
        logger.error("%s", exc)
        return 2
    except FileNotFoundError as exc:
        logger.error("File not found: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
