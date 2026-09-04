export interface Product {
  id: number;
  sku: string;
  name: string;
  brand: string;
  category: string;
  // Always the list price. What a buyer pays is effective_price_paise below.
  price_paise: number;
  price_display: string;
  // None = no active discount, set via the merchant dashboard.
  discount_pct: number | null;
  effective_price_paise: number;
  effective_price_display: string;
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

export interface ProductSuggestion {
  sku: string;
  name: string;
  unit: string;
  price_paise: number;
  price_display: string;
  stock: number;
  within_budget: boolean;
  note: string;
}

export interface AgentChatResponse {
  reply: string;
  status: "completed" | "awaiting_confirmation" | "iteration_limit";
  pending: PendingAction | null;
  cart: Cart;
  payment: PaymentInfo | null;
  upsell: UpsellOffer | null;
  product_suggestion: ProductSuggestion | null;
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
  // Client-side only (Date.now() at push time) — purely for display, never
  // sent to or received from the backend.
  timestamp: number;
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

export interface AuditSessionSummary {
  session_id: string;
  user_email: string;
  status: string;
  created_at: string;
  updated_at: string;
  event_count: number;
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
  type: "buyer" | "merchant" | "agent" | "pending";
  user_id: string;
  email: string | null;
  role: "BUYER" | "MERCHANT" | null;
  credential_id: string | null;
}

export interface RoleChoiceResult {
  role: string;
  token: string;
}

export interface DemoPrincipalOption {
  role: "BUYER" | "MERCHANT";
  email: string;
  name: string;
  description: string;
}

export interface DemoLoginOptions {
  available: boolean;
  principals: DemoPrincipalOption[];
}

export interface DemoLoginResult {
  token: string;
  user_id: string;
  email: string;
  role: string;
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

// --- Layer 4.8: buyer dashboard ---

export interface AgentSummaryLite {
  id: string;
  name: string;
  status: string;
  delivery_mode: string;
}

export interface OrderSummary {
  id: number;
  amount_paise: number;
  status: string;
  created_at: string;
}

export interface DashboardSummary {
  agent: AgentSummaryLite | null;
  agent_count: number;
  recent_orders: OrderSummary[];
  cart: Cart;
}

// --- Layer 5b: orders (buyer + merchant) ---

export interface OrderListItem {
  id: number;
  status: string;
  amount_paise: number;
  created_at: string;
  item_count: number;
  buyer_email: string | null;
}

export interface OrderItem {
  sku: string;
  name: string;
  quantity: number;
  unit_price_paise: number;
  line_total_paise: number;
}

export interface OrderDetail {
  id: number;
  status: string;
  amount_paise: number;
  currency: string;
  created_at: string;
  updated_at: string;
  items: OrderItem[];
  razorpay_payment_id: string | null;
  failure_code: string | null;
  failure_description: string | null;
  buyer_email: string;
}

// --- Layer 4.8: merchant dashboard ---

export interface MerchantNotification {
  id: number;
  created_at: string;
  type: "UNMET_DEMAND" | "OUT_OF_STOCK_DEMAND" | "BROWSE_ABANDONMENT" | "ATTRIBUTE_GAP";
  evidence: Record<string, unknown>;
  suggested_action: string;
  status: "NEW" | "ACTED" | "DISMISSED";
  acted_at: string | null;
  dismissed_at: string | null;
  conversions_since_acted: number;
  purchases_since_acted: number;
  revenue_since_acted_paise: number;
}

export interface MerchantProductRow {
  sku: string;
  name: string;
  category: string;
  price_paise: number;
  discount_pct: number | null;
  effective_price_paise: number;
  stock: number;
  is_out_of_stock: boolean;
}

export interface HeadlineNumbers {
  queries_received: number;
  match_rate: number;
  unmet_demand_count: number;
  upsell_revenue_paise: number;
  campaign_net_margin_impact_paise: number;
}
