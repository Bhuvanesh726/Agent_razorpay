"use client";

import { createContext, useContext } from "react";

// This backend's own session JWT — entirely separate from Google's tokens,
// which never leave the backend (see backend/app/auth/oauth_router.py).
const TOKEN_STORAGE_KEY = "razorpay-agent-jwt";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8842";

export interface AuthUser {
  type: "buyer" | "merchant" | "agent";
  user_id: string;
  email: string | null;
  role: "BUYER" | "MERCHANT" | null;
  credential_id: string | null;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    // Storage unavailable (private browsing, disabled) — the session just
    // won't persist across reloads, not worth surfacing as an error.
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // ignore
  }
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function googleLoginUrl(): string {
  return `${API_URL}/api/auth/google/login`;
}

export interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue>({
  user: null,
  loading: true,
  logout: () => {},
});

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}
