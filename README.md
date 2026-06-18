# Lexis — GRE Vocabulary Agent

A voice-first GRE vocabulary tutor powered by Sarvam AI's speech APIs, LangGraph agent orchestration, and spaced repetition.

Someone with 30–60 days before their GRE exam who knows English but needs to close the gap to a 160+ Verbal score. They practice 15 minutes a day — on the commute, in bed, between meetings — by speaking, not typing.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Next.js Frontend                         │
│   Login · Dashboard · Learn (voice) · Quiz · Practice · Coach   │
│   Reading Comprehension · Exam Countdown                        │
└───────────────────────┬─────────────────────────────────────────┘
                        │ REST (JSON + base64 audio)
┌───────────────────────▼─────────────────────────────────────────┐
│                    FastAPI  Backend                              │
│                                                                 │
│   /auth/signup, /auth/login                                     │
│   /session/start, /session/{id}/turn                            │
│   /items/next, /items/answer                                    │
│   /coach/next, /coach/diagnose                                  │
│   /user/{id}/dashboard, /user/{id}/mastery, /user/{id}/profile  │
│   /admin/ingest, /admin/generate                                │
└───────────────────────┬─────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│                   LangGraph StateGraph                          │
│                                                                 │
│  route_by_mode (conditional entry)                              │
│       ├─ diagnostic  ──► generate_audio ──► END                 │
│       ├─ learn       ──► vocab_teacher ──► generate_audio       │
│       │                       └──► update_mastery ──► END       │
│       ├─ quiz        ──► transcribe_audio ──► quiz_evaluator    │
│       │                       └──► generate_audio ──► END       │
│       └─ reading     ──► reading_coach ──► generate_audio ──► END│
└───────────────────────┬─────────────────────────────────────────┘
                        │ tool calls
┌───────────────────────▼─────────────────────────────────────────┐
│                  Tool Registry  (LangChain + MCP)               │
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
 │  gre_passages      │  │  items + attempts │  │  Message history │
 │  (semantic search) │  │  learner_profile  │  │  Word cache      │
 │                    │  │  users            │  │  Streak          │
 └────────────────────┘  └──────────────────┘  └──────────────────┘
```

---

## Features

### Learning Modes
- **Learn** — Voice-first vocabulary teaching with TTS pronunciation, Hindi translations, and contextual examples
- **Quiz** — Spoken sentence-use quizzes with LLM evaluation and spaced repetition
- **Reading** — Reading comprehension with passage retrieval from ChromaDB
- **Diagnostic** — First-session calibration to estimate the learner's starting level
- **Practice** — GRE-format items: Text Completion (TC), Sentence Equivalence (SE), and Reading Comprehension (RC)
- **Coach** — AI-driven planner that inspects the learner profile and decides what to study next

### Practice Item Types (GRE-format)
| Type | Description |
|------|-------------|
| TC (Text Completion) | 1–3 blanks, 3–5 options each, exactly one correct per blank |
| SE (Sentence Equivalence) | 1 blank, 6 options, exactly 2 correct (synonymous) answers |
| RC (Reading Comprehension) | Passage + question, multiple choice, one correct answer |

Items are scored deterministically. Wrong answers trigger LLM-powered error tagging to identify *why* the student erred (unknown word, wrong connotation, missed contrast, etc.).

### Learner Model
- **Elo-based ability tracking** per skill type — updates on every practice attempt
- **Error taxonomy** — tags like `unknown_word`, `wrong_connotation`, `missed_contrast`, `missed_concession`, `missed_cause`, `misread_scope`
- **Weak skill detection** — surfaces skills with lowest ratings for targeted practice
- **End-of-session diagnosis** — LLM curates confusion pairs and notes from recent attempts

### Spaced Repetition

| Mastery level | Meaning          | Next review in |
|:-------------:|------------------|:--------------:|
| 0             | Never seen       | Same day       |
| 1             | Seen, not known  | 1 day          |
| 2             | Partially known  | 3 days         |
| 3             | Know it well     | 7 days         |
| 4             | Mastered         | 14 days        |

### Observability
Every LLM call and tool call emits structured JSON logs with latency, token counts, cost tracking, and per-session cost rollups.

### Content Generation
Admin endpoint to generate + validate + store new TC/SE/RC items via LLM with a critic gate.

---

## Setup

### Prerequisites
- Python 3.11+, Node 20+
- [Sarvam AI API key](https://dashboard.sarvam.ai)
- [OpenRouter API key](https://openrouter.ai) (for LLM evaluation)

### Local dev (Docker)

```bash
cp backend/.env.example backend/.env
# fill in SARVAM_API_KEY and OPENROUTER_API_KEY

docker compose up

