"""
Item generator — grows the practice bank so the planner has real content to adapt over.

The pipeline is deliberately a loop with two gates, because a generator without a
checker just mass-produces plausible-looking broken items:

  1. GENERATE   (strong model)  — draft an item of a type at a target difficulty.
  2. VALIDATE   (deterministic) — content.models.validate_* enforces structure
                                  (blank count, option counts, answer in options, …).
                                  A structural failure triggers ONE corrective retry.
  3. CRITIQUE   (cheap model)   — semantic gate: is the answer unambiguously correct,
                                  are the distractors actually wrong, are SE's two
                                  answers genuine synonyms with no second valid pair?
  4. STORE                      — only items that pass BOTH gates are inserted as
                                  status='approved', source='generated'.

Entry points: `await generate_item(...)` (one) and `await generate_batch(...)` (many).
"""

import re
from typing import Optional
from uuid import uuid4

from content.models import Item, validate
from llm.router import Task, acomplete_json
from memory.longterm import get_item_stems, insert_item
from observability.logger import log
from tools.config import OPENROUTER_API_KEY, _has_real_key

# Per-type rules handed to the generator. They mirror the deterministic validators
# exactly, so a compliant generation passes validate() on the first try.
TYPE_RULES = {
    "TC": (
        "TEXT COMPLETION. The stem is 1-2 sentences with one or two blanks, each written "
        "as '____'. A single-blank item must have exactly 5 options; a two-blank item must "
        "have exactly 3 options per blank. Exactly one option per blank yields a coherent "
        "sentence. `options` is a list with one sub-list per blank (in order); `answer` is "
        "one correct option per blank, in order, each drawn from its own sub-list. "
        "`target_words` = the correct answer word(s). Use a real contextual cue "
        "(contrast/cause/concession) so the answer is defensible, not a guess."
    ),
    "SE": (
        "SENTENCE EQUIVALENCE. The stem has exactly ONE blank ('____'). Provide exactly 6 "
        "options in a single sub-list. Exactly TWO of them are near-synonyms that BOTH "
        "complete the sentence with the SAME meaning — those two are the `answer`. Critically, "
        "no OTHER pair among the 6 may also form a valid equivalent sentence. `target_words` = "
        "the two answers."
    ),
    "RC": (
        "READING COMPREHENSION. The stem is a self-contained passage of 80-130 words, then a "
        "blank line, then 'Question: <a single question about the passage>'. `options` must be "
        "a list containing exactly ONE sub-list of 5 answer-choice strings, like "
        '[["choice A", "choice B", "choice C", "choice D", "choice E"]]. Exactly one is '
        "correct. Distractors must be plausible but clearly unsupported by the passage. "
        "`target_words` may be []."
    ),
}

GEN_SYSTEM = (
    "You are a GRE Verbal item writer. Produce ONE high-quality, original practice item as "
    "JSON with keys: stem, options (list of lists), answer (list), explanation (<=2 "
    "sentences on why the answer is right and the cue that signals it), target_words (list). "
    "Difficulty {d}/5 means: 1-2 common words, 3 mid GRE vocabulary, 4-5 advanced/abstract "
    "vocabulary and subtler cues. Every entry in `answer` must be an option string copied "
    "VERBATIM from `options` — never an index or a paraphrase.\n\n{rules}"
)

CRITIC_SYSTEM = (
    "You are a strict GRE item reviewer. The item's TYPE dictates how many answers are "
    "correct BY DESIGN — never reject an item merely for having the number of answers its "
    "type requires:\n__RULES__\n\n"
    "Given that, reject ONLY if: the keyed answer(s) are not clearly the best choice(s); a "
    "non-keyed distractor is equally defensible; (SE) the two keyed words are not genuine "
    "synonyms OR some OTHER pair also forms an equivalent sentence; the explanation "
    "contradicts the answer; or the prose is ambiguous/awkward. "
    'Return JSON: {"approved": true|false, "reason": "<one sentence>", '
    '"suggested_difficulty": <1-5>}.'
)


def _norm(stem: str) -> str:
    return re.sub(r"\s+", " ", stem or "").strip().lower()


