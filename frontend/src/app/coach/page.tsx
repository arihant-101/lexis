"use client";

import { useCallback, useEffect, useState } from "react";
import ItemCard from "@/components/ItemCard";
import UserBadge from "@/components/UserBadge";
import { postJSON } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { AnswerResult, CoachTurn, Diagnosis, Item } from "@/lib/types";

// How the agent's chosen action is surfaced to the learner — this is what makes
// the reactive loop visible: you can SEE it re-teach vs. level up between items.
const ACTION_BADGE: Record<string, { label: string; cls: string }> = {
  reteach: { label: "Re-teaching", cls: "bg-amber-100 text-amber-800" },
  advance: { label: "Leveling up", cls: "bg-green-100 text-green-700" },
  start: { label: "Getting started", cls: "bg-indigo-100 text-indigo-700" },
};

function initialSelected(item: Item): string[] {
  return item.type === "TC" ? new Array(item.options.length).fill("") : [];
}

export default function CoachPage() {
  const { user, ready } = useAuth();
  const [turn, setTurn] = useState<CoachTurn | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [thinking, setThinking] = useState(false); // agent deciding the next step
  const [score, setScore] = useState({ correct: 0, total: 0 });
  const [error, setError] = useState<string | null>(null);
  const [showTrace, setShowTrace] = useState(false);
  const [ended, setEnded] = useState(false);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);

  // Ask the planner agent for the next step. It reads the last recorded attempt
  // (submitted just before) and branches: re-teach + drop difficulty, or advance.
  const askCoach = useCallback(async () => {
    if (!user) return;
    setThinking(true);
    setResult(null);
    setError(null);
    try {
      const t = await postJSON<CoachTurn>("/coach/next", { user_id: user.user_id });
      setTurn(t);
      if (t.item) setSelected(initialSelected(t.item));
    } catch {
      setError("The coach couldn't decide a next step. Try again.");
    } finally {
      setThinking(false);
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    if (user) askCoach();
  }, [askCoach, user]);

  async function submit() {
    if (!turn?.item || !user) return;
    setLoading(true);
    try {
      const d = await postJSON<AnswerResult>("/items/answer", {
        user_id: user.user_id,
        item_id: turn.item.id,
        user_answer: selected,
      });
      setResult(d);
      setScore((s) => ({ correct: s.correct + (d.is_correct ? 1 : 0), total: s.total + 1 }));
    } catch {
      setError("Could not submit your answer.");
    } finally {
      setLoading(false);
    }
  }

  async function endSession() {
    if (!user) return;
    setLoading(true);
    try {
      const d = await postJSON<Diagnosis>("/coach/diagnose", { user_id: user.user_id });
      setDiagnosis(d);
    } catch {
      setDiagnosis({ notes: [], confusion_pairs: [] });
    } finally {
      setEnded(true);
      setLoading(false);
    }
  }

  const badge = turn ? ACTION_BADGE[turn.action] ?? ACTION_BADGE.start : null;

  if (!ready) return <div className="p-8 text-gray-500">Loading…</div>;

  return (
    <main className="min-h-screen bg-gray-50 flex flex-col items-center p-8">
      <div className="w-full max-w-2xl">
        <div className="flex justify-between items-center text-sm text-gray-500 mb-4">
          <a href="/dashboard" className="hover:text-gray-700">← Dashboard</a>
          <div className="flex gap-4 items-center">
            <a href="/practice" className="hover:text-gray-700">Self-practice</a>
            <span>{score.correct}/{score.total} correct</span>
            <UserBadge username={user!.username} />
          </div>
        </div>

        <h1 className="text-2xl font-bold text-gray-900 mb-1">Coach session</h1>
        <p className="text-sm text-gray-500 mb-4">Lexis picks each item, reacts to how you did, and adapts as you go.</p>

        {/* ── End-of-session summary ─────────────────────────────── */}
        {ended ? (
          <div className="bg-white rounded-2xl shadow-sm p-8">
            <div className="text-3xl mb-2">📋</div>
            <h2 className="text-xl font-bold text-gray-900 mb-1">Session summary</h2>
            <p className="text-sm text-gray-500 mb-4">{score.correct}/{score.total} correct this session.</p>
            {diagnosis && diagnosis.notes.length > 0 ? (
              <ul className="list-disc list-inside space-y-1 text-sm text-gray-700 mb-4">
                {diagnosis.notes.map((n, i) => <li key={i}>{n}</li>)}
              </ul>
            ) : (
              <p className="text-sm text-gray-500 mb-4">Not enough attempts yet for a pattern — keep going next time.</p>
            )}
            {diagnosis && diagnosis.confusion_pairs.length > 0 && (
              <div className="mb-4">
                <div className="text-xs uppercase tracking-wide text-gray-400 mb-2">Words you mix up</div>
                <div className="flex flex-wrap gap-2">
                  {diagnosis.confusion_pairs.map((p, i) => (
                    <span key={i} className="text-xs bg-rose-100 text-rose-700 rounded-full px-2 py-1">
                      {p[0]} ↔ {p[1]}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <a href="/coach" className="inline-block bg-indigo-600 text-white px-5 py-2.5 rounded-xl font-medium hover:bg-indigo-700 transition">
              Start another session
            </a>
          </div>
        ) : (
          <>
            {/* ── Coach message + action badge (the visible agency) ── */}
            {turn && (
              <div className="bg-indigo-50 border border-indigo-100 rounded-2xl p-4 mb-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-lg">🧑‍🏫</span>
                  {badge && <span className={`text-xs font-medium rounded-full px-2 py-0.5 ${badge.cls}`}>{badge.label}</span>}
                  {turn.focus_skill && (
                    <span className="text-xs text-gray-500">focus: <b>{turn.focus_skill}</b></span>
                  )}
                </div>
                <p className="text-sm text-gray-800 whitespace-pre-wrap">
                  {turn.coaching_message || "Let's begin — here's your first item."}
                </p>
                {turn.trace && turn.trace.length > 0 && (
                  <div className="mt-2">
                    <button onClick={() => setShowTrace((v) => !v)} className="text-xs text-indigo-500 hover:text-indigo-700">
                      {showTrace ? "Hide" : "Why this?"}
                    </button>
                    {showTrace && (
                      <code className="block mt-1 text-[11px] text-gray-500 bg-white/60 rounded p-2">
                        {turn.trace.join(" → ")}
                      </code>
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="bg-white rounded-2xl shadow-sm p-8">
              {error && <div className="text-sm text-red-600 mb-4">{error}</div>}
              {(loading || thinking) && !turn?.item && (
                <div className="text-center text-gray-400 py-8">{thinking ? "Coach is thinking…" : "Loading…"}</div>
              )}

              {turn && !turn.item && !thinking && (
                <div className="text-center py-8">
                  <div className="text-4xl mb-3">🎉</div>
                  <h2 className="text-xl font-bold text-gray-900">You&apos;ve cleared the available items!</h2>
                  <p className="text-gray-500 mt-2">Wrap up to see your session summary.</p>
                </div>
              )}

              {turn?.item && (
                <ItemCard
                  item={turn.item}
                  selected={selected}
                  setSelected={setSelected}
                  result={result}
                  onSubmit={submit}
                  loading={loading}
                  footer={
                    <button
                      onClick={askCoach}
                      disabled={thinking}
                      className="w-full mt-6 bg-indigo-600 text-white py-3 rounded-xl font-medium disabled:opacity-40 hover:bg-indigo-700 transition"
                    >
                      {thinking ? "Coach is thinking…" : "Continue →"}
                    </button>
                  }
                />
              )}
            </div>

            <button onClick={endSession} disabled={loading} className="w-full mt-4 text-sm text-gray-500 hover:text-gray-700">
              End session &amp; get my summary
            </button>
          </>
        )}
      </div>
    </main>
  );
}
