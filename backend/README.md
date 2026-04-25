# CafeFinder Backend — Phase 1 MVP

Backend service that takes a **YouTube link**, extracts metadata, uses an LLM to identify the cafe/restaurant, searches Google Places, and returns ranked top 3 candidates with confidence scores.

> Phase 1 scope: YouTube only. Instagram, OCR, speech-to-text, and video frame analysis come in later phases.

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
                                                        │
                                                        ▼
                                                  PostgreSQL
```

---

## Tech Stack

- **API:** FastAPI + Uvicorn
- **DB:** PostgreSQL (async via SQLAlchemy 2.0 + asyncpg)
- **Cache:** Redis (reserved for Phase 2+)
- **External:** YouTube Data API v3, Google Places API (New), OpenAI or Anthropic LLM
- **Ranking:** rapidfuzz for fuzzy name matching

---

## Setup

### 1. Clone and install

```bash
git clone <your-repo-url>
cd cafefinder-backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your real API keys
```

You need:
- **`YOUTUBE_API_KEY`** — [Google Cloud Console](https://console.cloud.google.com/) → enable "YouTube Data API v3"
- **`GOOGLE_PLACES_API_KEY`** — same project, enable "Places API (New)"
- **`LLM_API_KEY`** — OpenAI or Anthropic key

### 3. Start Postgres + Redis

```bash
docker-compose up -d postgres redis
```

### 4. Run the API

```bash
uvicorn app.main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` for interactive Swagger UI.

---

## Testing the Pipeline

### Submit a YouTube link

```bash
curl -X POST http://localhost:8000/analyze-link \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/shorts/REPLACE_WITH_REAL_ID",
    "user_id": "test_user"
  }'
```

Response:

```json
{ "search_id": "uuid-here", "status": "pending" }
```

### Poll for results

```bash
curl http://localhost:8000/search/<search_id>/results
```

When `status: "completed"`:

```json
{
  "search_id": "...",
  "status": "completed",
  "confidence_level": "high",
  "results": [
    {
      "rank": 1,
      "name": "Roastery Coffee House",
      "address": "Banjara Hills, Hyderabad",
      "confidence": 0.91,
      "rating": 4.5,
      "maps_url": "...",
      "reason": ["Exact name match", "City matched", "Area matched"]
    }
  ]
}
```

---

## Project Structure

```
app/
├── main.py                  # FastAPI entry
├── config.py                # Settings (env-driven)
├── database.py              # Async SQLAlchemy
├── models/                  # ORM models
├── schemas/                 # Pydantic models
├── routers/                 # API endpoints
├── services/
│   ├── url_parser.py        # Step 1: parse YouTube URLs
│   ├── youtube_metadata.py  # Step 2: fetch via YouTube API
│   ├── llm_extractor.py     # Step 3: LLM JSON extraction
│   ├── places_search.py     # Step 4: Google Places (New)
│   ├── ranking_engine.py    # Step 5: weighted scoring
│   └── analyzer.py          # Orchestrator
├── prompts/                 # Versioned LLM prompts
└── utils/
```

---

## Phase Roadmap

- **Phase 1 ✅** — YouTube → metadata → LLM → Places → ranked results *(this codebase)*
- **Phase 2** — Screenshot upload + OCR
- **Phase 3** — Flutter mobile app
- **Phase 4** — Video frame extraction, speech-to-text, Celery workers
- **Phase 5** — User feedback loop, ranking improvements, saved places

---

## Run Tests

```bash
pytest -v
```

---

## License

MIT
