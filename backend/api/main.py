"""
Lexis FastAPI backend.

Endpoints:
    POST /session/start          create session, return session_id
    POST /session/{id}/turn      send user input, get agent response
    GET  /user/{id}/dashboard    study stats + words due today
    GET  /user/{id}/mastery      full mastery map
    POST /ingest/words           (admin) ingest word list into ChromaDB
"""

import os
import uuid
import time
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

load_dotenv(override=True)

from agent.graph import graph
from agent.state import AgentState
from memory.working import init_session, get_session, update_session, get_messages, set_messages
from memory.longterm import (
    get_study_stats, get_words_due_today, get_all_mastery, init_db,
    next_item_for, get_item, record_attempt,
)
from memory.migrate import run_migrations
from observability.logger import set_request_context, log, log_agent_run, get_session_cost
from rag.retriever import ingest_word_list, ingest_passage_list
from content.ingest import ingest_items
from content.grading import score_item, tag_errors
from content.generator import generate_batch
from memory.learner_model import update_ability, get_weak_skills, curate_profile
from memory.users import create_user, authenticate, get_exam_date, set_exam_date
from agent.planner import plan_next

app = FastAPI(title="Lexis", description="GRE vocabulary agent powered by Sarvam AI")

# Comma-separated allowed origins; defaults to local dev. Set CORS_ALLOW_ORIGINS
# in the environment for other deployments.
_cors_origins = [
    o.strip() for o in os.environ.get("CORS_ALLOW_ORIGINS", "http://localhost:3000").split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    # Prefer Alembic; fall back to in-code DDL where the toolchain isn't present.
    if not run_migrations():
        init_db()


# ── Schemas ────────────────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    username: str
    password: str


class ExamDateRequest(BaseModel):
    exam_date: Optional[str] = None   # "YYYY-MM-DD", or null to clear


class StartSessionRequest(BaseModel):
    user_id: str
    mode: str = "learn"       # learn | quiz | reading | diagnostic


class TurnRequest(BaseModel):
    user_id: str
    user_text: Optional[str] = None
    user_audio_b64: Optional[str] = None   # base64 WAV from frontend


class TurnResponse(BaseModel):
    session_id: str
    agent_text: str
    agent_audio_b64: Optional[str]
    hindi_translation: Optional[str]
    current_word: Optional[str]
    is_correct: Optional[bool]
    feedback: Optional[str]
    mastery_updates: list


class NextItemRequest(BaseModel):
    user_id: str
    item_type: str = "TC"       # TC | SE | RC


class CoachRequest(BaseModel):
    user_id: str


class AnswerRequest(BaseModel):
    user_id: str
    item_id: str
    user_answer: list[str]      # selected option per blank (two for SE)


class GenerateRequest(BaseModel):
    item_type: str = "TC"       # TC | SE | RC
    n: int = 5
    difficulty: int = 3


# ── Routes ─────────────────────────────────────────────────────────────────

@app.post("/auth/signup")
def signup(req: AuthRequest):
    """Create a tester account. user_id == normalized username; progress keys off it."""
    if len(req.username.strip()) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters.")
    if len(req.password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")
    user = create_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=409, detail="That username is already taken.")
    return user


@app.post("/auth/login")
def login(req: AuthRequest):
    """Authenticate an existing account; returns {user_id, username}."""
    user = authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return user


@app.post("/session/start")
def start_session(req: StartSessionRequest):
    session_id = str(uuid.uuid4())
    set_request_context(user_id=req.user_id)
    init_session(session_id, req.user_id, req.mode)
    return {"session_id": session_id, "mode": req.mode}


@app.post("/session/{session_id}/turn", response_model=TurnResponse)
async def run_turn(session_id: str, req: TurnRequest):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    set_request_context(user_id=req.user_id)
    start = time.time()

    # Build initial state for this turn
    state: AgentState = {
        "user_id": req.user_id,
        "session_id": session_id,
        "mode": session.get("mode", "learn"),
        "current_word": session.get("current_word"),
        "current_passage": session.get("current_passage"),
        "current_question": session.get("current_question"),
        "user_text": req.user_text,
        "user_audio_b64": req.user_audio_b64,
        "agent_text": "",
        "agent_audio_b64": None,
        "hindi_translation": None,
        "is_correct": None,
        "feedback": None,
        "mastery_delta": 0,
        "mastery_updates": [],
        "messages": get_messages(session_id),
    }

    try:
        # Run the LangGraph agent
        result = await graph.ainvoke(state)

        latency_ms = int((time.time() - start) * 1000)
        log_agent_run(
            mode=result["mode"],
            word=result.get("current_word"),
            total_latency_ms=latency_ms,
            nodes_executed=[],    # populated inside nodes
            success=True
        )
    except Exception as exc:
        latency_ms = int((time.time() - start) * 1000)
        log("agent_run_error", mode=state["mode"], error=str(exc), total_latency_ms=latency_ms)
        result = {
            **state,
            "agent_text": "I hit a local development error while processing that turn. Check the backend logs for details.",
            "agent_audio_b64": None,
            "mastery_updates": [],
        }

    # Persist session updates + conversation history (history is no longer dropped)
    update_session(session_id, {
        "current_word": result.get("current_word"),
        "current_passage": result.get("current_passage"),
        "current_question": result.get("current_question"),
    })
    set_messages(session_id, result.get("messages", []))
    log("turn_cost", session_id=session_id, cost_usd=get_session_cost(session_id))

    return TurnResponse(
        session_id=session_id,
        agent_text=result["agent_text"],
        agent_audio_b64=result.get("agent_audio_b64"),
        hindi_translation=result.get("hindi_translation"),
        current_word=result.get("current_word"),
        is_correct=result.get("is_correct"),
        feedback=result.get("feedback"),
        mastery_updates=result.get("mastery_updates", []),
    )


@app.get("/user/{user_id}/dashboard")
def get_dashboard(user_id: str):
    stats = get_study_stats(user_id)
    due_words = get_words_due_today(user_id)
    return {
        "user_id": user_id,
        "stats": stats,
        "due_today": due_words[:20],
        "due_count": len(due_words),
        "exam_date": get_exam_date(user_id),
    }


@app.put("/user/{user_id}/exam-date")
def put_exam_date(user_id: str, req: ExamDateRequest):
    """Set or clear the user's GRE exam date (drives the dashboard countdown)."""
    d = (req.exam_date or "").strip() or None
    if d is not None:
        try:
            datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="exam_date must be YYYY-MM-DD")
    return {"exam_date": set_exam_date(user_id, d)}


