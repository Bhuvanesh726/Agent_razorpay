"use client";

import { useEffect, useState } from "react";
import { ShoppingCart, Store } from "lucide-react";
import { chooseRole } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const ROLES = [
  {
    role: "BUYER" as const,
    icon: ShoppingCart,
    title: "I'm shopping",
    description: "Browse the shop, chat with a shopping assistant, and create your own bounded agent.",
  },
  {
    role: "MERCHANT" as const,
    icon: Store,
    title: "I'm selling",
    description: "See demand signals, campaigns, and manage your catalog's price, discounts, and stock.",
  },
];

export default function OnboardingPage() {
  const { user, loading, applyNewToken } = useAuth();
  const [submitting, setSubmitting] = useState<"BUYER" | "MERCHANT" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [redirectTo, setRedirectTo] = useState<string | null>(null);

  useEffect(() => {
    if (loading) return;
    if (!user) {
      window.location.href = "/login";
      return;
    }
    // Already onboarded — nothing to pick, bounce to the right dashboard.
    if (user.type === "buyer") window.location.href = "/dashboard";
    if (user.type === "merchant") window.location.href = "/merchant";
  }, [loading, user]);

  useEffect(() => {
    if (redirectTo) window.location.href = redirectTo;
  }, [redirectTo]);

  async function pick(role: "BUYER" | "MERCHANT") {
    setSubmitting(role);
    setError(null);
    try {
      const result = await chooseRole(role);
      await applyNewToken(result.token);
      setRedirectTo(role === "BUYER" ? "/dashboard" : "/merchant");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSubmitting(null);
    }
  }

  if (loading || !user || user.type !== "pending") {
    return (
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-6 py-8">
        <div className="h-7 w-64 animate-pulse rounded-md bg-black/[0.05]" />
        <div className="h-4 w-48 animate-pulse rounded-md bg-black/[0.05]" />
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-[70vh] w-full max-w-2xl flex-col items-center justify-center gap-8 px-6 py-8 text-center">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">
          Welcome — how would you like to use this store?
        </h1>
        <p className="mt-2 text-sm text-ink-soft">One click, and you&rsquo;re in. You can&rsquo;t switch later.</p>
      </div>

      {error && (
        <div className="w-full rounded-lg border border-danger/25 bg-danger-soft px-3 py-2 text-left text-sm text-danger">
          {error}
        </div>
      )}

      <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-2">
        {ROLES.map(({ role, icon: Icon, title, description }) => (
          <button
            key={role}
            onClick={() => pick(role)}
            disabled={submitting !== null}
            className="flex flex-col items-center gap-2 rounded-lg border border-line bg-surface p-8 text-left transition-colors duration-150 hover:border-accent hover:bg-accent-soft/40 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-40"
          >
            <div className="mb-1 flex h-11 w-11 items-center justify-center rounded-full bg-accent-soft text-accent">
              <Icon size={20} strokeWidth={1.75} />
            </div>
            <span className="text-lg font-semibold text-ink">{title}</span>
            <span className="text-sm text-ink-soft">{description}</span>
            {submitting === role && <span className="text-xs text-ink-faint">Setting up…</span>}
          </button>
        ))}
      </div>
    </div>
  );
}
