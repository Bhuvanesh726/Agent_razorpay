"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { quickBuy } from "@/lib/api";
import { openRazorpayCheckout } from "@/lib/checkout";
import type { ProductSuggestion } from "@/lib/types";
import Button from "@/components/ui/Button";

interface Props {
  suggestion: ProductSuggestion;
  credentialId: string;
  sessionId: string;
  onSuccess: (message: string) => void;
  onFailure: (message: string) => void;
}

export default function ProductSuggestionCard({ suggestion, credentialId, sessionId, onSuccess, onFailure }: Props) {
  const [buying, setBuying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleConfirm() {
    setBuying(true);
    setError(null);
    try {
      const payment = await quickBuy(credentialId, sessionId, suggestion.sku, 1);
      if (payment.status === "PAID") {
        // The agent completed it within its granted spend limit — there is no
        // checkout left for a human to drive. Worded to match reality: the
        // Razorpay order is real, the capture is a local test-mode stand-in
        // (see docs/PAYMENT-REALITY.md), so this must not claim a settled payment.
        onSuccess(
          `Order #${payment.order_id} placed — ₹${(payment.amount_paise / 100).toFixed(2)}. ` +
            "(Test mode: capture simulated locally.)"
        );
        setBuying(false);
        return;
      }
      openRazorpayCheckout(payment, suggestion.name, {
        onSuccess: (result) => {
          onSuccess(result.message);
          setBuying(false);
        },
        onFailure: (result) => {
          onFailure(result.message);
          setBuying(false);
        },
        onDismiss: () => setBuying(false),
        onUnavailable: () => {
          setError("Razorpay Checkout hasn't loaded yet — please try again in a moment.");
          setBuying(false);
        },
        onError: (message) => {
          setError(message);
          setBuying(false);
        },
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBuying(false);
    }
  }

  const withinBudget = suggestion.within_budget;
  const Icon = withinBudget ? CheckCircle2 : AlertTriangle;
  const toneClass = withinBudget ? "border-success/25 bg-success-soft" : "border-warning/25 bg-warning-soft";
  const iconClass = withinBudget ? "text-success" : "text-warning";
  const outOfStock = suggestion.stock === 0;

  return (
    <div className={`rounded-lg border p-3.5 text-sm ${toneClass}`}>
      <div className="flex items-start gap-2">
        <Icon size={16} className={`mt-0.5 shrink-0 ${iconClass}`} />
        <div className="min-w-0 flex-1">
          <p className="font-medium text-ink">{suggestion.name}</p>
          <p className="text-xs text-ink-soft">{suggestion.unit}</p>
          <p className="mt-1.5 font-mono text-base font-semibold tabular-nums text-ink">{suggestion.price_display}</p>
          <p className={`mt-1 ${iconClass}`}>{suggestion.note}</p>
          {outOfStock && <p className="mt-1 text-xs font-medium text-danger">Out of stock right now.</p>}
        </div>
      </div>

      {error && (
        <div className="mt-2.5 rounded-md border border-danger/25 bg-danger-soft px-2.5 py-1.5 text-xs text-danger">
          {error}
        </div>
      )}

      <Button variant="primary" size="sm" onClick={handleConfirm} disabled={buying || outOfStock} className="mt-3 w-full">
        {buying ? "Starting checkout…" : "Confirm & Buy"}
      </Button>
    </div>
  );
}
