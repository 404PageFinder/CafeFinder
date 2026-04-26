"""Evaluation metrics.

- Top-1 accuracy: % where the rank-1 result matches expected
- Top-3 accuracy: % where any of top 3 matches expected
- Low-confidence rate: % of cases where top result confidence < medium threshold
- Wrong-high-confidence rate: % where top-1 is WRONG but confidence is "high"
  (the most damaging error type — the user gets a confident wrong answer)
- No-results rate: % where the pipeline returned zero ranked results
- Failure rate: % where the pipeline errored out
"""

from dataclasses import dataclass, asdict, field
from statistics import mean, median

from evaluation.match import Expected, ActualResult, matches, expected_in_top_n


@dataclass
class CaseResult:
    case_id: str
    url: str
    status: str  # "completed" | "failed" | "no_results"
    error: str | None = None
    confidence_level: str | None = None  # high | medium | low | none
    top1_correct: bool = False
    top3_correct: bool = False
    top1_confidence: float = 0.0
    actual_top1_name: str | None = None
    actual_top1_address: str | None = None
    expected_name: str | None = None
    tags: list[str] = field(default_factory=list)
    explanation: str | None = None


@dataclass
class EvalMetrics:
    total: int
    completed: int
    failed: int
    no_results: int

    top1_correct: int
    top3_correct: int
    top1_accuracy: float
    top3_accuracy: float

    high_confidence: int
    medium_confidence: int
    low_confidence: int

    wrong_high_confidence: int
    wrong_high_confidence_rate: float
    low_confidence_rate: float

    avg_top1_confidence: float
    median_top1_confidence: float

    by_difficulty: dict[str, dict] = field(default_factory=dict)
    by_tag: dict[str, dict] = field(default_factory=dict)


def compute_metrics(case_results: list[CaseResult], cases_meta: list[dict]) -> EvalMetrics:
    """Compute aggregate metrics. cases_meta is the original test case list,
    used to slice metrics by difficulty / tag.
    """
    total = len(case_results)
    completed = sum(1 for r in case_results if r.status == "completed")
    failed = sum(1 for r in case_results if r.status == "failed")
    no_results = sum(1 for r in case_results if r.status == "no_results")

    top1 = sum(1 for r in case_results if r.top1_correct)
    top3 = sum(1 for r in case_results if r.top3_correct)

    high = sum(1 for r in case_results if r.confidence_level == "high")
    med = sum(1 for r in case_results if r.confidence_level == "medium")
    low = sum(1 for r in case_results if r.confidence_level in ("low", "none"))

    wrong_high = sum(
        1 for r in case_results
        if r.confidence_level == "high" and not r.top1_correct
        and r.status == "completed"
    )

    confidences = [r.top1_confidence for r in case_results if r.status == "completed"]
    avg_conf = mean(confidences) if confidences else 0.0
    med_conf = median(confidences) if confidences else 0.0

    # Slice by difficulty
    diff_meta = {c["id"]: c.get("difficulty", "unknown") for c in cases_meta}
    by_difficulty: dict[str, dict] = {}
    for r in case_results:
        d = diff_meta.get(r.case_id, "unknown")
        bucket = by_difficulty.setdefault(d, {"n": 0, "top1": 0, "top3": 0})
        bucket["n"] += 1
        bucket["top1"] += int(r.top1_correct)
        bucket["top3"] += int(r.top3_correct)
    for d, b in by_difficulty.items():
        b["top1_accuracy"] = round(b["top1"] / b["n"], 3) if b["n"] else 0.0
        b["top3_accuracy"] = round(b["top3"] / b["n"], 3) if b["n"] else 0.0

    # Slice by tag
    tags_meta = {c["id"]: c.get("tags", []) for c in cases_meta}
    by_tag: dict[str, dict] = {}
    for r in case_results:
        for tag in tags_meta.get(r.case_id, []):
            bucket = by_tag.setdefault(tag, {"n": 0, "top1": 0, "top3": 0})
            bucket["n"] += 1
            bucket["top1"] += int(r.top1_correct)
            bucket["top3"] += int(r.top3_correct)
    for tag, b in by_tag.items():
        b["top1_accuracy"] = round(b["top1"] / b["n"], 3) if b["n"] else 0.0
        b["top3_accuracy"] = round(b["top3"] / b["n"], 3) if b["n"] else 0.0

    return EvalMetrics(
        total=total,
        completed=completed,
        failed=failed,
        no_results=no_results,
        top1_correct=top1,
        top3_correct=top3,
        top1_accuracy=round(top1 / total, 3) if total else 0.0,
        top3_accuracy=round(top3 / total, 3) if total else 0.0,
        high_confidence=high,
        medium_confidence=med,
        low_confidence=low,
        wrong_high_confidence=wrong_high,
        wrong_high_confidence_rate=round(wrong_high / total, 3) if total else 0.0,
        low_confidence_rate=round(low / total, 3) if total else 0.0,
        avg_top1_confidence=round(avg_conf, 3),
        median_top1_confidence=round(med_conf, 3),
        by_difficulty=by_difficulty,
        by_tag=by_tag,
    )


def render_markdown_report(metrics: EvalMetrics, dataset_name: str = "dataset.json") -> str:
    m = metrics
    lines = [
        f"# Evaluation Report — {dataset_name}",
        "",
        "## Summary",
        f"- **Total cases:** {m.total}",
        f"- **Completed:** {m.completed} | **Failed:** {m.failed} | **No results:** {m.no_results}",
        "",
        "## Accuracy",
        f"- **Top-1 accuracy:** {m.top1_accuracy:.1%} ({m.top1_correct} / {m.total})",
        f"- **Top-3 accuracy:** {m.top3_accuracy:.1%} ({m.top3_correct} / {m.total})",
        "",
        "## Confidence Calibration",
        f"- **High confidence:** {m.high_confidence}",
        f"- **Medium confidence:** {m.medium_confidence}",
        f"- **Low / none:** {m.low_confidence}",
        f"- **Low-confidence rate:** {m.low_confidence_rate:.1%}",
        f"- **⚠ Wrong-high-confidence:** {m.wrong_high_confidence} ({m.wrong_high_confidence_rate:.1%}) — *most dangerous error type*",
        f"- **Avg top-1 confidence:** {m.avg_top1_confidence:.3f}  |  **Median:** {m.median_top1_confidence:.3f}",
        "",
        "## By Difficulty",
        "| Difficulty | N | Top-1 | Top-3 |",
        "|---|---|---|---|",
    ]
    for d, b in sorted(m.by_difficulty.items()):
        lines.append(f"| {d} | {b['n']} | {b['top1_accuracy']:.1%} | {b['top3_accuracy']:.1%} |")
    lines += ["", "## By Tag", "| Tag | N | Top-1 | Top-3 |", "|---|---|---|---|"]
    for tag, b in sorted(m.by_tag.items()):
        lines.append(f"| {tag} | {b['n']} | {b['top1_accuracy']:.1%} | {b['top3_accuracy']:.1%} |")
    return "\n".join(lines)


def metrics_to_dict(m: EvalMetrics) -> dict:
    return asdict(m)
