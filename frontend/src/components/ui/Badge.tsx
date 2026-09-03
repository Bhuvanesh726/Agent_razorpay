/**
 * Status pills, one place. `statusVariant` maps every status/decision
 * string this app actually produces to one of four restrained,
 * muted-not-saturated tones — used for meaning (a denial, a warning),
 * never as decoration. `humanize` turns a raw enum value like
 * "blocked_at_segment" or "REQUIRE_CONFIRMATION" into "Blocked at segment" /
 * "Requires confirmation" so no page ever prints a raw lowercase/
 * SCREAMING_SNAKE token straight from the API.
 */

export type BadgeVariant = "neutral" | "success" | "danger" | "warning" | "accent";

const VARIANT_STYLES: Record<BadgeVariant, string> = {
  neutral: "bg-black/[0.04] text-ink-soft",
  success: "bg-success-soft text-success",
  danger: "bg-danger-soft text-danger",
  warning: "bg-warning-soft text-warning",
  accent: "bg-accent-soft text-accent",
};

const KNOWN_STATUS_VARIANTS: Record<string, BadgeVariant> = {
  ALLOW: "success",
  MATCHED: "success",
  ACTIVE: "success",
  PAID: "success",
  COMPLETED: "success",
  ACTED: "success",
  IN_STOCK: "success",

  DENY: "danger",
  FAILED: "danger",
  REVOKED: "danger",
  BLOCKED_AT_SEGMENT: "danger",
  OUT_OF_STOCK: "danger",
  NO_MATCH: "danger",
  DISMISSED: "neutral",

  REQUIRE_CONFIRMATION: "warning",
  AWAITING_CONFIRMATION: "warning",
  PENDING: "warning",
  NEW: "warning",
  BLOCKED_BY_POLICY: "warning",
};

export function humanize(value: string): string {
  const spaced = value.replace(/[_-]+/g, " ").trim();
  if (spaced === spaced.toUpperCase() || spaced === spaced.toLowerCase()) {
    // SCREAMING_SNAKE_CASE or all-lowercase enum values (one word or
    // several — "blocked_at_segment" included): sentence-case them.
    const lower = spaced.toLowerCase();
    return lower.charAt(0).toUpperCase() + lower.slice(1);
  }
  return spaced;
}

export function statusVariant(status: string): BadgeVariant {
  return KNOWN_STATUS_VARIANTS[status.toUpperCase()] ?? "neutral";
}

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  className?: string;
}

export function Badge({ children, variant = "neutral", className = "" }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium leading-5 ${VARIANT_STYLES[variant]} ${className}`}
    >
      {children}
    </span>
  );
}

/** Convenience wrapper: pass a raw status/decision string, get a badge
 * with the right tone and a humanized label in one call. */
export function StatusBadge({ status, className = "" }: { status: string | null | undefined; className?: string }) {
  if (!status) return <span className="text-ink-faint">—</span>;
  return (
    <Badge variant={statusVariant(status)} className={className}>
      {humanize(status)}
    </Badge>
  );
}
