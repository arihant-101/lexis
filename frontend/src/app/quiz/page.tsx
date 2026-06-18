"use client";

import { useState, useEffect } from "react";
import { useAuth } from "@/lib/auth";

interface TurnResponse {
  session_id: string;
  agent_text: string;
  agent_audio_b64: string | null;
  current_word: string | null;
  is_correct: boolean | null;
  feedback: string | null;
  mastery_updates: { word: string; level: number }[];
}

// All backend calls go through the same-origin Next.js rewrite (/api/* -> backend),
// so no backend hostname is baked into the browser bundle (deploy-safe, no CORS).
const API = "/api";

type QuizState = "loading" | "question" | "result" | "done" | "error";

export default function QuizPage() {
  const { user, ready } = useAuth();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [currentWord, setCurrentWord] = useState<string | null>(null);
  const [agentText, setAgentText] = useState("");
  const [quizState, setQuizState] = useState<QuizState>("loading");
  const [answer, setAnswer] = useState("");
  const [lastResult, setLastResult] = useState<TurnResponse | null>(null);
  const [score, setScore] = useState({ correct: 0, total: 0 });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    fetch(`${API}/session/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: user.user_id, mode: "quiz" }),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error(`Session start failed (${r.status})`);
        return r.json();
      })
      .then(async (d) => {
        setSessionId(d.session_id);
        // First turn: get the question
        const res = await fetch(`${API}/session/${d.session_id}/turn`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ user_id: user.user_id, user_text: "start" }),
        });
        const data = await res.json().catch(() => null) as TurnResponse | null;
        if (!res.ok || !data) throw new Error(`Question load failed (${res.status})`);
        setCurrentWord(data.current_word);
        setAgentText(data.agent_text);
        setQuizState("question");
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Could not start quiz.");
        setQuizState("error");
      });
  }, [user]);

  async function submitAnswer() {
    if (!sessionId || !answer.trim() || !user) return;
    setQuizState("loading");
    setError(null);

    try {
      const res = await fetch(`${API}/session/${sessionId}/turn`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: user.user_id, user_text: answer }),
      });
      const data = await res.json().catch(() => null) as TurnResponse | null;
      if (!res.ok || !data) throw new Error(`Answer submit failed (${res.status})`);
      setLastResult(data);
      setScore((s) => ({
        correct: s.correct + (data.is_correct ? 1 : 0),
        total: s.total + 1,
      }));
      setAnswer("");
      setQuizState("result");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit answer.");
      setQuizState("error");
    }
  }

  async function nextWord() {
    if (!sessionId || !user) return;
    setQuizState("loading");
    setError(null);

    try {
      const res = await fetch(`${API}/session/${sessionId}/turn`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: user.user_id, user_text: "next" }),
      });
      const data = await res.json().catch(() => null) as TurnResponse | null;
      if (!res.ok || !data) throw new Error(`Next word failed (${res.status})`);
      if (!data.current_word) {
        setQuizState("done");
        return;
      }
      setCurrentWord(data.current_word);
      setAgentText(data.agent_text);
      setLastResult(null);
      setQuizState("question");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load next word.");
      setQuizState("error");
    }
  }

  if (!ready) return <div className="p-8 text-gray-500">Loading…</div>;

  return (
    <main className="min-h-screen bg-gray-50 flex flex-col items-center justify-center p-8">
      <div className="w-full max-w-lg">
        {/* Score bar */}
        <div className="flex justify-between items-center text-sm text-gray-500 mb-4">
          <a href="/dashboard" className="hover:text-gray-700">← Dashboard</a>
          <span>{score.correct}/{score.total} correct</span>
        </div>

        <div className="bg-white rounded-2xl shadow-sm p-8">
          {quizState === "loading" && (
            <div className="text-center text-gray-400 py-8">Loading…</div>
          )}

          {quizState === "error" && (
            <div className="text-center py-8">
              <h2 className="text-lg font-bold text-gray-900">Quiz could not continue</h2>
              <p className="text-sm text-red-600 mt-2">{error}</p>
              <a
                href="/dashboard"
                className="inline-block mt-6 bg-indigo-600 text-white px-6 py-3 rounded-xl font-medium hover:bg-indigo-700 transition"
              >
                Back to dashboard
              </a>
            </div>
          )}

          {quizState === "question" && (
            <>
              <div className="text-center mb-6">
                <span className="text-xs uppercase tracking-wide text-gray-400">Word</span>
                <h2 className="text-4xl font-bold text-gray-900 mt-1">
                  {currentWord?.toUpperCase()}
                </h2>
              </div>
              <p className="text-gray-600 text-sm mb-4">{agentText}</p>
              <textarea
                className="w-full border border-gray-200 rounded-xl p-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-none"
                rows={3}
                placeholder={`Use "${currentWord}" in a sentence…`}
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
              />
              <button
                onClick={submitAnswer}
                disabled={!answer.trim()}
                className="w-full mt-3 bg-indigo-600 text-white py-3 rounded-xl font-medium disabled:opacity-40 hover:bg-indigo-700 transition"
              >
                Submit
              </button>
            </>
          )}

          {quizState === "result" && lastResult && (
            <>
              <div
                className={`text-center text-2xl font-bold mb-4 ${
                  lastResult.is_correct ? "text-green-600" : "text-red-500"
                }`}
              >
                {lastResult.is_correct ? "Correct! ✅" : "Not quite ❌"}
              </div>
              <p className="text-gray-700 text-sm whitespace-pre-wrap mb-2">
                {lastResult.agent_text}
              </p>
              {lastResult.mastery_updates[0] && (
                <div className="mt-4 text-xs text-gray-400 text-center">
                  Mastery: {"⭐".repeat(lastResult.mastery_updates[0].level)} level {lastResult.mastery_updates[0].level}/4
                </div>
              )}
              <button
                onClick={nextWord}
                className="w-full mt-6 bg-indigo-600 text-white py-3 rounded-xl font-medium hover:bg-indigo-700 transition"
              >
                Next word →
              </button>
            </>
          )}

          {quizState === "done" && (
            <div className="text-center py-8">
              <div className="text-4xl mb-4">🎉</div>
              <h2 className="text-xl font-bold text-gray-900">Quiz complete!</h2>
              <p className="text-gray-500 mt-2">
                {score.correct} of {score.total} correct
              </p>
              <a
                href="/dashboard"
                className="inline-block mt-6 bg-indigo-600 text-white px-6 py-3 rounded-xl font-medium hover:bg-indigo-700 transition"
              >
                Back to dashboard
              </a>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
