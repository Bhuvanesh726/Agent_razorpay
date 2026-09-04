"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
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

  if (!user || user.type === "agent") return null;
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
    <div className="flex items-center gap-2">
      <span className="rounded bg-black/[0.05] px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide text-ink-faint">
        Dev
      </span>
      <button
        onClick={switchRole}
        disabled={busy}
        title="Dev-only: demo both sides without two Google accounts"
        className="inline-flex items-center gap-1.5 rounded-full bg-warning-soft px-3 py-1.5 text-xs font-medium text-warning transition-colors duration-150 hover:bg-warning/15 disabled:opacity-40"
      >
        <RefreshCw size={12} className={busy ? "animate-spin" : ""} />
        {busy ? "Switching…" : `Switch to ${target === "BUYER" ? "buyer" : "merchant"} view`}
      </button>
      {error && <span className="text-xs text-danger">{error}</span>}
    </div>
  );
}
