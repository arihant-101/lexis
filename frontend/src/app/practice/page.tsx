"use client";

import { useCallback, useEffect, useState } from "react";
import ItemCard from "@/components/ItemCard";
import UserBadge from "@/components/UserBadge";
import { postJSON } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { AnswerResult, Item, Mode, MODES } from "@/lib/types";

export default function PracticePage() {
  const { user, ready } = useAuth();
  const [mode, setMode] = useState<Mode>("TC");
  const [item, setItem] = useState<Item | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [done, setDone] = useState(false);
  const [score, setScore] = useState({ correct: 0, total: 0 });
  const [error, setError] = useState<string | null>(null);

  const loadNext = useCallback(async (m: Mode) => {
    if (!user) return;
    setLoading(true);
    setResult(null);
    setError(null);
    setDone(false);
    try {
      const d = await postJSON<{ item: Item | null }>("/items/next", { user_id: user.user_id, item_type: m });
      if (!d.item) {
        setItem(null);
        setDone(true);
      } else {
        setItem(d.item);
        setSelected(d.item.type === "TC" ? new Array(d.item.options.length).fill("") : []);
      }
    } catch {
      setError("Could not load the next item.");
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    if (user) loadNext(mode);
  }, [mode, loadNext, user]);

  async function submit() {
    if (!item || !user) return;
    setLoading(true);
    try {
      const d = await postJSON<AnswerResult>("/items/answer", {
        user_id: user.user_id,
        item_id: item.id,
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

  if (!ready) return <div className="p-8 text-gray-500">Loading…</div>;

  return (
    <main className="min-h-screen bg-gray-50 flex flex-col items-center p-8">
      <div className="w-full max-w-2xl">
        <div className="flex justify-between items-center text-sm text-gray-500 mb-4">
          <a href="/dashboard" className="hover:text-gray-700">← Dashboard</a>
          <div className="flex gap-4 items-center">
            <a href="/coach" className="text-indigo-600 hover:text-indigo-700 font-medium">Coach me →</a>
            <span>{score.correct}/{score.total} correct</span>
            <UserBadge username={user!.username} />
          </div>
        </div>

        {/* Mode tabs */}
        <div className="flex gap-2 mb-4">
          {MODES.map((m) => (
            <button
              key={m.key}
              onClick={() => setMode(m.key)}
              className={`flex-1 rounded-xl py-2 text-sm font-medium transition ${
                mode === m.key ? "bg-indigo-600 text-white" : "bg-white border border-gray-200 text-gray-600 hover:bg-gray-50"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>

        <div className="bg-white rounded-2xl shadow-sm p-8">
          {loading && !item && <div className="text-center text-gray-400 py-8">Loading…</div>}
          {error && <div className="text-sm text-red-600 mb-4">{error}</div>}

          {done && (
            <div className="text-center py-8">
              <div className="text-4xl mb-3">🎉</div>
              <h2 className="text-xl font-bold text-gray-900">You&apos;ve cleared every {mode} item!</h2>
              <p className="text-gray-500 mt-2">Try another type above, or come back later.</p>
            </div>
          )}

          {item && !done && (
            <ItemCard
              item={item}
              selected={selected}
              setSelected={setSelected}
              result={result}
              onSubmit={submit}
              loading={loading}
              footer={
                <button
                  onClick={() => loadNext(mode)}
                  className="w-full mt-6 bg-indigo-600 text-white py-3 rounded-xl font-medium hover:bg-indigo-700 transition"
                >
                  Next →
                </button>
              }
            />
          )}
        </div>
      </div>
    </main>
  );
}
