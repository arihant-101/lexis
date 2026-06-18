"""
Closed error taxonomy for GRE Verbal answer analysis.

When a user gets an item wrong, the evaluator tags WHY with one or more of these.
Keeping it a fixed, small set is what makes Phase 2's error-pattern diagnosis
possible ("you keep missing contrast cues") instead of free-text noise.
"""

from enum import Enum


class ErrorTag(str, Enum):
    UNKNOWN_WORD = "unknown_word"          # didn't know the target word's meaning
    WRONG_CONNOTATION = "wrong_connotation"  # knew denotation, missed positive/negative tone
    WRONG_REGISTER = "wrong_register"      # formality/usage mismatch
    MISSED_CONTRAST = "missed_contrast"    # ignored a contrast cue (but, yet, however)
    MISSED_CONCESSION = "missed_concession"  # ignored a concession (although, despite)
    MISSED_CAUSE = "missed_cause"          # ignored a causal cue (because, thus)
    MISREAD_SCOPE = "misread_scope"        # misread what the blank/sentence refers to
    GRAMMAR = "grammar"                    # grammatical agreement error
    CARELESS = "careless"                  # plausibly knew it; slip
    NONE = "none"                          # no specific error (e.g. correct answer)


ALL_TAGS: list[str] = [t.value for t in ErrorTag]
