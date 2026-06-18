"use client";

import { clearUser } from "@/lib/auth";

// Small identity chip + logout, shown in each page's top bar so a tester can
// see who they're signed in as and switch to a fresh profile.
export default function UserBadge({ username }: { username: string }) {
  function logout() {
    clearUser();
    window.location.href = "/login";
  }
  return (
    <div className="flex items-center gap-2 text-sm text-gray-500">
      <span>👤 {username}</span>
      <button onClick={logout} className="text-indigo-600 hover:text-indigo-700">
        Log out
      </button>
    </div>
  );
}
