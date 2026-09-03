"use client";

import { useEffect, useState } from "react";
import { chooseRole } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function OnboardingPage() {
  const { user, loading, applyNewToken } = useAuth();
  const [submitting, setSubmitting] = useState<"BUYER" | "MERCHANT" | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  async function pick(role: "BUYER" | "MERCHANT") {
    setSubmitting(role);
    setError(null);
    try {
      const result = await chooseRole(role);
      await applyNewToken(result.token);
      window.location.href = role === "BUYER" ? "/dashboard" : "/merchant";
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSubmitting(null);
    }
  }

  if (loading || !user || user.type !== "pending") {
    return <div className="p-6 text-sm text-gray-400">Loading…</div>;
  }

  return (
    <div className="mx-auto flex min-h-[70vh] w-full max-w-2xl flex-col items-center justify-center gap-8 p-6 text-center">
      <div>
        <h1 className="text-2xl font-semibold">Welcome — how would you like to use this store?</h1>
        <p className="mt-2 text-sm text-gray-500">One click, and you&rsquo;re in. You can&rsquo;t switch later.</p>
      </div>

      {error && (
        <div className="w-full rounded-md border border-red-300 bg-red-50 px-3 py-2 text-left text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-2">
        <button
          onClick={() => pick("BUYER")}
          disabled={submitting !== null}
          className="flex flex-col items-center gap-2 rounded-lg border border-gray-200 p-8 text-left hover:border-black disabled:opacity-40"
        >
          <span className="text-3xl">🛒</span>
          <span className="text-lg font-semibold">I&rsquo;m shopping</span>
          <span className="text-sm text-gray-500">
            Browse the shop, chat with a shopping assistant, and create your own bounded agent.
          </span>
          {submitting === "BUYER" && <span className="text-xs text-gray-400">Setting up…</span>}
        </button>

        <button
          onClick={() => pick("MERCHANT")}
          disabled={submitting !== null}
          className="flex flex-col items-center gap-2 rounded-lg border border-gray-200 p-8 text-left hover:border-black disabled:opacity-40"
        >
          <span className="text-3xl">🏪</span>
          <span className="text-lg font-semibold">I&rsquo;m selling</span>
          <span className="text-sm text-gray-500">
            See demand signals, campaigns, and manage your catalog's price, discounts, and stock.
          </span>
          {submitting === "MERCHANT" && <span className="text-xs text-gray-400">Setting up…</span>}
        </button>
      </div>
    </div>
  );
}
