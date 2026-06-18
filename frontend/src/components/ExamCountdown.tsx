"use client";

import { useState } from "react";
import { putJSON } from "@/lib/api";

// Per-user GRE countdown with an inline date editor. The parent owns the current
// value; this component persists changes via PUT and reports them back.
interface Props {
  userId: string;
  examDate: string | null; // "YYYY-MM-DD" or null
  onChange: (next: string | null) => void;
}

function daysUntil(isoDate: string): number {
  const [y, m, d] = isoDate.split("-").map(Number);
  const exam = new Date(y, m - 1, d);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((exam.getTime() - today.getTime()) / 86400000);
}

function label(isoDate: string): string {
  const n = daysUntil(isoDate);
  if (n < 0) return "Your GRE date has passed — set a new one";
  if (n === 0) return "🎯 GRE day is today — you've got this";
  if (n === 1) return "🔥 1 day until your GRE";
  return `🔥 ${n} days until your GRE`;
}

export default function ExamCountdown({ userId, examDate, onChange }: Props) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(examDate ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(next: string | null) {
    setSaving(true);
    setError(null);
    try {
      const r = await putJSON<{ exam_date: string | null }>(
        `/user/${userId}/exam-date`,
        { exam_date: next }
      );
      onChange(r.exam_date);
      setValue(r.exam_date ?? "");
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <div className="flex items-center gap-3 text-gray-500">
        {examDate ? (
          <span className="font-medium text-gray-700">{label(examDate)}</span>
        ) : (
          <span>Set your GRE date to track a countdown</span>
        )}
        <button
          onClick={() => { setValue(examDate ?? ""); setEditing(true); }}
          className="text-sm text-indigo-600 hover:text-indigo-700"
        >
          {examDate ? "Edit" : "Set date"}
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        type="date"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none"
      />
      <button
        onClick={() => value && save(value)}
        disabled={saving || !value}
        className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40 hover:bg-indigo-700"
      >
        {saving ? "…" : "Save"}
      </button>
      <button
        onClick={() => { setEditing(false); setError(null); }}
        className="text-sm text-gray-500 hover:text-gray-700"
      >
        Cancel
      </button>
      {examDate && (
        <button
          onClick={() => save(null)}
          disabled={saving}
          className="text-sm text-red-500 hover:text-red-600"
        >
          Clear
        </button>
      )}
      {error && <span className="text-sm text-red-600">{error}</span>}
    </div>
  );
}
