"use client";

import { useState, useRef, useEffect } from "react";
import { useAuth } from "@/lib/auth";

interface TurnResponse {
  session_id: string;
  agent_text: string;
  agent_audio_b64: string | null;
  hindi_translation: string | null;
  current_word: string | null;
  is_correct: boolean | null;
  feedback: string | null;
  mastery_updates: { word: string; level: number; next_review: string }[];
}

// All backend calls go through the same-origin Next.js rewrite (/api/* -> backend),
// so no backend hostname is baked into the browser bundle (deploy-safe, no CORS).
const API = "/api";

function arrayBufferToBase64(buffer: ArrayBuffer) {
  let binary = "";
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < bytes.byteLength; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function renderAgentText(text: string) {
  return text.split("\n").map((line, index) => {
    const trimmed = line.trim();
    const heading = trimmed.match(/^\*\*(.+)\*\*$/);
    if (heading) {
      return (
        <div key={index} className="font-bold text-gray-900 mb-2">
          {heading[1]}
        </div>
      );
    }

    const boldParts = line.split(/(\*\*[^*]+\*\*)/g);
    return (
      <div key={index} className={trimmed ? "mb-1" : "h-3"}>
        {boldParts.map((part, partIndex) => {
          if (part.startsWith("**") && part.endsWith("**")) {
            return <strong key={partIndex}>{part.slice(2, -2)}</strong>;
          }
          return <span key={partIndex}>{part}</span>;
        })}
      </div>
    );
  });
}

export default function LearnPage() {
  const { user, ready } = useAuth();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [turns, setTurns] = useState<{ role: "agent" | "user"; text: string }[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const startedRef = useRef(false);
  const inFlightRef = useRef(false);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);

  // Start session on mount
  useEffect(() => {
    if (!user || startedRef.current) return;
    startedRef.current = true;

    fetch(`${API}/session/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: user.user_id, mode: "learn" }),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error(`Session start failed (${r.status})`);
        return r.json();
      })
      .then((d) => {
        setSessionId(d.session_id);
        sendTurn(d.session_id, "", null); // kick off first word
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Could not start a learning session.");
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function sendTurn(sid: string, text: string, audiob64: string | null) {
    if (inFlightRef.current || !user) return;
    inFlightRef.current = true;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/session/${sid}/turn`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: user.user_id, user_text: text, user_audio_b64: audiob64 }),
      });
      const data = await res.json().catch(() => null) as TurnResponse | null;
      if (!res.ok || !data) throw new Error(`Turn failed (${res.status})`);

      if (text) setTurns((t) => [...t, { role: "user", text }]);
      setTurns((t) => [...t, { role: "agent", text: data.agent_text }]);

      // Play audio if present
      if (data.agent_audio_b64) {
        currentAudioRef.current?.pause();
        currentAudioRef.current = null;

        const audio = new Audio(`data:audio/wav;base64,${data.agent_audio_b64}`);
        currentAudioRef.current = audio;
        audio.play().catch(() => {});
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Something went wrong while sending that turn.";
      setError(message);
      if (text) setTurns((t) => [...t, { role: "user", text }]);
      setTurns((t) => [...t, { role: "agent", text: `Local dev error: ${message}` }]);
    } finally {
      inFlightRef.current = false;
      setLoading(false);
    }
  }

  async function handleSend() {
    if (!sessionId || !input.trim() || inFlightRef.current) return;
    const text = input.trim();
    setInput("");
    await sendTurn(sessionId, text, null);
  }

  async function toggleRecording() {
    if (recording) {
      mediaRecorderRef.current?.stop();
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("Microphone access was blocked or unavailable.");
      return;
    }
    const mr = new MediaRecorder(stream);
    chunksRef.current = [];
    mr.ondataavailable = (e) => chunksRef.current.push(e.data);
    mr.start();
    mediaRecorderRef.current = mr;
    setRecording(true);
    mr.onstop = async () => {
      setRecording(false);
      const blob = new Blob(chunksRef.current, { type: "audio/webm" });
      const arrayBuffer = await blob.arrayBuffer();
      const b64 = arrayBufferToBase64(arrayBuffer);
      if (sessionId) await sendTurn(sessionId, "", b64);
      stream.getTracks().forEach((t) => t.stop());
    };
  }

  if (!ready) return <div className="p-8 text-gray-500">Loading…</div>;

  return (
    <main className="flex flex-col h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b px-6 py-4 flex items-center gap-3">
        <a href="/dashboard" className="text-gray-400 hover:text-gray-600">←</a>
        <h1 className="font-semibold text-gray-900">Learn</h1>
        {loading && <span className="ml-2 text-xs text-indigo-500 animate-pulse">thinking…</span>}
      </header>
      {error && (
        <div className="bg-red-50 border-b border-red-100 px-6 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
        {!turns.length && !loading && !error && (
          <div className="text-center text-sm text-gray-400 mt-12">
            Starting your learning session...
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className={`flex ${t.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap ${
                t.role === "user"
                  ? "bg-indigo-600 text-white"
                  : "bg-white border border-gray-200 text-gray-800"
              }`}
            >
              {t.role === "agent" ? renderAgentText(t.text) : t.text}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="bg-white border-t px-4 py-3 flex gap-2">
        <input
          className="flex-1 border border-gray-200 rounded-xl px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
          placeholder="Type a sentence using the word, or record…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleSend();
            }
          }}
          disabled={loading}
        />
        <button
          onClick={toggleRecording}
          className={`px-3 py-2 rounded-xl text-sm font-medium transition ${
            recording
              ? "bg-red-500 text-white"
              : "bg-gray-100 text-gray-600 hover:bg-gray-200"
          }`}
        >
          {recording ? "⏹ Stop" : "🎙 Speak"}
        </button>
        <button
          onClick={handleSend}
          disabled={loading || inFlightRef.current || !input.trim()}
          className="bg-indigo-600 text-white px-4 py-2 rounded-xl text-sm font-medium disabled:opacity-40 hover:bg-indigo-700 transition"
        >
          Send
        </button>
      </div>
    </main>
  );
}
