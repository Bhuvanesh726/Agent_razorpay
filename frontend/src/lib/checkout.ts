import { reportPaymentFailed, verifyPayment } from "@/lib/api";
import type { PaymentInfo, PaymentResult } from "@/lib/types";

// Shared between the chat-driven payment flow (ChatPanel) and the manual
// "Buy Now" flow (CartSidebar / page.tsx) — same Razorpay Checkout wiring
// either way, just triggered from a different place.

interface RazorpaySuccessResponse {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

interface RazorpayFailureResponse {
  error: { code?: string; description?: string };
}

interface RazorpayInstance {
  on(event: "payment.failed", handler: (response: RazorpayFailureResponse) => void): void;
  open(): void;
}

interface RazorpayOptions {
  key: string;
  amount: number;
  currency: string;
  order_id: string;
  name: string;
  description?: string;
  handler: (response: RazorpaySuccessResponse) => void;
  modal?: { ondismiss?: () => void };
}

declare global {
  interface Window {
    Razorpay?: new (options: RazorpayOptions) => RazorpayInstance;
  }
}

export interface CheckoutHandlers {
  onSuccess: (result: PaymentResult) => void;
  onFailure: (result: PaymentResult) => void;
  onDismiss: () => void;
  onUnavailable: () => void;
  onError: (message: string) => void;
}

export function openRazorpayCheckout(payment: PaymentInfo, description: string, handlers: CheckoutHandlers): void {
  if (!window.Razorpay) {
    handlers.onUnavailable();
    return;
  }

  const rzp = new window.Razorpay({
    key: payment.razorpay_key_id,
    amount: payment.amount_paise,
    currency: payment.currency,
    order_id: payment.razorpay_order_id,
    name: "Razorpay Shop (test mode)",
    description,
    handler: async (response) => {
      try {
        const result = await verifyPayment(
          response.razorpay_order_id,
          response.razorpay_payment_id,
          response.razorpay_signature
        );
        if (result.status === "PAID") handlers.onSuccess(result);
        else handlers.onFailure(result);
      } catch (e) {
        handlers.onError(e instanceof Error ? e.message : String(e));
      }
    },
    modal: {
      ondismiss: handlers.onDismiss,
    },
  });

  rzp.on("payment.failed", async (response) => {
    try {
      const result = await reportPaymentFailed(
        payment.razorpay_order_id,
        response.error?.code,
        response.error?.description
      );
      handlers.onFailure(result);
    } catch (e) {
      handlers.onError(e instanceof Error ? e.message : String(e));
    }
  });

  rzp.open();
}

const SESSION_STORAGE_KEY = "razorpay-agent-session-id";
const AGENT_SESSION_STORAGE_PREFIX = "razorpay-agent-session-id:";

export function getOrCreateSessionId(): string {
  if (typeof window === "undefined") return "";
  try {
    const existing = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (existing) return existing;
    const created = crypto.randomUUID();
    window.localStorage.setItem(SESSION_STORAGE_KEY, created);
    return created;
  } catch {
    return crypto.randomUUID();
  }
}

// One conversation per (buyer, agent credential) — a session id is tied to
// a single AgentCredential's own scopes/spend limit for its whole
// lifetime, so switching agents must never reuse another agent's session.
export function getOrCreateAgentSessionId(credentialId: string): string {
  if (typeof window === "undefined") return "";
  const key = AGENT_SESSION_STORAGE_PREFIX + credentialId;
  try {
    const existing = window.localStorage.getItem(key);
    if (existing) return existing;
    const created = crypto.randomUUID();
    window.localStorage.setItem(key, created);
    return created;
  } catch {
    return crypto.randomUUID();
  }
}

// Layer 7: start a fresh conversation with the same agent. Without this the
// session id above is sticky for the lifetime of the browser profile, so an
// agent could only ever have one conversation and the history list could
// never hold a second row.
export function startNewAgentSessionId(credentialId: string): string {
  const created = crypto.randomUUID();
  setActiveAgentSessionId(credentialId, created);
  return created;
}

// Layer 7: opening a past conversation makes it the active one for this
// agent, so a reload resumes where the buyer left off instead of silently
// dropping them back into the newest session.
export function setActiveAgentSessionId(credentialId: string, sessionId: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(AGENT_SESSION_STORAGE_PREFIX + credentialId, sessionId);
  } catch {
    // Storage unavailable — the session is still active in memory for this
    // tab, it just won't survive a reload. Not worth surfacing.
  }
}

// Every chat session id is browser-scoped (localStorage), not user-scoped —
// if the JWT changes to a different signed-in principal (a fresh login, a
// different account on the same browser) while a stale session id from the
// previous principal is still stored, the backend's ownership check on
// that AgentSession row rejects the very first message with "This session
// belongs to a different principal." Call this whenever the identity behind
// the token changes, so fresh session ids are minted for the new principal
// — sweeps both the bare key and every per-agent-credential key.
export function clearSessionId(): void {
  try {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    const staleKeys: string[] = [];
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      if (key && key.startsWith(AGENT_SESSION_STORAGE_PREFIX)) staleKeys.push(key);
    }
    for (const key of staleKeys) window.localStorage.removeItem(key);
  } catch {
    // ignore
  }
}
