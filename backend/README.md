# CafeFinder Backend — Phase 1.5

Backend service that takes a **YouTube link**, identifies the cafe/restaurant shown in the video, and returns ranked results with confidence scores.

> **Phase 1.5 adds:** branch-aware ranking, human-readable explanations, feedback API, and a 50-case evaluation harness with calibration metrics.

---

## What's new in 1.5

| Area | Change |
|---|---|
| **Ranking** | Detects when multiple results are branches of the same chain. Penalizes same-name candidates in the wrong area. Hard-filters non-food categories. |
| **API** | Every results response now includes a human-readable `explanation` string. New `POST /feedback` endpoint with `correct` / `not_correct` / `show_more` actions. |
| **Validation** | New `evaluation/` module: dataset format, async runner, metrics (Top-1, Top-3, low-conf rate, **wrong-high-confidence rate**), markdown report generator. |
| **Architecture** | Pipeline split into pure `run_pipeline()` (no DB) and DB-bound `run_analysis()`. The eval harness uses the pure version. |

---

## Architecture

```
Client
  │
  ▼
FastAPI  ──►  URL Parser  ──►  YouTube Metadata
                                    │
                                    ▼
                              LLM Extractor  ──►  Google Places Search
                                                        │
                                                        ▼
                                                   Ranking Engine
                                                   (branch-aware)
                                                        │
                                                        ▼
                                              Explanation Builder
                                                        │
                                                        ▼
                                                  PostgreSQL
                                                        │
                                              ┌─────────┴─────────┐
                                              ▼                   ▼
                                       /search/results       /feedback
```

Eval harness bypasses DB and FastAPI — calls `run_pipeline()` directly.

---

## Setup

```bash
git clone <your-repo>
cd cafefinder-backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Fill in YOUTUBE_API_KEY, GOOGLE_PLACES_API_KEY, LLM_API_KEY

docker-compose up -d postgres redis
uvicorn app.main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` for Swagger UI.

---

## API endpoints

### `POST /analyze-link`

```bash
curl -X POST http://localhost:8000/analyze-link \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/shorts/ABC123", "user_id": "u_1"}'
```

Returns `{ "search_id": "...", "status": "pending" }`. The pipeline runs as a background task.

### `GET /search/{search_id}/results`

Poll until `status: "completed"`. Response now includes `explanation`:

```json
{
  "search_id": "...",
  "status": "completed",
  "confidence_level": "high",
  "explanation": "Most likely: Roastery Coffee House in Banjara Hills, Hyderabad (4.5★, 1.2k reviews). Exact name match · City 'Hyderabad' matched.",
  "needs_user_input": false,
  "suggested_user_question": null,
  "results": [
    {
      "rank": 1,
      "name": "Roastery Coffee House",
      "address": "...",
      "google_place_id": "ChIJ...",
      "confidence": 0.91,
      "rating": 4.5,
      "review_count": 1200,
      "maps_url": "...",
      "reason": ["Exact name match", "City matched", "Area matched"]
    }
  ]
}
```

### `POST /feedback`

Three actions:

```bash
# Correct: user confirms the place
curl -X POST http://localhost:8000/feedback \
  -d '{"search_id": "...", "action": "correct", "selected_google_place_id": "ChIJ..."}'

# Not correct: user rejects
curl -X POST http://localhost:8000/feedback \
  -d '{"search_id": "...", "action": "not_correct", "selected_google_place_id": "ChIJ...", "feedback_text": "Wrong branch"}'

# Show more: user wants alternatives (Phase 2 will trigger relaxed re-query)
curl -X POST http://localhost:8000/feedback \
  -d '{"search_id": "...", "action": "show_more"}'
```

Response: `{ "feedback_id": "...", "status": "recorded", "next_action": null | "rerun_with_relaxed_filters" }`

---

## Project structure

