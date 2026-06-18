"use client";

import { ReactNode } from "react";
import { AnswerResult, Item, MODES } from "@/lib/types";

// Presentational renderer for a TC/SE/RC item + post-answer reveal.
// The parent owns all state (item, selected, result) and the "what comes next"
// action, which it passes via `footer` — practice shows "Next", coach shows "Continue".
interface Props {
  item: Item;
  selected: string[];
  setSelected: (s: string[]) => void;
  result: AnswerResult | null;
  onSubmit: () => void;
  loading: boolean;
  footer?: ReactNode; // rendered after the result reveal (parent decides next step)
}

export function isFilled(item: Item, selected: string[]): boolean {
  if (item.type === "TC") return selected.length === item.options.length && selected.every(Boolean);
  if (item.type === "SE") return selected.length === 2;
  return selected.length === 1; // RC
}

export default function ItemCard({ item, selected, setSelected, result, onSubmit, loading, footer }: Props) {
  const filled = isFilled(item, selected);

  // option styling once the answer is revealed
  function optClass(opt: string): string {
    if (!result) return "border-gray-300 bg-gray-50";
    if (result.correct_answer.includes(opt)) return "border-green-400 bg-green-50 text-green-800";
    if (selected.includes(opt)) return "border-red-400 bg-red-50 text-red-700";
    return "border-gray-200 bg-white text-gray-400";
  }

  function toggleSE(opt: string) {
    if (result) return;
    setSelected(
      selected.includes(opt) ? selected.filter((x) => x !== opt) : selected.length < 2 ? [...selected, opt] : selected
    );
  }

  return (
    <>
      <div className="text-xs uppercase tracking-wide text-gray-400 mb-3">
        {MODES.find((m) => m.key === item.type)?.label} · difficulty {item.difficulty}/5
      </div>

      {/* TEXT COMPLETION — inline dropdowns */}
      {item.type === "TC" && (
        <p className="text-lg leading-relaxed text-gray-800 mb-6">
          {item.stem.split("____").map((part, i) => (
            <span key={i}>
              {part}
              {i < item.options.length && (
                <select
                  value={selected[i] ?? ""}
                  disabled={!!result}
                  onChange={(e) => {
                    const ns = [...selected];
                    ns[i] = e.target.value;
                    setSelected(ns);
                  }}
                  className={`mx-1 my-1 inline-block rounded-lg border px-2 py-1 text-base ${optClass(selected[i] ?? "__none__")}`}
                >
                  <option value="">▼ choose…</option>
                  {item.options[i].map((o) => (
                    <option key={o} value={o}>{o}</option>
                  ))}
                </select>
              )}
            </span>
          ))}
        </p>
      )}

      {/* SENTENCE EQUIVALENCE — pick exactly two */}
      {item.type === "SE" && (
        <>
          <p className="text-lg leading-relaxed text-gray-800 mb-2">
            {item.stem.split("____").map((part, i) => (
              <span key={i}>
                {part}
                {i === 0 && <span className="px-6 mx-1 border-b-2 border-gray-400" />}
              </span>
            ))}
          </p>
          <p className="text-xs text-gray-400 mb-4">Pick the <b>two</b> words that both complete the sentence with the same meaning.</p>
          <div className="grid grid-cols-2 gap-2 mb-6">
            {item.options[0].map((o) => (
              <button
                key={o}
                onClick={() => toggleSE(o)}
                disabled={!!result}
                className={`rounded-lg border px-3 py-2 text-sm text-left transition ${
                  result ? optClass(o) : selected.includes(o) ? "border-indigo-500 bg-indigo-50 text-indigo-800" : "border-gray-300 bg-gray-50 hover:bg-gray-100"
                }`}
              >
                {selected.includes(o) ? "☑ " : "☐ "}{o}
              </button>
            ))}
          </div>
        </>
      )}

      {/* READING — passage + radios */}
      {item.type === "RC" && (
        <>
          <div className="text-base leading-relaxed text-gray-800 mb-4 space-y-3">
            {item.stem.split("\n\n").map((para, i) => (
              <p key={i} className={para.startsWith("Question:") ? "font-semibold text-gray-900" : ""}>{para}</p>
            ))}
          </div>
          <div className="space-y-2 mb-6">
            {item.options[0].map((o) => (
              <button
                key={o}
                onClick={() => !result && setSelected([o])}
                disabled={!!result}
                className={`block w-full rounded-lg border px-3 py-2 text-sm text-left transition ${
                  result ? optClass(o) : selected.includes(o) ? "border-indigo-500 bg-indigo-50 text-indigo-800" : "border-gray-300 bg-gray-50 hover:bg-gray-100"
                }`}
              >
                {selected.includes(o) ? "● " : "○ "}{o}
              </button>
            ))}
          </div>
        </>
      )}

      {!result ? (
        <button
          onClick={onSubmit}
          disabled={!filled || loading}
          className="w-full bg-indigo-600 text-white py-3 rounded-xl font-medium disabled:opacity-40 hover:bg-indigo-700 transition"
        >
          Submit
        </button>
      ) : (
        <div>
          <div className={`text-lg font-bold mb-2 ${result.is_correct ? "text-green-600" : "text-red-500"}`}>
            {result.is_correct ? "Correct ✅" : "Not quite ❌"}
          </div>
          {!result.is_correct && (
            <p className="text-sm text-gray-600 mb-2">
              Correct answer: <span className="font-semibold">{result.correct_answer.join(", ")}</span>
            </p>
          )}
          <p className="text-sm text-gray-700 whitespace-pre-wrap">{result.explanation}</p>
          {result.error_tags.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {result.error_tags.map((t) => (
                <span key={t} className="text-xs bg-amber-100 text-amber-800 rounded-full px-2 py-1">
                  {t.replace(/_/g, " ")}
                </span>
              ))}
            </div>
          )}
          {footer}
        </div>
      )}
    </>
  );
}
