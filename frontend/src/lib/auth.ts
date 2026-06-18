"use client";

// Client-side auth state. The backend returns {user_id, username} on login/signup;
// we persist it in localStorage and key every API call off user_id. This is a
// lightweight tester identity (not a hardened session) — enough to keep fresh and
// returning progress separate.

import { useEffect, useState } from "react";

export interface AuthUser {
  user_id: string;
  username: string;
}

const KEY = "lexis_user";

export function getUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

export function setUser(u: AuthUser): void {
  localStorage.setItem(KEY, JSON.stringify(u));
}

export function clearUser(): void {
  localStorage.removeItem(KEY);
}

// Guard a page: returns the user once known, or redirects to /login if not signed in.
export function useAuth(): { user: AuthUser | null; ready: boolean } {
  const [user, setUserState] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const u = getUser();
    if (!u) {
      window.location.href = "/login";
      return;
    }
    setUserState(u);
    setReady(true);
  }, []);

  return { user, ready };
}