```
cafefinder-backend/
├── app/
│   ├── main.py                  # FastAPI entry (registers analyze, feedback, health)
│   ├── config.py                # Settings (env-driven)
│   ├── database.py              # Async SQLAlchemy
│   │
│   ├── models/                  # ORM models
│   │   ├── search_history.py
│   │   ├── extracted_clues.py
│   │   ├── place_result.py
│   │   └── feedback.py          # NEW
│   │
│   ├── schemas/                 # Pydantic
│   │   ├── analyze.py           # Now includes `explanation` field
│   │   ├── llm.py
│   │   └── feedback.py          # NEW
│   │
│   ├── routers/
│   │   ├── analyze.py
│   │   ├── feedback.py          # NEW
│   │   └── health.py
│   │
│   ├── services/
│   │   ├── url_parser.py
│   │   ├── youtube_metadata.py
│   │   ├── llm_extractor.py
│   │   ├── places_search.py
│   │   ├── ranking_engine.py    # 1.5 — chain detection, branch penalty, food filter
│   │   ├── explanation.py       # NEW — human-readable summaries
│   │   └── analyzer.py          # 1.5 — split into run_pipeline + run_analysis
│   │
│   ├── prompts/
│   └── utils/
│
├── evaluation/                  # NEW — Phase 1.5 validation harness
│   ├── README.md
│   ├── dataset.json             # 50-link test set (8 seeded, fill in the rest)
│   ├── match.py                 # expected vs actual matcher
│   ├── metrics.py               # Top-1, Top-3, wrong-high-conf
│   ├── run_eval.py              # async runner
│   └── results/                 # output dir (gitignored)
│
└── tests/
    ├── test_url_parser.py
    ├── test_ranking.py
    ├── test_ranking_branches.py # NEW — chain disambiguation
    ├── test_metrics.py          # NEW — eval metrics
    └── test_explanation.py      # NEW — summary generation
```

---

## Running tests

```bash
# Unit tests — no external APIs, no DB
pytest -v

# Specific suites
pytest tests/test_ranking_branches.py -v
pytest tests/test_metrics.py -v
```

The unit tests run with zero external dependencies — perfect for CI.

---

## Running the evaluation suite

See [`evaluation/README.md`](evaluation/README.md) for full details.

```bash
# Set baseline before any tuning
python -m evaluation.run_eval --output-dir evaluation/results/baseline

# After making a ranking change, re-run and compare
python -m evaluation.run_eval --output-dir evaluation/results/experiment_1
diff evaluation/results/baseline/metrics.json evaluation/results/experiment_1/metrics.json
```

The runner exits with code 1 if `wrong_high_confidence_rate > 10%` — usable as a CI gate.

---

## Phase roadmap

- **Phase 1 ✅** — YouTube → metadata → LLM → Places → ranked results
- **Phase 1.5 ✅** *(this codebase)* — Branch-aware ranking, explanation field, feedback API, evaluation harness
- **Phase 2** — Screenshot upload + OCR (will plug into the existing `ocr_text` field in `llm_input`)
- **Phase 3** — Flutter mobile app
- **Phase 4** — Video frame extraction, speech-to-text, Celery workers
- **Phase 5** — Feedback-driven ranking improvements, saved places, user collections

---

## Tuning the system

The ranking weights live in `app/services/ranking_engine.py`:

```python
W_NORMAL = {"name": 0.35, "loc": 0.20, "cat": 0.15, "ev": 0.15, "qual": 0.10, "meta": 0.05}
W_CHAIN  = {"name": 0.20, "loc": 0.40, "cat": 0.10, "ev": 0.15, "qual": 0.10, "meta": 0.05}
```

Confidence thresholds live in `app/config.py`:

```python
confidence_high: float = 0.85    # Above → "high" label
confidence_medium: float = 0.55  # Above → "medium" label
```

Workflow for any tuning: baseline run → change → re-run → compare. The eval harness exists exactly so you don't tune blind.

---

## License

MIT
