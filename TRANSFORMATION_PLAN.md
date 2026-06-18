# Lexis — Agentic Transformation Plan

Turning the v1 deterministic workflow into a genuinely agentic, exam-relevant GRE
Verbal coach. This doc is the source of truth: deep design per phase + the task list.

## Guiding principles
- **Agentic where the decision is open** (what to study, why an answer was wrong,
  how to adapt, what to generate). **Deterministic where it's solved** (SRS intervals,
  scoring math, ability-estimate updates, adaptive item selection math).
- **Agent plans + re-plans on surprise; deterministic executors run routine steps.**
  Do not run a full agent loop on every turn (latency/cost).
- **Build the agent on real data.** Phase 1 (real item types) produces the `attempts`
  signal the agent needs. Ship it before the agent.
- **Nothing generated reaches a user un-validated.** High-stakes exam = critic gate.

## Forks (decided)
| Decision | Choice |
|---|---|
| Tool layer | One typed registry → LangChain tools (model-selected) + MCP export. Stop importing tool fns directly. |
| Transport | SSE streaming (needed once an agent loop exists). |
| Content | Generate + critic-validate + cache into item bank. |
| Migrations | Alembic. |

---

# PHASE 0 — Foundations (no user-facing change)

### 0.1 LLM router — `backend/llm/router.py` (new)
Centralize the `ChatOpenAI` construction duplicated across vocab_teacher / diagnostic /
reading_coach. Route model by task; structured-output helper with retry; cost logging.

```python
class Task(str, Enum):
    ROUTE; EVALUATE; PARSE; PLAN; GENERATE; DIAGNOSE; VALIDATE

MODEL_BY_TASK = {
    Task.ROUTE: "openai/gpt-4o-mini", Task.EVALUATE: "openai/gpt-4o-mini",
    Task.PARSE: "openai/gpt-4o-mini", Task.VALIDATE: "openai/gpt-4o-mini",
    Task.PLAN: "openai/gpt-4o", Task.GENERATE: "openai/gpt-4o", Task.DIAGNOSE: "openai/gpt-4o",
}
def get_llm(task: Task, **overrides) -> ChatOpenAI: ...
async def acomplete_json(task, system, user, schema: type[BaseModel]) -> BaseModel:
    """Structured output with 1 retry on parse failure; logs tokens+cost."""
```

### 0.2 Tool registry — `backend/tools/registry.py` (new)
Single typed definition per tool; export as LangChain tools AND MCP. Migrate the speech
tools out of `mcp/server.py` into `tools/speech.py`.

```python
@dataclass
class ToolSpec: name: str; fn: Callable; args_schema: type[BaseModel]; description: str
REGISTRY: dict[str, ToolSpec] = {}
def tool(args_schema): ...                       # decorator → registers
def as_langchain_tools(names: list[str]) -> list[StructuredTool]
def as_mcp_server() -> FastMCP
```

### 0.3 Memory persistence fix — `api/main.py`, `memory/working.py`
v1 bug: `run_turn` writes `"messages": []` every turn, discarding history (breaks
multi-turn diagnostic/reading). Persist messages + plan in Redis.
```python
# working.py
def append_messages(session_id, msgs); def get_messages(session_id) -> list
def set_plan(session_id, plan); def get_plan(session_id) -> dict
```

### 0.4 Alembic — `backend/migrations/`
Init alembic; migration 0001 = current `user_word_mastery` + `study_sessions`
(move DDL out of `init_db`). `alembic upgrade head` on startup.

### 0.5 Delete dead code
`agent/nodes/classify.py` (no-op), `_needs_transcription` flag, static `route_by_mode`.

### 0.6 Observability — `observability/logger.py`
`log_tool_call(tool, latency, ok)`, `log_plan_decision(action, reason)`,
per-session cost rollup keyed by `session_id`.

**Acceptance:** behavior unchanged; messages persist across turns; one place builds LLMs;
`alembic upgrade head` builds schema; dead code gone.

---

# PHASE 1 — Real exam item types (highest ROI)

v1 only trains "use the word in a sentence." The GRE Verbal section is Text Completion (TC),
Sentence Equivalence (SE), and Reading Comprehension (RC). Add them.

### 1.1 Schema — migration 0002 (`memory/longterm.py`)
```sql
items(
  id TEXT PK, type TEXT,                 -- vocab|TC|SE|RC
  target_words TEXT[], stem TEXT, options JSONB, answer JSONB,
  explanation TEXT, difficulty INT, status TEXT,  -- pending|approved|retired
  source TEXT, validated_by TEXT, created_at TIMESTAMPTZ DEFAULT NOW()
);
attempts(
  id BIGSERIAL PK, user_id TEXT, item_id TEXT NULL, word TEXT NULL,
  item_type TEXT, user_answer JSONB, is_correct BOOL,
  error_tags TEXT[], latency_ms INT, ts TIMESTAMPTZ DEFAULT NOW()
);
```
New fns: `insert_item`, `get_item`, `next_item_for(user_id, type, difficulty)`,
`record_attempt(...)`, `get_recent_attempts(user_id, n)`.

