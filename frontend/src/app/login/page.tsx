"use client";

import { useState } from "react";
import { postJSON } from "@/lib/api";
import { AuthUser, setUser } from "@/lib/auth";

export default function LoginPage() {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const user = await postJSON<AuthUser>(`/auth/${mode}`, { username, password });
      setUser(user);
      window.location.href = "/dashboard";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-gray-50 flex items-center justify-center p-8">
      <div className="w-full max-w-sm">
        <div className="text-center mb-6">
          <h1 className="text-3xl font-bold text-gray-900">Lexis</h1>
          <p className="text-gray-500 text-sm mt-1">Your adaptive GRE Verbal coach</p>
        </div>

        {/* Mode toggle */}
        <div className="flex gap-2 mb-4">
          {(["login", "signup"] as const).map((m) => (
            <button
              key={m}
              onClick={() => { setMode(m); setError(null); }}
              className={`flex-1 rounded-xl py-2 text-sm font-medium transition ${
                mode === m ? "bg-indigo-600 text-white" : "bg-white border border-gray-200 text-gray-600 hover:bg-gray-50"
              }`}
            >
              {m === "login" ? "Log in" : "Sign up"}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="bg-white rounded-2xl shadow-sm p-6 space-y-4">
          <div>
            <label className="block text-sm text-gray-600 mb-1">Username</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoCapitalize="none"
              autoComplete="username"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
              placeholder="e.g. tester_anita"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-600 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
              placeholder="••••••"
            />
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <button
            type="submit"
            disabled={loading || !username || !password}
            className="w-full bg-indigo-600 text-white py-2.5 rounded-xl font-medium disabled:opacity-40 hover:bg-indigo-700 transition"
          >
            {loading ? "…" : mode === "login" ? "Log in" : "Create account"}
          </button>

          <p className="text-xs text-gray-400 text-center">
            {mode === "login"
              ? "New here? Switch to Sign up to start a fresh progress profile."
              : "Pick any username — each one keeps its own separate progress."}
          </p>
        </form>
      </div>
    </main>
  );
}