@app.get("/user/{user_id}/mastery")
def get_mastery_map(user_id: str):
    return {"user_id": user_id, "mastery": get_all_mastery(user_id)}


@app.get("/user/{user_id}/profile")
def get_learner_profile(user_id: str):
    """The learner model: ability per skill, weak areas, recent error patterns."""
    return {"user_id": user_id, **get_weak_skills(user_id)}


# ── Practice items (Phase 1) ─────────────────────────────────────────────────

@app.post("/coach/next")
async def coach_next(req: CoachRequest):
    """Planner agent: inspects the learner profile and DECIDES the next item to serve."""
    set_request_context(user_id=req.user_id)
    return await plan_next(req.user_id)


@app.post("/coach/diagnose")
async def coach_diagnose(req: CoachRequest):
    """End-of-session: synthesize recent attempts into curated notes + confusion pairs."""
    set_request_context(user_id=req.user_id)
    return await curate_profile(req.user_id)


@app.post("/items/next")
def items_next(req: NextItemRequest):
    """Serve the next item of the requested type, with the answer stripped out."""
    item = next_item_for(req.user_id, req.item_type)
    if not item:
        return {"item": None, "message": "You've cleared every item at this level — nice work!"}
    safe = {k: item[k] for k in ("id", "type", "stem", "options", "target_words", "difficulty")}
    return {"item": safe}


@app.post("/items/answer")
async def items_answer(req: AnswerRequest):
    """Score an answer deterministically; tag errors (LLM) only when wrong."""
    item = get_item(req.item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    set_request_context(user_id=req.user_id)
    start = time.time()
    is_correct = score_item(item, req.user_answer)

    error_tags: list = []
    explanation = item.get("explanation", "")
    if not is_correct:
        tagged = await tag_errors(item, req.user_answer)
        error_tags = tagged["error_tags"]
        explanation = tagged["explanation"]

    latency_ms = int((time.time() - start) * 1000)
    record_attempt(
        req.user_id,
        item["type"],
        item_id=item["id"],
        word=(item.get("target_words") or [None])[0],
        user_answer=req.user_answer,
        is_correct=is_correct,
        error_tags=error_tags,
        latency_ms=latency_ms,
    )
    new_rating = update_ability(req.user_id, item["type"], item.get("difficulty", 3), is_correct)
    log("item_answered", item_id=item["id"], type=item["type"],
        is_correct=is_correct, error_tags=error_tags, rating=new_rating)

    return {
        "is_correct": is_correct,
        "correct_answer": item["answer"],
        "explanation": explanation,
        "error_tags": error_tags,
    }


@app.post("/admin/generate")
async def admin_generate(req: GenerateRequest):
    """Generate -> validate -> critique -> store a batch of items of one type."""
    if req.item_type not in ("TC", "SE", "RC"):
        raise HTTPException(status_code=400, detail="item_type must be TC, SE, or RC")
    return await generate_batch(req.item_type, max(1, min(req.n, 25)), req.difficulty)


@app.post("/admin/ingest")
def ingest_all(
    words_path: str = "rag/data/gre_words.json",
    passages_path: str = "rag/data/gre_passages.json",
):
    ingest_word_list(words_path)
    ingest_passage_list(passages_path)
    items_result = ingest_items()
    return {
        "status": "ok",
        "words_path": words_path,
        "passages_path": passages_path,
        "items": items_result,
    }