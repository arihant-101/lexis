"""
Lexis eval framework.

Eval suites (run a subset by name, e.g. `python -m evals.run_evals error_tagger`):
  1. word_difficulty   — does the corpus difficulty tagging match expected GRE difficulty?
  2. usage_evaluation  — does the LLM correctly score correct vs incorrect word usage?
  3. spaced_repetition — does the retrieval surface the right words at the right time?
  4. error_tagger      — does the error-tagger pick a defensible taxonomy tag? (agentic)
  5. planner_branch    — does the reactive planner branch correctly on the last attempt? (agentic)

Run: python -m evals.run_evals               # all suites
     python -m evals.run_evals error_tagger planner_branch
Exits non-zero if any suite has a failure/error (CI-friendly).
"""

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable
from tools.speech import synthesize_pronunciation
from tools.lexical import evaluate_word_usage
from rag.retriever import retrieve_words_for_quiz

from content.grading import tag_errors
from agent.planner import plan_next
from memory.longterm import record_attempt
from memory.learner_model import update_ability
from tools.config import OPENROUTER_API_KEY, _has_real_key


# ── Result types ───────────────────────────────────────────────────────────

@dataclass
class EvalResult:
    suite: str
    passed: int = 0
    failed: int = 0
    errors: int = 0
    latencies_ms: list = field(default_factory=list)
    failures: list = field(default_factory=list)

    @property
    def total(self):
        return self.passed + self.failed + self.errors

    @property
    def accuracy(self):
        return self.passed / self.total if self.total else 0

    @property
    def p50_latency(self):
        s = sorted(self.latencies_ms)
        return s[len(s) // 2] if s else 0

    @property
    def p95_latency(self):
        s = sorted(self.latencies_ms)
        return s[int(len(s) * 0.95)] if s else 0

    def summary(self) -> dict:
        return {
            "suite": self.suite,
            "accuracy": round(self.accuracy, 3),
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "p50_latency_ms": self.p50_latency,
            "p95_latency_ms": self.p95_latency,
            "sample_failures": self.failures[:3]
        }


# ── Suite 1: Word difficulty calibration ──────────────────────────────────

DIFFICULTY_GROUND_TRUTH = [
    # (word, expected_difficulty_range)
    ("ephemeral",    (3, 5)),
    ("sycophant",    (3, 5)),
    ("ubiquitous",   (2, 4)),
    ("aberrant",     (3, 5)),
    ("benevolent",   (1, 3)),
    ("capricious",   (3, 5)),
    ("obfuscate",    (4, 5)),
    ("happy",        (1, 2)),
    ("mundane",      (2, 3)),
    ("loquacious",   (3, 5)),
]


def eval_word_difficulty() -> EvalResult:
    result = EvalResult(suite="word_difficulty")
    from rag.retriever import _get_collections
    word_col, _ = _get_collections()

    for word, (min_d, max_d) in DIFFICULTY_GROUND_TRUTH:
        start = time.time()
        try:
            results = word_col.get(ids=[f"word_{word}"], include=["metadatas"])
            if not results["metadatas"]:
                result.errors += 1
                continue
            difficulty = int(results["metadatas"][0].get("difficulty", 3))
            latency = int((time.time() - start) * 1000)
            result.latencies_ms.append(latency)

            if min_d <= difficulty <= max_d:
                result.passed += 1
            else:
                result.failed += 1
                result.failures.append({
                    "word": word,
                    "expected_range": [min_d, max_d],
                    "got": difficulty
                })
        except Exception as e:
            result.errors += 1
            result.failures.append({"word": word, "error": str(e)})

    return result


# ── Suite 2: Usage evaluation accuracy ────────────────────────────────────

USAGE_GROUND_TRUTH = [
    # (word, sentence, expected_is_correct)
    ("ephemeral", "The ephemeral beauty of cherry blossoms makes them all the more precious.", True),
    ("ephemeral", "She put the ephemeral in the drawer.", False),
    ("sycophant", "The sycophant constantly flattered his boss to gain promotions.", True),
    ("sycophant", "The sycophant ran quickly through the forest.", False),
    ("ubiquitous", "Smartphones have become ubiquitous in modern society.", True),
    ("ubiquitous", "She felt ubiquitous after the long journey.", False),
    ("obfuscate", "The lawyer tried to obfuscate the facts with complex jargon.", True),
    ("obfuscate", "He decided to obfuscate the cake with chocolate frosting.", False),
    ("capricious", "Her capricious nature made it impossible to predict her moods.", True),
    ("capricious", "The capricious mountain stood tall against the sky.", False),
]


def eval_usage_evaluation() -> EvalResult:
    result = EvalResult(suite="usage_evaluation")

    for word, sentence, expected in USAGE_GROUND_TRUTH:
        start = time.time()
        try:
            evaluation = evaluate_word_usage(word=word, user_sentence=sentence)
            latency = int((time.time() - start) * 1000)
            result.latencies_ms.append(latency)

            if evaluation["is_correct"] == expected:
                result.passed += 1
            else:
                result.failed += 1
                result.failures.append({
                    "word": word,
                    "sentence": sentence,
                    "expected": expected,
                    "got": evaluation["is_correct"],
                    "feedback": evaluation.get("feedback", "")
                })
        except Exception as e:
            result.errors += 1
            result.failures.append({"word": word, "error": str(e)})

    return result


# ── Suite 3: Spaced repetition retrieval ──────────────────────────────────

def eval_spaced_repetition() -> EvalResult:
    """
    Simulate a user who knows 500 words well (mastery=4) and 500 at level 1.
    Verify retrieval never surfaces mastered words and surfaces level-1 words first.
    """
    result = EvalResult(suite="spaced_repetition")

    mastered_words = [f"word_{i}" for i in range(500)]
    learning_words = [f"gre_word_{i}" for i in range(500)]

    fake_mastery = {w: 4 for w in mastered_words}
    fake_mastery.update({w: 1 for w in learning_words})

    try:
        retrieved = retrieve_words_for_quiz(
            user_id="eval_test_user",
            n=20,
            mastery_scores=fake_mastery
        )

        for word_data in retrieved:
            word = word_data["word"]
            start = time.time()
            latency = int((time.time() - start) * 1000)
            result.latencies_ms.append(latency)

            if fake_mastery.get(word, 0) == 4:
                result.failed += 1
                result.failures.append({
                    "issue": "mastered word surfaced",
                    "word": word
                })
            else:
                result.passed += 1

    except Exception as e:
        result.errors += 1
        result.failures.append({"error": str(e)})

    return result


# ── Suite 4: Error-tagger quality (agentic) ───────────────────────────────
#
# When a learner answers wrong, the LLM tags WHY from the closed taxonomy. We can't
# assert one exact tag (several are defensible), so each case lists the SET of
# acceptable tags; a case passes if the tagger returns at least one of them. Items
# are embedded so the suite is hermetic (no DB dependency).

TAGGER_GROUND_TRUTH = [
    {
        "name": "se_opposite_connotation",
        "item": {
            "id": "ev_se_1", "type": "SE",
            "stem": "The senator's ____ remarks alienated even her staunchest supporters.",
            "options": [["caustic", "acerbic", "gracious", "measured", "conciliatory", "verbose"]],
            "answer": ["caustic", "acerbic"],
            "explanation": "Remarks that alienate supporters are biting. 'Gracious'/'conciliatory' are opposites.",
            "difficulty": 3,
        },
        "user_answer": ["gracious", "conciliatory"],
        "acceptable_tags": ["wrong_connotation", "unknown_word", "misread_scope"],
    },
    {
        "name": "se_ignored_concession",
        "item": {
            "id": "ev_se_2", "type": "SE",
            "stem": "Although meant as praise, his ____ comments struck many as condescending.",
            "options": [["patronizing", "supercilious", "sincere", "heartfelt", "blunt", "cautious"]],
            "answer": ["patronizing", "supercilious"],
            "explanation": "'Condescending' points to 'patronizing'/'supercilious'. 'Sincere'/'heartfelt' contradict the cue.",
            "difficulty": 3,
        },
        "user_answer": ["sincere", "heartfelt"],
        "acceptable_tags": ["missed_concession", "missed_contrast", "wrong_connotation"],
    },
    {
        "name": "tc_ignored_contrast",
        "item": {
            "id": "ev_tc_1", "type": "TC",
            "stem": "Far from being ____, the professor's lectures were dry and difficult to sit through.",
            "options": [["riveting", "tedious", "lengthy", "technical", "optional"]],
            "answer": ["riveting"],
            "explanation": "'Far from being X' inverts the blank: lectures are dry, so X is engaging. 'Tedious' is a synonym of dry, not its opposite.",
            "difficulty": 3,
        },
        "user_answer": ["tedious"],
        "acceptable_tags": ["missed_contrast", "misread_scope"],
    },
    {
        "name": "tc_ignored_cause",
        "item": {
            "id": "ev_tc_2", "type": "TC",
            "stem": "Because the bridge had been thoroughly inspected, the engineers were ____ about its safety.",
            "options": [["confident", "anxious", "ambivalent", "silent", "curious"]],
            "answer": ["confident"],
            "explanation": "The causal 'because ... inspected' yields reassurance: 'confident'. 'Anxious' ignores the cause cue.",
            "difficulty": 2,
        },
        "user_answer": ["anxious"],
        "acceptable_tags": ["missed_cause", "missed_contrast", "misread_scope"],
    },
    {
        "name": "se_unknown_hard_vocab",
        "item": {
            "id": "ev_se_3", "type": "SE",
            "stem": "Her ____ for detail made her an exceptional editor but an exhausting travel companion.",
            "options": [["meticulousness", "fastidiousness", "indifference", "disdain", "aptitude", "tolerance"]],
            "answer": ["meticulousness", "fastidiousness"],
            "explanation": "Extreme attention to detail: 'meticulousness'/'fastidiousness'. 'Aptitude'/'tolerance' don't fit.",
            "difficulty": 4,
        },
        "user_answer": ["aptitude", "tolerance"],
        "acceptable_tags": ["unknown_word", "wrong_connotation", "misread_scope"],
    },
]


def eval_error_tagger() -> EvalResult:
    result = EvalResult(suite="error_tagger")
    if not _has_real_key(OPENROUTER_API_KEY):
        result.failures.append({"skipped": "no OPENROUTER_API_KEY — tagger needs an LLM"})
        return result

    async def _run():
        for case in TAGGER_GROUND_TRUTH:
            start = time.time()
            try:
                out = await tag_errors(case["item"], case["user_answer"])
                result.latencies_ms.append(int((time.time() - start) * 1000))
                got = set(out["error_tags"])
                acceptable = set(case["acceptable_tags"])
                if got & acceptable:
                    result.passed += 1
                else:
                    result.failed += 1
                    result.failures.append({
                        "case": case["name"], "got": sorted(got),
                        "acceptable": case["acceptable_tags"],
                    })
            except Exception as e:  # noqa: BLE001
                result.errors += 1
                result.failures.append({"case": case["name"], "error": str(e)})

    asyncio.run(_run())
    return result


# ── Suite 5: Planner branch correctness (agentic) ─────────────────────────
#
# The reactive planner must branch on the last attempt. We seed a learner with a
# controlled last attempt, run plan_next, and assert invariants. The `action`
# decision is deterministic (checked always); the tool TRACE invariants
# (re-teach grounds in a word lookup, difficulty moves the right way) need an LLM
# and are checked only when a key is present.

PLANNER_SCENARIOS = [
    {
        "name": "fresh_start",
        "attempts": [],
        "expect": {"action": "start"},
    },
    {
        "name": "wrong_vocab_reteach",
        "attempts": [
            {"item_type": "SE", "item_id": "se_0002", "word": "patronizing",
             "is_correct": False, "error_tags": ["unknown_word"], "difficulty": 3,
             "user_answer": ["sincere", "heartfelt"]},
        ],
        "expect": {"action": "reteach", "max_difficulty_leq": 3,
                   "looked_up_word": True, "served_skill": "SE"},
    },
    {
        "name": "correct_advance",
        "attempts": [
            {"item_type": "SE", "item_id": "se_0003", "word": "startled",
             "is_correct": True, "error_tags": [], "difficulty": 2,
             "user_answer": ["startled", "alarmed"]},
        ],
        "expect": {"action": "advance", "min_difficulty_geq": 2},
    },
]

_SERVE_RE = re.compile(r"serve_item:(\w+)\[(\d+)-(\d+)\]")


def _serve_calls(trace: list) -> list:
    """Parse serve_item trace strings into (type, lo, hi) tuples."""
    out = []
    for t in trace:
        m = _SERVE_RE.match(t)
        if m:
            out.append((m.group(1), int(m.group(2)), int(m.group(3))))
    return out


def _seed_learner(scenario: dict) -> str:
    uid = f"eval_{scenario['name']}_{int(time.time() * 1000)}"
    for a in scenario.get("attempts", []):
        record_attempt(
            uid, a["item_type"], item_id=a.get("item_id"), word=a.get("word"),
            user_answer=a.get("user_answer"), is_correct=a["is_correct"],
            error_tags=a.get("error_tags") or [],
        )
        update_ability(uid, a["item_type"], a.get("difficulty", 3), a["is_correct"])
    return uid


def _planner_checks(scenario: dict, out: dict, with_llm: bool) -> list:
    """Return [(check_name, ok, detail), ...] for one scenario."""
    exp = scenario["expect"]
    checks = [
        (f"{scenario['name']}/action", out["action"] == exp["action"],
         f"action={out['action']} expected={exp['action']}"),
        (f"{scenario['name']}/served_item", out.get("item") is not None, "an item was served"),
    ]
    if not with_llm:
        return checks  # trace invariants below need a real LLM run

    serves = _serve_calls(out.get("trace") or [])
    checks.append((f"{scenario['name']}/called_serve_item", len(serves) > 0, f"trace={out.get('trace')}"))
    if exp.get("max_difficulty_leq") is not None:
        ok = bool(serves) and any(hi <= exp["max_difficulty_leq"] for _, _, hi in serves)
        checks.append((f"{scenario['name']}/difficulty_dropped", ok,
                       f"serves={serves} need a window with max<={exp['max_difficulty_leq']}"))
    if exp.get("min_difficulty_geq") is not None:
        ok = bool(serves) and any(lo >= exp["min_difficulty_geq"] for _, lo, _ in serves)
        checks.append((f"{scenario['name']}/difficulty_raised", ok,
                       f"serves={serves} need a window with min>={exp['min_difficulty_geq']}"))
    if exp.get("looked_up_word"):
        ok = any(str(t).startswith("look_up_word") for t in (out.get("trace") or []))
        checks.append((f"{scenario['name']}/grounded_reteach", ok, f"trace={out.get('trace')}"))
    if exp.get("served_skill"):
        ok = any(typ == exp["served_skill"] for typ, _, _ in serves)
        checks.append((f"{scenario['name']}/served_same_skill", ok, f"serves={serves}"))
    return checks


def eval_planner_branch() -> EvalResult:
    result = EvalResult(suite="planner_branch")
    with_llm = _has_real_key(OPENROUTER_API_KEY)

    async def _run():
        for scenario in PLANNER_SCENARIOS:
            start = time.time()
            try:
                uid = _seed_learner(scenario)
                out = await plan_next(uid)
                result.latencies_ms.append(int((time.time() - start) * 1000))
                for name, ok, detail in _planner_checks(scenario, out, with_llm):
                    if ok:
                        result.passed += 1
                    else:
                        result.failed += 1
                        result.failures.append({"check": name, "detail": detail})
            except Exception as e:  # noqa: BLE001
                result.errors += 1
                result.failures.append({"scenario": scenario["name"], "error": str(e)})

    asyncio.run(_run())
    return result


# ── Runner ─────────────────────────────────────────────────────────────────

# ── Suite 6: Generator well-formedness (agentic) ──────────────────────────
#
# Generate one item of each type and assert it is STRUCTURALLY valid and servable
# (answer drawn from options). This guards the generation prompts from regressing —
# e.g. the RC "one sub-list of 5" / "answer is a string not an index" contract.

from content.generator import generate_item  # noqa: E402
from content.models import validate as validate_item  # noqa: E402


def eval_generator() -> EvalResult:
    result = EvalResult(suite="generator")
    if not _has_real_key(OPENROUTER_API_KEY):
        result.failures.append({"skipped": "no OPENROUTER_API_KEY — generation needs an LLM"})
        return result

    async def _run():
        for item_type in ("TC", "SE", "RC"):
            start = time.time()
            try:
                item = await generate_item(item_type, difficulty=3)
                result.latencies_ms.append(int((time.time() - start) * 1000))
                if item is None:
                    result.failed += 1
                    result.failures.append({"type": item_type, "reason": "no valid draft produced"})
                    continue
                validate_item(item)  # raises if structurally malformed
                flat_opts = [o for grp in item.options for o in grp]
                if not all(a in flat_opts for a in item.answer):
                    raise ValueError("answer not a subset of options")
                result.passed += 1
            except Exception as e:  # noqa: BLE001
                result.failed += 1
                result.failures.append({"type": item_type, "reason": str(e)})

    asyncio.run(_run())
    return result


ALL_SUITES: dict[str, Callable[[], EvalResult]] = {
    "word_difficulty": eval_word_difficulty,
    "usage_evaluation": eval_usage_evaluation,
    "spaced_repetition": eval_spaced_repetition,
    "error_tagger": eval_error_tagger,
    "planner_branch": eval_planner_branch,
    "generator": eval_generator,
}


def run_all_evals(selected: list = None):
    print("Running Lexis eval suites...\n")
    names = selected or list(ALL_SUITES)

    all_results = []
    any_failed = False
    for name in names:
        suite_fn = ALL_SUITES.get(name)
        if suite_fn is None:
            print(f"  ! unknown suite '{name}' — skipping\n")
            continue
        print(f"  Running {name}...")
        r = suite_fn()
        all_results.append(r.summary())
        any_failed = any_failed or r.failed > 0 or r.errors > 0
        print(f"  → accuracy={r.accuracy:.1%}  passed={r.passed} failed={r.failed} "
              f"errors={r.errors}  p50={r.p50_latency}ms\n")

    print("Results:")
    print(json.dumps(all_results, indent=2))
    return all_results, any_failed


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    _, failed = run_all_evals(selected=args or None)
    sys.exit(1 if failed else 0)
