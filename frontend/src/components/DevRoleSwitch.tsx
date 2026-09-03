"use client";

import { useState } from "react";
import { devSwitchRole } from "@/lib/api";
import { useAuth } from "@/lib/auth";

// Dev-only — the backend gates the actual endpoint on APP_ENV=development
// (same pattern as X-Chaos-Fault and /api/payments/test-complete) and
// 404s outside it, so this control is harmless to leave rendered anywhere;
// it just stops working in a non-dev deployment.
export default function DevRoleSwitch() {
  const { user, applyNewToken } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!user || user.type === "pending" || user.type === "agent") return null;
  const target: "BUYER" | "MERCHANT" = user.type === "buyer" ? "MERCHANT" : "BUYER";

  async function switchRole() {
    setBusy(true);
    setError(null);
    try {
      const result = await devSwitchRole(target);
      await applyNewToken(result.token);
      window.location.href = target === "BUYER" ? "/dashboard" : "/merchant";
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-1.5">
      <button
        onClick={switchRole}
        disabled={busy}
        title="Dev-only: demo both sides without two Google accounts"
        className="rounded-md border border-dashed border-amber-400 px-2 py-1 text-xs text-amber-700 hover:bg-amber-50 disabled:opacity-40"
      >
        {busy ? "Switching…" : `Dev: switch to ${target === "BUYER" ? "buyer" : "merchant"}`}
      </button>
      {error && <span className="text-xs text-red-600">{error}</span>}
    </div>
  );
}
