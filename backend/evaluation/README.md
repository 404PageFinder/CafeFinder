# Evaluation Suite

Validation harness for the CafeFinder pipeline. Runs a curated set of YouTube links through `run_pipeline()`, compares results against ground-truth, and reports accuracy + confidence-calibration metrics.

---

## Why this exists

Before you ship Phase 2 (screenshot OCR), you need to know:
- How often does Phase 1 actually pick the right place? (Top-1 accuracy)
- How often is the right answer at least *in* the top 3? (Top-3 accuracy)
- Is the system humble when uncertain? (low-confidence rate)
- **Most important:** how often does it confidently give a wrong answer? (wrong-high-confidence rate)

The fourth one is the dangerous bucket. A system that's wrong with low confidence is annoying. A system that's wrong with high confidence misleads users — and if you build screenshot OCR or a Flutter app on top of it, you bake in that miscalibration.

---

## Files

| File | Purpose |
|---|---|
| `dataset.json` | Test cases — URL + expected place + tags. Currently 8 seeded entries; fill out to 50. |
| `match.py` | Compares expected vs actual. Place-id-first, name+city fallback. |
| `metrics.py` | Computes Top-1, Top-3, low-conf rate, wrong-high-conf rate. Slicing by difficulty/tag. |
| `run_eval.py` | Async runner. Calls `run_pipeline()` directly — no server, no DB writes. |
| `results/` | Output directory. Each run creates `results/<timestamp>/` with three files. |

---

## Filling the dataset

The seed file has 8 cases with `REPLACE_ME_001` through `REPLACE_ME_008` placeholder URLs. Replace each with a real YouTube/Shorts link that clearly shows ONE cafe or restaurant. Aim for 50 cases total.

For each case, fill in:

- `url` — the actual YouTube/Shorts link
- `expected.place_name` — the real name (this is your ground truth)
- `expected.google_place_id` — **strongly recommended**. Find the cafe in Google Maps, share, copy the URL, and extract the `ChIJ...` part. This is the gold-standard match key. Without it, the matcher falls back to fuzzy name + city — less reliable.
- `expected.city` and `expected.area` — for the matcher fallback and for slicing metrics
- `tags` — for slicing metrics. Suggested tags:
  - `chain` / `indie`
  - `name_in_title` / `name_in_caption` / `name_only_in_video`
  - `branch_disambiguation` (for chains where picking the right branch matters)
  - `low_signal` (negative tests — should fail gracefully)
  - city tag like `hyderabad`, `bengaluru`, `mumbai`
- `difficulty` — `easy` / `medium` / `hard` / `very_hard`

### Recommended dataset composition for 50 cases

```
20 easy   — name clearly in title/description, single-location indie cafes
15 medium — name in description only, or chain that needs branch disambiguation
10 hard   — name only visible in video (no OCR yet — these test fallback behavior)
 5 very_hard — negative tests; system should report low confidence
```

This mix tells you both the ceiling (easy cases — what's the best you can do) and the floor (hard cases — does the system at least fail safely).

---

## Running

```bash
# Default — runs all cases in dataset.json with concurrency 3
python -m evaluation.run_eval

# Custom dataset
python -m evaluation.run_eval --dataset evaluation/datasets/regression_v2.json

# Higher concurrency (watch your YouTube API quota and Places API quota)
python -m evaluation.run_eval --concurrency 5

# Custom output dir
python -m evaluation.run_eval --output-dir evaluation/results/baseline_v1.5
```

Each run writes three files to `evaluation/results/<timestamp>/`:
- `case_results.json` — per-case detail (what was expected, what was returned, why)
- `metrics.json` — aggregate metrics for programmatic comparison
- `report.md` — human-readable markdown report

The runner exits with code 1 if `wrong_high_confidence_rate > 10%`. This makes it CI-friendly — you can gate Phase 2 work on this metric.

---

## Reading the report

Example output:

```
# Evaluation Report — dataset.json

## Summary
- Total cases: 50
- Completed: 47 | Failed: 1 | No results: 2

## Accuracy
- Top-1 accuracy: 62.0% (31 / 50)
- Top-3 accuracy: 80.0% (40 / 50)

## Confidence Calibration
- High confidence: 28
- Medium confidence: 14
- Low / none: 8
- Low-confidence rate: 16.0%
- ⚠ Wrong-high-confidence: 3 (6.0%) — most dangerous error type
- Avg top-1 confidence: 0.692  |  Median: 0.745

## By Difficulty
| Difficulty | N | Top-1 | Top-3 |
|---|---|---|---|
| easy | 20 | 90.0% | 100.0% |
| hard | 10 | 30.0% | 50.0% |
| medium | 15 | 53.3% | 80.0% |
| very_hard | 5 | 0.0% | 0.0% |
```

### What numbers should you target?

These are reasonable Phase 1 targets — adjust based on your dataset:

| Metric | Acceptable | Good | Excellent |
|---|---|---|---|
| Top-1 accuracy | ≥ 50% | ≥ 65% | ≥ 75% |
| Top-3 accuracy | ≥ 70% | ≥ 80% | ≥ 90% |
| Wrong-high-confidence rate | ≤ 10% | ≤ 5% | ≤ 2% |

If wrong-high-confidence is high, the fix is **calibration, not search quality** — raise the `confidence_high` threshold in `app/config.py` until that rate drops, even if it means more results land in "medium" territory.

---

## Workflow: improving the system

```
1. Set baseline:
     python -m evaluation.run_eval --output-dir evaluation/results/baseline

2. Make a change (tune ranking weights, tweak prompt, add a heuristic)

3. Re-run:
     python -m evaluation.run_eval --output-dir evaluation/results/experiment_X

4. Diff the two metrics.json files — did Top-1 improve without
   wrong-high-confidence getting worse?

5. If yes → keep change, commit. If no → revert.
```

Always check both metrics. It's easy to game Top-1 by being more confident; the wrong-high-confidence number stops you from doing that.

---

## Notes

- The runner needs your `.env` configured with real `YOUTUBE_API_KEY`, `GOOGLE_PLACES_API_KEY`, and `LLM_API_KEY`. It calls real APIs.
- Cost per run: ~50 YouTube API hits (free tier easily covers it) + 50 LLM calls + ~150 Places API hits. With `gpt-4o-mini` and Places New API, a 50-case run costs roughly $0.10–$0.30.
- The runner is async with configurable concurrency. Default 3 is conservative; bump to 5–10 if you're not hitting rate limits.
- Don't commit `results/` to git — it's already in `.gitignore`.
