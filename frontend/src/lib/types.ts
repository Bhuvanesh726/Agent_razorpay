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

export interface PaymentInfo {
  order_id: number;
  razorpay_order_id: string;
  amount_paise: number;
  currency: string;
  razorpay_key_id: string;
  status: string;
}

export interface UpsellOffer {
  sku: string;
  name: string;
  price_paise: number;
  reason: string;
}

export interface AgentChatResponse {
  reply: string;
  status: "completed" | "awaiting_confirmation" | "iteration_limit";
  pending: PendingAction | null;
  cart: Cart;
  payment: PaymentInfo | null;
  upsell: UpsellOffer | null;
}

export interface PaymentResult {
  status: "PAID" | "FAILED";
  order_id: number;
  razorpay_order_id: string | null;
  razorpay_payment_id: string | null;
  amount_paise: number;
  message: string;
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
  tool_result: Record<string, unknown> | null;
  decision: "ALLOW" | "DENY" | "REQUIRE_CONFIRMATION" | null;
  rule_name: string | null;
  reason: string | null;
  model_used: string | null;
  latency_ms: number | null;
  request_id: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  cost_paise: number | null;
  fallback_used: boolean | null;
}

export interface AuditTotals {
  total_model_calls: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  total_cost_paise: number;
  fallback_used_count: number;
  upsell_proposed_count: number;
  upsell_accepted_count: number;
  upsell_declined_count: number;
  upsell_blocked_count: number;
  upsell_incremental_revenue_paise: number;
}

export interface AuditTrail {
  session_id: string;
  events: AuditEvent[];
  totals: AuditTotals;
}

export interface SessionReplay {
  session_id: string;
  event_count: number;
  narrative: string[];
  final_cart: Cart | null;
  final_order_status: string | null;
}

export interface Segment {
  name: string;
  description: string;
  size: number;
}

export interface CampaignProposal {
  skus: string[];
  discount_pct: number;
  message: string;
  rationale: string;
}

export interface CampaignMeasurement {
  segment_size: number;
  offers_sent: number;
  offers_blocked: number;
  control_size: number;
  redemptions: number;
  treatment_revenue_paise: number;
  control_revenue_paise: number;
  control_conversion_rate: number;
  expected_baseline_revenue_paise: number;
  incremental_revenue_paise: number;
  discount_cost_paise: number;
  treatment_cogs_paise: number;
  expected_baseline_cogs_paise: number;
  net_margin_impact_paise: number;
}

export interface CampaignSummary {
  campaign_id: string;
  segment_name: string;
  status: string;
  created_at: string;
  proposal: CampaignProposal | null;
  measurement: CampaignMeasurement | null;
}

export interface CampaignOffer {
  customer_key: string;
  group: "treatment" | "control";
  decision: "ALLOW" | "DENY" | null;
  rule_name: string | null;
  reason: string | null;
  discount_pct: number | null;
  sku: string | null;
  redeemed: boolean;
  revenue_paise: number;
  cogs_paise: number;
}

export interface CampaignDetail extends CampaignSummary {
  offers: CampaignOffer[];
}

export interface ContentGap {
  sku: string;
  count: number;
  sample_questions: string[];
}

export interface MeResponse {
  type: "buyer" | "merchant" | "agent";
  user_id: string;
  email: string | null;
  role: "BUYER" | "MERCHANT" | null;
  credential_id: string | null;
}

export interface AgentCreateRequest {
  name: string;
  delivery_mode: "EMBEDDED" | "EXTERNAL";
  scopes: string[];
  spend_limit_paise: number;
  standing_instruction?: string | null;
}

export interface AgentSummary {
  id: string;
  name: string;
  delivery_mode: string;
  scopes: string[];
  spend_limit_paise: number;
  spent_paise: number;
  status: string;
  standing_instruction: string | null;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface AgentCreateResponse extends AgentSummary {
  // Populated exactly once, and only for delivery_mode "EXTERNAL" — see
  // docs/047-principals.md. Never present for EMBEDDED.
  key: string | null;
}

export interface AgentAction {
  timestamp: string;
  session_id: string;
  event_type: string;
  tool_name: string | null;
  decision: "ALLOW" | "DENY" | "REQUIRE_CONFIRMATION" | null;
  rule_name: string | null;
  reason: string | null;
}

export interface AgentDetail extends AgentSummary {
  recent_actions: AgentAction[];
}
