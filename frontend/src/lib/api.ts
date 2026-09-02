import type { AgentChatResponse, AuditTrail, Cart, Category, PaymentResult, ProductListResponse } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8842";

const REQUEST_TIMEOUT_MS = 8000;
// The agent loop can make several sequential model calls (with retries/fallback)
// before responding — a plain product/cart request has no reason to take this long.
const AGENT_REQUEST_TIMEOUT_MS = 120_000;

async function request<T>(path: string, init?: RequestInit, timeoutMs: number = REQUEST_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...(init?.body
        ? { ...init, headers: { "Content-Type": "application/json", ...init?.headers } }
        : init),
      signal: controller.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error(`Timed out reaching the API at ${API_URL}. Is the backend running?`);
    }
    throw new Error(`Could not reach the API at ${API_URL}. Is the backend running?`);
  } finally {
    clearTimeout(timeout);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request to ${path} failed with ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export interface ProductQuery {
  category?: string | null;
  search?: string;
  minPricePaise?: number;
  maxPricePaise?: number;
  page?: number;
  pageSize?: number;
}

export function fetchProducts(query: ProductQuery = {}): Promise<ProductListResponse> {
  const params = new URLSearchParams();
  if (query.category) params.set("category", query.category);
  if (query.search) params.set("search", query.search);
  if (query.minPricePaise != null) params.set("min_price_paise", String(query.minPricePaise));
  if (query.maxPricePaise != null) params.set("max_price_paise", String(query.maxPricePaise));
  params.set("page", String(query.page ?? 1));
  params.set("page_size", String(query.pageSize ?? 50));
  return request<ProductListResponse>(`/api/products?${params.toString()}`);
}

export function fetchCategories(): Promise<Category[]> {
  return request<Category[]>("/api/categories");
}

export function fetchCart(): Promise<Cart> {
  return request<Cart>("/api/cart");
}

export function addCartItem(sku: string, quantity = 1): Promise<Cart> {
  return request<Cart>("/api/cart/items", {
    method: "POST",
    body: JSON.stringify({ sku, quantity }),
  });
}

export function removeCartItem(itemId: number): Promise<Cart> {
  return request<Cart>(`/api/cart/items/${itemId}`, { method: "DELETE" });
}

export function sendAgentMessage(
  sessionId: string,
  message: string,
  budgetPaise?: number | null
): Promise<AgentChatResponse> {
  return request<AgentChatResponse>(
    "/api/agent/chat",
    {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, message, budget_paise: budgetPaise ?? null }),
    },
    AGENT_REQUEST_TIMEOUT_MS
  );
}

export function confirmPendingAction(sessionId: string, approve: boolean): Promise<AgentChatResponse> {
  return request<AgentChatResponse>(
    "/api/agent/confirm",
    { method: "POST", body: JSON.stringify({ session_id: sessionId, approve }) },
    AGENT_REQUEST_TIMEOUT_MS
  );
}

export function fetchAuditTrail(sessionId: string): Promise<AuditTrail> {
  return request<AuditTrail>(`/api/audit/${sessionId}`);
}

export function verifyPayment(
  razorpayOrderId: string,
  razorpayPaymentId: string,
  razorpaySignature: string
): Promise<PaymentResult> {
  return request<PaymentResult>("/api/payments/verify", {
    method: "POST",
    body: JSON.stringify({
      razorpay_order_id: razorpayOrderId,
      razorpay_payment_id: razorpayPaymentId,
      razorpay_signature: razorpaySignature,
    }),
  });
}

export function reportPaymentFailed(
  razorpayOrderId: string,
  errorCode?: string,
  errorDescription?: string
): Promise<PaymentResult> {
  return request<PaymentResult>("/api/payments/failed", {
    method: "POST",
    body: JSON.stringify({
      razorpay_order_id: razorpayOrderId,
      error_code: errorCode ?? null,
      error_description: errorDescription ?? null,
    }),
  });
}
