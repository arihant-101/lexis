"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import UserBadge from "@/components/UserBadge";
import ExamCountdown from "@/components/ExamCountdown";

interface DashboardData {
  stats: {
    total_words_seen?: number;
    words_seen?: number;
    mastered: number;
    familiar: number;
    learning: number;
    due_today?: number;
    avg_accuracy?: number;
    accuracy?: number;
  };
  due_today: string[];
  due_count: number;
  exam_date: string | null;
}

export default function Dashboard() {
  const { user, ready } = useAuth();
  const [data, setData] = useState<DashboardData | null>(null);

  useEffect(() => {
    if (!user) return;
    fetch(`/api/user/${user.user_id}/dashboard`)
      .then((r) => r.json())
      .then(setData);
  }, [user]);

  if (!ready || !data) return <div className="p-8 text-gray-500">Loading...</div>;

  const { stats, due_count } = data;
  const totalWordsSeen = stats.total_words_seen ?? stats.words_seen ?? 0;
  const accuracy = stats.avg_accuracy ?? stats.accuracy ?? 0;

  return (
    <main className="min-h-screen bg-gray-50 p-8">
      <div className="flex justify-end mb-4">
        <UserBadge username={user!.username} />
      </div>
      <h1 className="text-3xl font-bold text-gray-900 mb-2">Good morning 👋</h1>
      <div className="mb-8">
        <ExamCountdown
          userId={user!.user_id}
          examDate={data.exam_date}
          onChange={(next) => setData({ ...data, exam_date: next })}
        />
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        {[
          { label: "Due today",  value: due_count,              color: "bg-orange-100 text-orange-700" },
          { label: "Mastered",   value: stats.mastered,         color: "bg-green-100 text-green-700"  },
          { label: "Learning",   value: stats.learning,         color: "bg-blue-100 text-blue-700"    },
          { label: "Accuracy",   value: `${Math.round(accuracy * 100)}%`,
                                                                 color: "bg-purple-100 text-purple-700"},
        ].map(({ label, value, color }) => (
          <div key={label} className={`rounded-xl p-4 ${color}`}>
            <div className="text-2xl font-bold">{value}</div>
            <div className="text-sm">{label}</div>
          </div>
        ))}
      </div>

      {/* Progress bar */}
      <div className="bg-white rounded-xl p-6 mb-6 shadow-sm">
        <div className="flex justify-between text-sm text-gray-500 mb-2">
          <span>Vocabulary progress</span>
          <span>{totalWordsSeen} / 3500 words</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-3">
          <div
            className="bg-indigo-500 h-3 rounded-full transition-all"
            style={{ width: `${(totalWordsSeen / 3500) * 100}%` }}
          />
        </div>
      </div>

      {/* CTA buttons */}
      <div className="flex gap-4">
        <a
          href="/coach"
          className="flex-1 bg-indigo-600 text-white text-center py-4 rounded-xl font-semibold hover:bg-indigo-700 transition"
        >
          🧑‍🏫 Coach me
        </a>
        <a
          href="/learn"
          className="flex-1 bg-white border border-gray-200 text-gray-700 text-center py-4 rounded-xl font-semibold hover:bg-gray-50 transition"
        >
          Study today's words ({due_count})
        </a>
        <a
          href="/practice"
          className="flex-1 bg-white border border-gray-200 text-gray-700 text-center py-4 rounded-xl font-semibold hover:bg-gray-50 transition"
        >
          Self-practice
        </a>
      </div>
    </main>
  );
}
