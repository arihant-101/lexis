"""
Item models for the practice bank.

A single generic `Item` shape is stored in Postgres and sent to the frontend,
with per-type validators enforcing the rules that make an item well-formed.

Generic shape (matches the `items` DB row):
  - stem:    sentence/question; each blank is marked with "____" (in order)
  - options: list-of-lists — one option list per blank
  - answer:  list of correct option(s)

Per type:
  TC  N blanks, 3-5 options each, exactly one correct per blank.
  SE  1 blank, exactly 6 options, exactly 2 correct (synonymous) answers.
  RC  1 "blank" (the question), one option list, exactly one correct answer.
"""

from typing import Literal

from pydantic import BaseModel, field_validator

ItemType = Literal["TC", "SE", "RC", "vocab"]

BLANK = "____"


class Item(BaseModel):
    id: str
    type: ItemType
    stem: str
    options: list[list[str]]
    answer: list[str]
    explanation: str = ""
    target_words: list[str] = []
    difficulty: int = 3

    @field_validator("difficulty")
    @classmethod
    def _clamp_difficulty(cls, v: int) -> int:
        return max(1, min(int(v), 5))


def validate_tc(item: Item) -> None:
    """Validate a Text Completion item; raises ValueError on a malformed item."""
    if item.type != "TC":
        raise ValueError("validate_tc called on a non-TC item")
    n_blanks = item.stem.count(BLANK)
    if n_blanks < 1:
        raise ValueError("TC stem must contain at least one '____' blank")
    if len(item.options) != n_blanks:
        raise ValueError(f"TC: {n_blanks} blanks in stem but {len(item.options)} option groups")
    if len(item.answer) != n_blanks:
        raise ValueError(f"TC: {n_blanks} blanks but {len(item.answer)} answers")
    for i, (opts, ans) in enumerate(zip(item.options, item.answer)):
        if not (3 <= len(opts) <= 5):
            raise ValueError(f"TC blank {i + 1}: expected 3-5 options, got {len(opts)}")
        if len(set(opts)) != len(opts):
            raise ValueError(f"TC blank {i + 1}: duplicate options")
        if ans not in opts:
            raise ValueError(f"TC blank {i + 1}: answer '{ans}' not among its options")


def validate_se(item: Item) -> None:
    """Sentence Equivalence: one blank, exactly 6 options, exactly 2 correct synonyms."""
    if item.type != "SE":
        raise ValueError("validate_se called on a non-SE item")
    if item.stem.count(BLANK) != 1:
        raise ValueError("SE stem must contain exactly one '____' blank")
    if len(item.options) != 1:
        raise ValueError("SE must have exactly one option group")
    opts = item.options[0]
    if len(opts) != 6:
        raise ValueError(f"SE needs exactly 6 options, got {len(opts)}")
    if len(set(opts)) != 6:
        raise ValueError("SE options must be unique")
    if len(item.answer) != 2 or len(set(item.answer)) != 2:
        raise ValueError("SE needs exactly 2 distinct answers")
    for a in item.answer:
        if a not in opts:
            raise ValueError(f"SE answer '{a}' not among options")


def validate_rc(item: Item) -> None:
    """Reading Comprehension: one question, one option group, exactly one answer."""
    if item.type != "RC":
        raise ValueError("validate_rc called on a non-RC item")
    if len(item.options) != 1:
        raise ValueError("RC must have exactly one option group")
    opts = item.options[0]
    if len(opts) < 2:
        raise ValueError("RC needs at least 2 options")
    if len(set(opts)) != len(opts):
        raise ValueError("RC options must be unique")
    if len(item.answer) != 1:
        raise ValueError("RC needs exactly one answer")
    if item.answer[0] not in opts:
        raise ValueError("RC answer not among options")


VALIDATORS = {"TC": validate_tc, "SE": validate_se, "RC": validate_rc}


def validate(item: Item) -> None:
    """Run the per-type validator if one exists."""
    fn = VALIDATORS.get(item.type)
    if fn:
        fn(item)