### 1.2 Error taxonomy — `backend/eval/taxonomy.py` (new)
```python
class ErrorTag(str, Enum):
    UNKNOWN_WORD; WRONG_CONNOTATION; MISSED_CONTRAST; MISSED_CONCESSION
    MISSED_CAUSE; MISREAD_SCOPE; WRONG_REGISTER; GRAMMAR; CARELESS; NONE
```

### 1.3 Item models — `backend/content/models.py` (new, pydantic)
```python
class TCBlank(BaseModel): options: conlist(str, min_length=3, max_length=5); answer: str
class TextCompletion(BaseModel):
    stem: str; blanks: conlist(TCBlank, min_length=1, max_length=3)
    explanation: str; target_words: list[str]; difficulty: int
class SentenceEquivalence(BaseModel):
    stem: str; options: conlist(str, min_length=6, max_length=6)
    answers: conlist(str, min_length=2, max_length=2); explanation: str; difficulty: int
class ReadingItem(BaseModel):
    passage_id: str; question: str; options: list[str]; answer: str; explanation: str
```

### 1.4 Evaluation — `agent/nodes/evaluate.py` (rewrite of quiz_evaluator)
- MC items: **deterministic** correctness (compare keyed answer). No LLM for right/wrong.
- Wrong answers: one LLM call (EVALUATE model) → `error_tags` + ≤2-sentence explanation.
- Writes `record_attempt(...)`; vocab still updates SRS via existing `update_mastery`.

Error-tag prompt:
```
You are a GRE Verbal item analyst. Given an item, the correct answer, and the student's
wrong answer, identify WHY they erred. Return JSON:
{ "error_tags": [<subset of the fixed list>], "explanation": "<=2 sentences" }
Fixed list: unknown_word, wrong_connotation, missed_contrast, missed_concession,
missed_cause, misread_scope, wrong_register, grammar, careless. Prefer the single
most explanatory tag.
```

### 1.5 Seed item bank — `backend/content/data/items_seed.json`
Hand-author ~30 TC + ~30 SE + a few RC (real generation lands in Phase 3). Ingest path.

### 1.6 Frontend — `frontend/src/app/`
Polymorphic renderer; dispatch on `item.type`.
- `components/ItemRenderer.tsx` → `TCItem` (inline dropdown per blank), `SEItem`
  (6 checkboxes, enforce exactly 2), `RCItem` (passage + radio).
- `quiz/page.tsx` becomes a session runner: GET `/items/next`, POST `/items/{id}/answer`.
- New API routes in `api/main.py`: `GET /session/{id}/next`, `POST /session/{id}/answer`.

**Acceptance:** user completes a TC and an SE item end-to-end; wrong answers tagged;
`attempts` populated; all three item types render.

---

# PHASE 2 — The agent (genuine agency)

### 2.1 State — `agent/state.py` (rewrite)
```python
class AgentState(TypedDict):
    user_id: str; session_id: str
    messages: Annotated[list, add_messages]   # real reducer, not discarded
    profile: dict                              # learner_profile snapshot
    plan: dict                                 # session lesson plan
    current_item: Optional[dict]
    last_attempt: Optional[dict]               # answer + error_tags
    step_count: int                            # loop guard
    agent_text: str; agent_audio_b64: Optional[str]; feedback: Optional[str]
```

### 2.2 Tools — `backend/tools/tutoring.py`, `content.py`
Args-schema'd, model-selected:
`get_due_items`, `get_weak_skills`, `generate_item`, `pull_passage`, `serve_item`,
`explain`, `give_hint`, `reteach`, `adjust_difficulty`, `update_learner_model`,
`schedule_review`.

### 2.3 Planner loop — `agent/planner.py` (new — the real agent)
```python
def build_planner():
    g = StateGraph(AgentState)
    g.add_node("plan", plan_node)          # get_llm(Task.PLAN).bind_tools(tools)
    g.add_node("tools", ToolNode(tools))
    g.set_entry_point("plan")
    g.add_conditional_edges("plan", should_continue, {"tools": "tools", "end": END})
    g.add_edge("tools", "plan")
    return g.compile()

def should_continue(s):
    last = s["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) and s["step_count"] < 6 else "end"
```
Planner system prompt:
```
You are Lexis, an adaptive GRE Verbal coach running one study session.
Decide what the student does next to maximize score gain in their limited time.
You are given: learner profile (ability per skill, confusion pairs, notes), time budget,
exam date, current lesson plan, and the latest attempt.
Each turn choose the SINGLE best next action via tools:
- If an attempt just failed, diagnose why (use error tags), then decide: re-teach the
  word, give a hint and retry, drop difficulty, or move on.
- Prioritise the weakest skill and overdue spaced-repetition words. Don't drill mastered
  items. Vary item type. Keep momentum.
Call update_learner_model when you learn something durable about the student.
End your turn by serving exactly one item or one short coaching message. Be concise
(~15-minute session).
```