def _item_to_text(item: Item) -> str:
    return (
        f"type={item.type} difficulty={item.difficulty}\n"
        f"stem: {item.stem}\n"
        f"options: {item.options}\n"
        f"answer: {item.answer}\n"
        f"explanation: {item.explanation}"
    )


async def generate_item(item_type: str, difficulty: int = 3, avoid: Optional[list] = None) -> Optional[Item]:
    """Draft + structurally validate one item. One corrective retry on a validation failure.
    Returns a structurally-valid Item, or None if generation/validation never succeeds."""
    if not _has_real_key(OPENROUTER_API_KEY):
        return None
    if item_type not in TYPE_RULES:
        raise ValueError(f"unsupported item_type {item_type!r}")

    system = GEN_SYSTEM.format(d=difficulty, rules=TYPE_RULES[item_type])
    user = f"Generate one {item_type} item at difficulty {difficulty}/5."
    if avoid:
        user += " Make it distinct from these existing stems:\n" + "\n".join(f"- {s}" for s in avoid[:12])

    for _attempt in range(2):
        try:
            data = await acomplete_json(Task.GENERATE, system, user)
            data["id"] = f"gen_{item_type.lower()}_{uuid4().hex[:8]}"
            data["type"] = item_type
            data["difficulty"] = difficulty
            item = Item(**data)
            validate(item)            # deterministic structural gate
            return item
        except Exception as exc:      # noqa: BLE001
            user += f"\n\nYour previous attempt was rejected: {exc}. Return a corrected item."
    log("generate_item_failed", item_type=item_type, difficulty=difficulty)
    return None


async def critique_item(item: Item) -> dict:
    """Semantic gate. Without a key, defer to the structural validator only (approve)."""
    if not _has_real_key(OPENROUTER_API_KEY):
        return {"approved": True, "reason": "structural-only (no critic model)"}
    try:
        system = CRITIC_SYSTEM.replace("__RULES__", TYPE_RULES.get(item.type, ""))
        data = await acomplete_json(Task.VALIDATE, system, _item_to_text(item))
        return {
            "approved": bool(data.get("approved")),
            "reason": str(data.get("reason", "")),
            "suggested_difficulty": data.get("suggested_difficulty"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"approved": False, "reason": f"critic error: {exc}"}


async def generate_batch(item_type: str, n: int, difficulty: int = 3) -> dict:
    """Generate up to `n` approved items of a type. Over-attempts to absorb rejects,
    dedupes against the existing bank, and only stores items that clear both gates."""
    existing = {_norm(s) for s in get_item_stems(item_type)}
    avoid = [s for s in get_item_stems(item_type)][:12]

    accepted, rejected = [], []
    attempts = 0
    max_attempts = n * 3 + 2          # bounded so a bad streak can't loop forever

    while len(accepted) < n and attempts < max_attempts:
        attempts += 1
        item = await generate_item(item_type, difficulty, avoid)
        if item is None:
            rejected.append({"stage": "generate/validate", "reason": "no valid draft"})
            continue
        if _norm(item.stem) in existing:
            rejected.append({"stage": "dedupe", "id": item.id, "reason": "duplicate stem"})
            continue

        crit = await critique_item(item)
        if not crit["approved"]:
            rejected.append({"stage": "critique", "id": item.id, "reason": crit["reason"]})
            continue

        # apply the critic's difficulty correction if it offered one
        sd = crit.get("suggested_difficulty")
        if isinstance(sd, int) and 1 <= sd <= 5:
            item.difficulty = sd

        insert_item({**item.model_dump(), "status": "approved", "source": "generated"})
        existing.add(_norm(item.stem))
        avoid.append(item.stem)
        accepted.append({"id": item.id, "difficulty": item.difficulty, "stem": item.stem})

    log("generate_batch_done", item_type=item_type, requested=n,
        accepted=len(accepted), rejected=len(rejected), attempts=attempts)
    return {
        "item_type": item_type, "requested": n,
        "accepted": accepted, "rejected": rejected,
        "accept_rate": round(len(accepted) / attempts, 2) if attempts else None,
    }
