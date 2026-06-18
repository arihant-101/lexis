// Shared shapes for practice + coach modes. The backend `_safe`/SERVE_FIELDS
// projection (id, type, stem, options, target_words, difficulty) is the contract.

export type Mode = "TC" | "SE" | "RC";

export const MODES: { key: Mode; label: string }[] = [
  { key: "TC", label: "Text Completion" },
  { key: "SE", label: "Sentence Equivalence" },
  { key: "RC", label: "Reading" },
];

export interface Item {
  id: string;
  type: Mode;
  stem: string;
  options: string[][];
  target_words: string[];
  difficulty: number;
}

export interface AnswerResult {
  is_correct: boolean;
  correct_answer: string[];
  explanation: string;
  error_tags: string[];
}

// Shape returned by POST /coach/next (planner agent).
export interface CoachTurn {
  coaching_message: string;
  item: Item | null;
  action: "reteach" | "advance" | "start" | string;
  focus_skill: string;
  trace: string[];
}

// Shape returned by POST /coach/diagnose.
export interface Diagnosis {
  notes: string[];
  confusion_pairs: [string, string][];
}