### 2.4 Hybrid graph — `agent/graph.py` (rewrite)
```
session_start → plan_session (planner, agentic)         # sets lesson plan once
turn → execute_step (deterministic: serve next planned item)
     → evaluate (error tags)
     → interpret (LLM: why wrong; profile signal)
     → router: { on_track → execute_step,
                 struggling|surprise|tangent → planner (re-plan),
                 done → END }
```

### 2.5 Learner model — `memory/learner_model.py` (new)
- **Deterministic:** `update_ability(user_id, skill, item_difficulty, correct)` —
  Elo: `R' = R + K*(S - E)`, `E = 1/(1+10^((D-R)/400))`.
- **LLM-curated:** `curate_profile(user_id)` — end-of-session DIAGNOSE pass over recent
  `attempts` → `confusion_pairs` + `notes`. Not per-turn (cost).

### 2.6 Adaptive diagnostic — `diagnostic/adaptive.py` (replaces self-report)
```python
def select_next(estimate: float, asked: set[str]) -> Item   # max-information near estimate
def update_estimate(estimate: float, item_difficulty: int, correct: bool) -> float
```
~8–12 items; LLM only for item gen + interpreting spoken answers; seeds
`learner_profile.ability`.

**Acceptance:** session driven by planner; a wrong answer can trigger re-teach/hint vs.
fixed flow; ability estimates update; profile notes populated.

---

# PHASE 3 — Generative validated content
- `content/generators.py`: `generate_tc/se/rc(target_words, difficulty)` (GENERATE model,
  structured output).
- `content/validator.py`: `validate_item(item) -> {ok, reasons}` — exactly-one-best-answer,
  plausible distractors, target word used correctly (VALIDATE model + rule checks).
- `content/ingest.py`: approved → `items` table + Chroma `items` collection.
- `content/worker.py`: background buffer of N validated items per (type, difficulty, weak cluster).

# PHASE 4 — Voice + latency
- SSE endpoint `GET /session/{id}/stream`; stream tokens + audio chunks.
- Parallelize independent tool calls in the planner.
- Pronunciation feedback tool (STT user word → compare).
- Keep routine turns off the full loop.

# PHASE 5 — Eval flywheel & trust
- `evals/`: golden expert-keyed item set; evaluator-agreement eval; item-validation eval;
  calibration (predicted mastery vs. 7-day recall).
- CI gate on evals for any prompt/model change.
- Cost/latency dashboards from logger.

---

# TASK LIST

Legend: `[ ]` todo · deps in parens · each task lists its acceptance check.

## Phase 0 — Foundations ✅ DONE (2026-06-15)
- [x] **P0-1** `llm/router.py`: Task enum, MODEL_BY_TASK, `get_llm`, `acomplete_json` (retry+cost). _Verified: imports + LLM construction OK._
- [x] **P0-2** Refactored vocab_teacher/diagnostic/reading_coach to `get_llm(Task.*)`. _Verified: only the router constructs `ChatOpenAI`._
- [x] **P0-3** `tools/` package (`config`, `speech`, `lexical`, `registry`, `mcp_app`); removed local `backend/mcp/` (it shadowed the PyPI `mcp`). _Verified: `as_langchain_tools()` returns all 6 tools._
- [x] **P0-4** Fixed `messages: []` discard; `working.py` `get/set_messages` (+ `get/set_plan`). _Verified: round-trip preserves `additional_kwargs` (diagnostic multi-turn now works)._
- [x] **P0-5** Alembic + migration `0001` (existing tables); `run_migrations()` at startup, falls back to `init_db()`. _Authored; runtime needs `pip install` (alembic/sqlalchemy not in local venv)._
- [x] **P0-6** Deleted `nodes/classify.py` + `_needs_transcription`; routing now via `set_conditional_entry_point`. _Verified: graph compiles without the node._
- [x] **P0-7** `log_tool_call`, `log_plan_decision`, per-session cost (`add/get/reset_session_cost`); `log_llm_call` takes `session_id`. _Verified: wired into tools + router + turn._

### Phase 0 deviations from the original plan (intentional)
- **Kept `route_by_mode`** rather than deleting it — the planner that replaces it doesn't
  exist until Phase 2. P0-6 instead removed only the dead `classify` no-op node and made
  routing a conditional entry point. (Behavior preserved.)
