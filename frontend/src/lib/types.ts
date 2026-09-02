export interface Product {
  id: number;
  sku: string;
  name: string;
  brand: string;
  category: string;
  price_paise: number;
  price_display: string;
  unit: string;
  stock: number;
  description: string;
  tags: string[];
}

export interface ProductListResponse {
  items: Product[];
  total: number;
  page: number;
  page_size: number;
}

export interface Category {
  category: string;
  product_count: number;
}

export interface CartItem {
  id: number;
  product_id: number;
  sku: string;
  name: string;
  quantity: number;
  unit_price_paise: number;
  unit_price_display: string;
  line_total_paise: number;
  line_total_display: string;
}

export interface Cart {
  id: number;
  user_id: string;
  status: string;
  created_at: string;
  items: CartItem[];
  total_paise: number;
  total_display: string;
}

export interface PendingAction {
  tool_name: string | null;
  arguments: Record<string, unknown> | null;
  rule_name: string | null;
  reason: string | null;
}

export interface AgentChatResponse {
  reply: string;
  status: "completed" | "awaiting_confirmation" | "iteration_limit";
  pending: PendingAction | null;
  cart: Cart;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
}

export interface AuditEvent {
  id: number;
  session_id: string;
  user_id: string;
  timestamp: string;
  event_type: string;
  actor: "user" | "agent" | "policy" | "system";
  tool_name: string | null;
  tool_args: Record<string, unknown> | null;
  decision: "ALLOW" | "DENY" | "REQUIRE_CONFIRMATION" | null;
  rule_name: string | null;
  reason: string | null;
  model_used: string | null;
  latency_ms: number | null;
  request_id: string | null;
}
