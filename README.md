# Lexis — GRE Vocabulary Agent

A voice-first GRE vocabulary tutor powered by Sarvam AI's speech APIs, LangGraph agent orchestration, and spaced repetition.

**Use case:** Someone with 30–60 days before their GRE exam who knows English but needs to close the gap to a 160+ Verbal score. They practice 15 minutes a day — on the commute, in bed, between meetings — by speaking, not typing.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Next.js Frontend                         │
│   Dashboard · Learn (voice) · Quiz · Reading Comprehension      │
└───────────────────────┬─────────────────────────────────────────┘
                        │ REST (JSON + base64 audio)
┌───────────────────────▼─────────────────────────────────────────┐
│                    FastAPI  /session/{id}/turn                   │
└───────────────────────┬─────────────────────────────────────────┘
                        │ ainvoke(AgentState)
┌───────────────────────▼─────────────────────────────────────────┐
│                   LangGraph StateGraph                          │
│                                                                 │
│  classify_intent                                                │
│       │                                                         │
│       ├─ diagnostic  ──► generate_audio ──► END                 │
│       ├─ learn       ──► vocab_teacher ──► generate_audio       │
│       │                       └──► update_mastery ──► END       │
│       ├─ quiz        ──► transcribe_audio ──► quiz_evaluator     │
│       │                       └──► generate_audio ──► END       │
│       └─ reading     ──► reading_coach ──► generate_audio ──► END│
└───────────────────────┬─────────────────────────────────────────┘
                        │ tool calls
┌───────────────────────▼─────────────────────────────────────────┐
│                  MCP Server  (FastMCP)                          │
│                                                                 │
│  synthesize_pronunciation   → Sarvam TTS  bulbul:v1             │
│  transcribe_speech          → Sarvam STT  saarika:v2            │
│  translate_to_hindi         → Sarvam Translate mayura:v1        │
│  get_word_data              → Free Dictionary API + ChromaDB    │
│  evaluate_word_usage        → OpenRouter LLM (structured JSON)  │
│  get_reading_passage        → ChromaDB RAG retrieval            │
└─────┬───────────────────────────────────────────────────────────┘
      │
 ┌────▼──────────────┐  ┌──────────────────┐  ┌──────────────────┐
 │   ChromaDB         │  │   PostgreSQL      │  │     Redis        │
 │                    │  │                   │  │                  │
 │  gre_words         │  │  user_word_mastery│  │  Session state   │
 │  gre_passages      │  │  study_sessions   │  │  Word cache      │
 │  (semantic search) │  │  (spaced rep)     │  │  Streak          │
 └────────────────────┘  └──────────────────┘  │  Rate limiting   │
                                                └──────────────────┘
