"use client";

import { useEffect, useState } from "react";
import { fetchMe } from "@/lib/api";
import { AuthContext, AuthUser, clearToken, getToken } from "@/lib/auth";

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setLoading(false);
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

  return <AuthContext.Provider value={{ user, loading, logout }}>{children}</AuthContext.Provider>;
}
