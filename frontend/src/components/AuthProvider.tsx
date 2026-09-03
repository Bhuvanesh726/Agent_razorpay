"use client";

import { useEffect, useState } from "react";
import { fetchMe } from "@/lib/api";
import { AuthContext, AuthUser, clearToken, getToken, setToken } from "@/lib/auth";

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      // Deferred to a microtask, same reasoning as app/audit/page.tsx's
      // identical pattern: a setState call must not run synchronously
      // inside the effect body itself.
      Promise.resolve().then(() => setLoading(false));
      return;
    }
    fetchMe()
      .then(setUser)
      .catch(() => {
        // Expired or otherwise invalid — drop it rather than keep retrying
        // a token that will never succeed.
        clearToken();
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  function logout() {
    clearToken();
    setUser(null);
    window.location.href = "/";
  }

  async function applyNewToken(token: string) {
    setToken(token);
    const me = await fetchMe();
    setUser(me);
  }

  return <AuthContext.Provider value={{ user, loading, logout, applyNewToken }}>{children}</AuthContext.Provider>;
}