```

---

## Key Design Decisions

### Why LangGraph instead of a simple function chain?

Each learning mode (diagnostic / learn / quiz / reading) follows a different node sequence. Routing logic is kept declarative in `agent/graph.py` as conditional edges rather than scattered `if/else` through the codebase. Adding a new mode (e.g., "essay feedback") means adding a node and a routing branch — nothing else changes.

### Why an MCP server for Sarvam API calls?

The MCP server gives each Sarvam tool:
- A typed Pydantic input schema (safe to expose to an LLM as a tool)
- Retry logic and structured error responses at one layer
- Observability hooks that log latency and cost per call

This means the agent doesn't contain any raw HTTP calls; it only calls typed tools.

### Why ChromaDB for words?

The quiz evaluator needs to surface words at the right difficulty level that the user hasn't mastered yet. SQL filtering on a flat table doesn't let you do semantic clustering (e.g., "words semantically similar to `ameliorate`"). ChromaDB handles both: metadata filters for difficulty/mastery + cosine similarity for semantic neighbors.

### Why Redis for session state?

LangGraph `ainvoke` is stateless — each turn reconstructs state from scratch. Redis provides a fast TTL-backed store for per-session working context (current word, current passage, message history) and a word definition cache so we don't re-hit the dictionary API for the same word in multiple sessions.

### Spaced repetition design

| Mastery level | Meaning          | Next review in |
|:-------------:|------------------|:--------------:|
| 0             | Never seen       | Same day       |
| 1             | Seen, not known  | 1 day          |
| 2             | Partially known  | 3 days         |
| 3             | Know it well     | 7 days         |
| 4             | Mastered         | 14 days        |

Mastery moves up on a correct quiz answer, down on wrong. Words at level 4 are excluded from retrieval until their `next_review` date is reached.

### Observability

Every LLM call and Sarvam API call emits a JSON log line with:
```json
{
  "ts": "2024-12-01T10:23:45Z",
  "request_id": "abc-123",
  "user_id": "user_456",
  "event": "llm_call",
  "model": "openai/gpt-4o-mini",
  "prompt_tokens": 412,
  "completion_tokens": 89,
  "cost_usd": 0.000116,
  "latency_ms": 340,
  "success": true
}
```

---

## Evals

Three eval suites in `backend/evals/run_evals.py`:

1. **Word difficulty** — verifies ChromaDB metadata matches expected difficulty ranges for 10 sampled words
2. **Usage evaluation** — 10 (word, sentence, expected_correct) pairs, checks LLM evaluator accuracy
3. **Spaced repetition** — simulates a user with 500 mastered words, verifies none appear in quiz retrieval

Run: `python backend/evals/run_evals.py`

---

## Setup

### Prerequisites
- Python 3.11+, Node 20+
- [Sarvam AI API key](https://dashboard.sarvam.ai)
- [OpenRouter API key](https://openrouter.ai) (for LLM evaluation)

### Local dev (Docker)

```bash
cp backend/.env.example .env
# fill in SARVAM_API_KEY and OPENROUTER_API_KEY

docker compose up

# Ingest GRE word list (first run only)
curl -X POST http://localhost:8000/admin/ingest
```

### Local dev (without Docker)

```bash
# Backend
cd backend
pip install -r requirements.txt
cp .env.example .env  # fill in keys
uvicorn api.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000/dashboard](http://localhost:3000/dashboard)

---

## Project structure

```
lexis/
├── backend/
│   ├── agent/
│   │   ├── state.py           # AgentState TypedDict
│   │   ├── graph.py           # LangGraph StateGraph + routing
│   │   └── nodes/
│   │       ├── classify.py    # Intent classification
│   │       ├── vocab_teacher.py
│   │       ├── quiz_evaluator.py
│   │       ├── audio.py       # STT + TTS nodes
│   │       ├── mastery.py     # Post-learn mastery update
│   │       ├── diagnostic.py  # First-session calibration
│   │       └── reading_coach.py
│   ├── mcp/
│   │   └── server.py          # FastMCP server (Sarvam + RAG tools)
│   ├── rag/
│   │   ├── retriever.py       # ChromaDB client + ingestion
│   │   └── data/
│   │       └── gre_words.json # 50 seed words (expandable to 3500)
│   ├── memory/
│   │   ├── longterm.py        # PostgreSQL mastery store
│   │   └── working.py         # Redis session + cache
│   ├── evals/
│   │   └── run_evals.py       # Three eval suites
│   ├── observability/
│   │   └── logger.py          # Structured JSON logging + LLM cost tracking
│   ├── api/
│   │   └── main.py            # FastAPI entrypoint
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── src/app/
│       ├── dashboard/page.tsx
│       ├── learn/page.tsx     # Voice + text chat interface
│       └── quiz/page.tsx      # Sentence-use quiz
├── docker-compose.yml
└── README.md
```

---

## Extending to 3500 GRE words

The seed file has 50 words. To ingest the full GRE corpus:

1. Replace `rag/data/gre_words.json` with a complete word list (same schema)
2. `POST /admin/ingest` — ChromaDB ingestion runs in ~2 minutes for 3500 words
3. Passages can be added to `gre_passages` collection with the same ingestion path

The spaced repetition system and retrieval logic require no changes — they filter by `mastery_level` and `difficulty` metadata automatically.
