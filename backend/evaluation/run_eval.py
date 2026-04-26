"""Evaluation runner.

Usage:
    python -m evaluation.run_eval                      # default dataset
    python -m evaluation.run_eval --dataset path.json  # custom dataset
    python -m evaluation.run_eval --concurrency 4      # parallel pipeline runs

Calls the pure run_pipeline directly — no DB writes, no FastAPI server.
Writes results to evaluation/results/<timestamp>/.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from app.services.analyzer import run_pipeline
from evaluation.match import ActualResult, Expected, expected_in_top_n, matches
from evaluation.metrics import (
    CaseResult,
    compute_metrics,
    metrics_to_dict,
    render_markdown_report,
)


def load_dataset(path: Path) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def to_actual_results(ranked) -> list[ActualResult]:
    return [
        ActualResult(
            google_place_id=r.place.google_place_id,
            name=r.place.name,
            address=r.place.address,
            confidence=r.confidence,
        )
        for r in ranked
    ]


async def run_one_case(case: dict, semaphore: asyncio.Semaphore) -> CaseResult:
    async with semaphore:
        case_id = case["id"]
        url = case["url"]
        expected = Expected(
            place_name=case["expected"].get("place_name"),
            google_place_id=case["expected"].get("google_place_id"),
            city=case["expected"].get("city"),
            area=case["expected"].get("area"),
            country=case["expected"].get("country"),
        )

        # Skip placeholder URLs
        if "REPLACE_ME" in url:
            return CaseResult(
                case_id=case_id,
                url=url,
                status="failed",
                error="placeholder_url",
                expected_name=expected.place_name,
                tags=case.get("tags", []),
            )

        try:
            result = await run_pipeline(url)
        except Exception as e:
            return CaseResult(
                case_id=case_id,
                url=url,
                status="failed",
                error=f"pipeline_crash: {e}",
                expected_name=expected.place_name,
                tags=case.get("tags", []),
            )

        if result.error:
            return CaseResult(
                case_id=case_id,
                url=url,
                status="failed",
                error=result.error,
                expected_name=expected.place_name,
                tags=case.get("tags", []),
                explanation=result.explanation,
            )

        actual = to_actual_results(result.ranked)
        if not actual:
            return CaseResult(
                case_id=case_id,
                url=url,
                status="no_results",
                confidence_level=result.confidence_level,
                expected_name=expected.place_name,
                tags=case.get("tags", []),
                explanation=result.explanation,
            )

        top1 = matches(expected, actual[0])
        top3 = expected_in_top_n(expected, actual, 3)

        return CaseResult(
            case_id=case_id,
            url=url,
            status="completed",
            confidence_level=result.confidence_level,
            top1_correct=top1,
            top3_correct=top3,
            top1_confidence=actual[0].confidence,
            actual_top1_name=actual[0].name,
            actual_top1_address=actual[0].address,
            expected_name=expected.place_name,
            tags=case.get("tags", []),
            explanation=result.explanation,
        )


async def run_all(dataset_path: Path, concurrency: int, output_dir: Path) -> int:
    data = load_dataset(dataset_path)
    cases = data["test_cases"]
    print(f"Loaded {len(cases)} test cases from {dataset_path}")

    semaphore = asyncio.Semaphore(concurrency)
    tasks = [run_one_case(c, semaphore) for c in cases]
    case_results: list[CaseResult] = []
    for i, fut in enumerate(asyncio.as_completed(tasks), 1):
        r = await fut
        case_results.append(r)
        marker = "✓" if r.top1_correct else ("·" if r.top3_correct else ("?" if r.status != "completed" else "✗"))
        print(f"  [{i}/{len(cases)}] {marker} {r.case_id} status={r.status} top1={r.top1_correct} top3={r.top3_correct}")

    # Sort by case_id for deterministic output
    case_results.sort(key=lambda r: r.case_id)

    metrics = compute_metrics(case_results, cases)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Per-case JSON
    cases_path = output_dir / "case_results.json"
    with open(cases_path, "w") as f:
        json.dump([asdict(c) for c in case_results], f, indent=2, default=str)

    # Aggregate metrics JSON
    metrics_path = output_dir / "metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics_to_dict(metrics), f, indent=2)

    # Markdown report
    report_path = output_dir / "report.md"
    with open(report_path, "w") as f:
        f.write(render_markdown_report(metrics, dataset_path.name))

    print()
    print(render_markdown_report(metrics, dataset_path.name))
    print()
    print(f"Wrote: {cases_path}")
    print(f"Wrote: {metrics_path}")
    print(f"Wrote: {report_path}")

    # Exit code reflects whether wrong-high-confidence rate is acceptable
    if metrics.wrong_high_confidence_rate > 0.10:
        print("⚠ wrong-high-confidence rate above 10% — investigate.")
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description="Run CafeFinder evaluation suite.")
    parser.add_argument(
        "--dataset",
        default=str(Path(__file__).parent / "dataset.json"),
        help="Path to dataset JSON",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Max concurrent pipeline runs (be mindful of API rate limits)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (defaults to evaluation/results/<timestamp>/)",
    )
    args = parser.parse_args()

    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(__file__).parent / "results" / ts

    rc = asyncio.run(run_all(Path(args.dataset), args.concurrency, out_dir))
    sys.exit(rc)


if __name__ == "__main__":
    main()