# Ingest GRE word list + passages + seed items (first run only)
curl -X POST http://localhost:8000/admin/ingest
```

### Local dev (without Docker)

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env        # fill in keys
uvicorn api.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

---

## Project Structure

```
lexis/
├── backend/
│   ├── agent/
│   │   ├── state.py              # AgentState TypedDict
│   │   ├── graph.py              # LangGraph StateGraph + conditional routing
│   │   ├── planner.py            # AI coach — inspects profile, decides next action
│   │   └── nodes/
│   │       ├── vocab_teacher.py  # Word teaching with context + examples
│   │       ├── quiz_evaluator.py # Spoken answer evaluation
│   │       ├── audio.py          # STT + TTS nodes (Sarvam)
│   │       ├── mastery.py        # Post-learn mastery update
│   │       ├── diagnostic.py     # First-session calibration
│   │       └── reading_coach.py  # Reading comprehension coach
│   ├── llm/
│   │   └── router.py             # Centralized LLM construction by task type
│   ├── tools/
│   │   ├── registry.py           # Typed tool registry → LangChain + MCP export
│   │   ├── speech.py             # Sarvam TTS/STT/translate tools
│   │   ├── lexical.py            # Dictionary + word data tools
│   │   ├── config.py             # Tool configuration
│   │   └── mcp_app.py            # FastMCP server export
│   ├── content/
│   │   ├── models.py             # TC/SE/RC Pydantic item models
│   │   ├── taxonomy.py           # ErrorTag enum for error classification
│   │   ├── grading.py            # Deterministic scoring + LLM error tagging
│   │   ├── generator.py          # LLM item generation + validation
│   │   ├── ingest.py             # Seed item ingestion
│   │   └── data/                 # Seed items (TC, SE, RC JSON)
│   ├── rag/
│   │   ├── retriever.py          # ChromaDB client + ingestion
│   │   └── data/                 # GRE words + passages JSON
│   ├── memory/
│   │   ├── longterm.py           # PostgreSQL: mastery, items, attempts
│   │   ├── working.py            # Redis: session state, message history, cache
│   │   ├── learner_model.py      # Elo ability tracking + profile curation
│   │   ├── users.py              # User auth (signup/login)
│   │   └── migrate.py            # Alembic migration runner
│   ├── migrations/               # Alembic migrations (5 versions)
│   ├── evals/
│   │   └── run_evals.py          # Eval suites (word difficulty, usage, SRS)
│   ├── observability/
│   │   └── logger.py             # Structured JSON logging + cost tracking
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx          # Landing page
│   │   │   ├── login/            # Auth (signup + login)
│   │   │   ├── dashboard/        # Study stats + words due + exam countdown
│   │   │   ├── learn/            # Voice + text learning interface
│   │   │   ├── quiz/             # Spoken sentence-use quiz
│   │   │   ├── practice/         # GRE-format items (TC/SE/RC)
│   │   │   └── coach/            # AI-driven study session
│   │   ├── components/
│   │   │   ├── ItemCard.tsx      # Practice item renderer
│   │   │   ├── ExamCountdown.tsx # Countdown to exam date
│   │   │   └── UserBadge.tsx     # User display component
│   │   └── lib/
│   │       ├── api.ts            # Backend API client
│   │       ├── auth.ts           # Auth utilities
│   │       └── types.ts          # TypeScript type definitions
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/signup` | Create account |
| POST | `/auth/login` | Authenticate |
| POST | `/session/start` | Start a learning session (learn/quiz/reading/diagnostic) |
| POST | `/session/{id}/turn` | Send user input, get agent response |
| POST | `/items/next` | Get next practice item (TC/SE/RC) |
| POST | `/items/answer` | Submit answer, get scoring + error tags |
| POST | `/coach/next` | AI planner decides what to study next |
| POST | `/coach/diagnose` | End-of-session profile curation |
| GET | `/user/{id}/dashboard` | Study stats + words due today |
| GET | `/user/{id}/mastery` | Full mastery map |
| GET | `/user/{id}/profile` | Learner model (ability, weak areas) |
| PUT | `/user/{id}/exam-date` | Set GRE exam date |
| POST | `/admin/ingest` | Ingest words, passages, and seed items |
| POST | `/admin/generate` | Generate new practice items via LLM |

---

## Key Design Decisions

**LangGraph for orchestration** — Each learning mode follows a different node sequence. Routing is declarative as conditional edges in `agent/graph.py`. Adding a new mode means adding a node and a routing branch.

**Typed tool registry** — Single definition per tool exports as both LangChain tools (for agent use) and MCP server. No raw HTTP calls in agent code.

**ChromaDB for semantic search** — The quiz evaluator needs words at the right difficulty that the user hasn't mastered. ChromaDB handles metadata filters for difficulty/mastery + cosine similarity for semantic neighbors.

**Redis for session state** — LangGraph `ainvoke` is stateless per turn. Redis provides TTL-backed storage for session context, message history, and word definition caching.

**Deterministic scoring, LLM error analysis** — Practice items are scored by comparing answers directly (no LLM needed for right/wrong). LLM is only invoked to analyze *why* a wrong answer was chosen.

**Centralized LLM router** — All LLM construction goes through `llm/router.py` with task-based model selection (cheaper models for routing/evaluation, capable models for generation/diagnosis).

**Alembic migrations** — Schema changes tracked in versioned migrations, auto-applied on startup.