- **Removed the whole `backend/mcp/` package** (not just moved files). It shadowed the real
  PyPI `mcp`, so the MCP server never actually ran (silent no-op fallback). Bumped
  `mcp>=1.2.0` so FastMCP is real on rebuild; `as_mcp_server()` raises a clear error otherwise.
- **Fixed a latent bug** in `get_reading_passage`: it passed a string difficulty into
  `retrieve_passage` (which expects int 1–5 for `$lte`); now mapped easy/medium/hard → 2/3/5.
- Added `alembic==1.13.2` to requirements.

## Phase 1 — Real item types
- [ ] **P1-1** Migration 0002: `items` + `attempts` tables; longterm.py CRUD. (P0-5) _AC: insert/read item + attempt._
- [ ] **P1-2** `eval/taxonomy.py`: ErrorTag enum. _AC: importable closed set._
- [ ] **P1-3** `content/models.py`: TC/SE/RC pydantic models w/ constraints. _AC: SE enforces 6 options / 2 answers._
- [ ] **P1-4** `agent/nodes/evaluate.py`: deterministic MC scoring + LLM error-tagging; `record_attempt`. (P1-1,P1-2,P0-1) _AC: wrong TC answer yields tags + row._
- [ ] **P1-5** `content/data/items_seed.json` (~30 TC, ~30 SE, few RC) + ingest. (P1-1,P1-3) _AC: items queryable by type/difficulty._
- [ ] **P1-6** API: `GET /session/{id}/next`, `POST /session/{id}/answer`. (P1-4,P1-5) _AC: serve item, post answer, get result._
- [ ] **P1-7** Frontend `ItemRenderer` + TC/SE/RC components. (P1-6) _AC: all three render & submit._
- [ ] **P1-8** Frontend: `quiz/page.tsx` → session runner using new routes. (P1-7) _AC: full TC+SE session works._

## Phase 2 — The agent
- [ ] **P2-1** `agent/state.py`: loop-capable state (messages reducer, plan, profile, step_count). _AC: graph compiles with new state._
- [ ] **P2-2** `memory/learner_model.py`: `learner_profile` table (migration 0003) + Elo `update_ability`. (P1-1) _AC: ability moves on attempt._
- [ ] **P2-3** `tools/tutoring.py` + `tools/content.py`: planner tool set w/ schemas. (P0-3,P1-*) _AC: tools registered + bindable._
- [ ] **P2-4** `agent/planner.py`: tool-calling loop + system prompt + step guard. (P2-1,P2-3) _AC: loop selects tools, halts at cap._
- [ ] **P2-5** `agent/graph.py`: hybrid plan→execute→evaluate→interpret→{continue|replan|done}. (P2-4) _AC: wrong answer triggers re-teach path._
- [ ] **P2-6** `agent/nodes/interpret.py`: LLM diagnosis writing profile signals. (P2-2) _AC: error pattern → profile note._
- [ ] **P2-7** `memory/learner_model.curate_profile`: end-of-session DIAGNOSE pass. (P2-2) _AC: confusion_pairs populated._
- [ ] **P2-8** `diagnostic/adaptive.py`: adaptive selection + estimate update; replace self-report node + UI. (P2-2) _AC: diagnostic sets ability in ~10 items._

## Phase 3 — Generative content
- [ ] **P3-1** `content/generators.py`: TC/SE/RC generation (structured output). (P0-1,P1-3)
- [ ] **P3-2** `content/validator.py`: critic gate (one-best-answer, distractors, target word). (P3-1)
- [ ] **P3-3** `content/ingest.py`: approved → items table + Chroma `items` collection. (P3-2)
- [ ] **P3-4** `content/worker.py`: background buffer per (type, difficulty, cluster). (P3-3)

## Phase 4 — Voice + latency
- [ ] **P4-1** SSE `GET /session/{id}/stream`; token + audio streaming. (P2-5)
- [ ] **P4-2** Frontend: consume SSE in learn/quiz. (P4-1)
- [ ] **P4-3** Parallelize independent planner tool calls. (P2-4)
- [ ] **P4-4** Pronunciation feedback tool. (P0-3)

## Phase 5 — Flywheel
- [ ] **P5-1** Golden item set + evaluator-agreement eval. (P1-4)
- [ ] **P5-2** Item-validation eval. (P3-2)
- [ ] **P5-3** Calibration tracking (mastery vs 7-day recall). (P2-2)
- [ ] **P5-4** CI gate on evals; cost/latency dashboard. (P0-7)

## Cross-cutting (do alongside)
- [ ] **X-1** Replace `demo_user` with real auth (frontend + API). 
- [ ] **X-2** Background task runner (RQ/async) for P2-7 + P3-4.
- [ ] **X-3** Update README + architecture diagram to match reality (remove "agentic" overclaim until P2 lands).
