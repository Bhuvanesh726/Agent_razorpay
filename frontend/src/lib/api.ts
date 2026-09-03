import type {
  AgentChatResponse,
  AgentCreateRequest,
  AgentCreateResponse,
  AgentDetail,
  AgentSummary,
  AuditTrail,
  CampaignDetail,
  CampaignSummary,
  Cart,
  Category,
  ContentGap,
  MeResponse,
  PaymentResult,
  ProductListResponse,
  Segment,
  SessionReplay,
} from "./types";
import { authHeaders } from "./auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8842";

const REQUEST_TIMEOUT_MS = 8000;
// The agent loop can make several sequential model calls (with retries/fallback)
// before responding — a plain product/cart request has no reason to take this long.
const AGENT_REQUEST_TIMEOUT_MS = 120_000;

async function request<T>(path: string, init?: RequestInit, timeoutMs: number = REQUEST_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  // Sent on every request, not just the ones that strictly need it — public
  // endpoints (products, catalog feed) simply ignore it, and this keeps
  // every call site below from having to remember auth individually.
  const headers = { ...authHeaders(), ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers };

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers,
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

export function fetchSessionReplay(sessionId: string): Promise<SessionReplay> {
  return request<SessionReplay>(`/api/audit/${sessionId}/replay`);
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

export function logProductView(sku: string, sessionId: string | null): Promise<void> {
  // Fire-and-forget by contract: the backend endpoint is best-effort and
  // never errors, but a network failure (offline, blocked request) could
  // still reject the fetch — swallow it here too, since a page render or
  // a click must never wait on or break over a view-logging call.
  return request<void>(`/api/products/${encodeURIComponent(sku)}/view`, {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId }),
  }).catch(() => undefined);
}

export function fetchContentGaps(): Promise<ContentGap[]> {
  return request("/api/campaigns/content-gaps");
}

export function fetchSegments(): Promise<Segment[]> {
  return request<Segment[]>("/api/campaigns/segments");
}

export function fetchCampaigns(): Promise<CampaignSummary[]> {
  return request<CampaignSummary[]>("/api/campaigns");
}

export function fetchCampaign(campaignId: string): Promise<CampaignDetail> {
  return request<CampaignDetail>(`/api/campaigns/${campaignId}`);
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

export function fetchMe(): Promise<MeResponse> {
  return request<MeResponse>("/api/auth/me");
}

export function fetchAgents(): Promise<AgentSummary[]> {
  return request<AgentSummary[]>("/api/agents");
}

export function fetchAgent(credentialId: string): Promise<AgentDetail> {
  return request<AgentDetail>(`/api/agents/${credentialId}`);
}

export function createAgent(payload: AgentCreateRequest): Promise<AgentCreateResponse> {
  return request<AgentCreateResponse>("/api/agents", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function revokeAgent(credentialId: string): Promise<AgentSummary> {
  return request<AgentSummary>(`/api/agents/${credentialId}/revoke`, { method: "POST" });
}

export function runAgent(credentialId: string): Promise<{ reply: string; status: string; cart: Cart }> {
  return request(`/api/agents/${credentialId}/run`, { method: "POST" }, AGENT_REQUEST_TIMEOUT_MS);
}
