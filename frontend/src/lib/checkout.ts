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
