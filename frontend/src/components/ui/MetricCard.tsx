/** label -> number-as-hero -> muted meta description. The number is the
 * visually dominant element, set in Geist Mono with tabular figures so a
 * row of these never has misaligned digits. */
interface Props {
  label: string;
  value: string;
  meta?: string;
  tone?: "default" | "success" | "danger";
}

const TONE_STYLES: Record<NonNullable<Props["tone"]>, string> = {
  default: "text-ink",
  success: "text-success",
  danger: "text-danger",
};

export default function MetricCard({ label, value, meta, tone = "default" }: Props) {
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-line bg-surface p-4">
      <span className="text-xs font-medium uppercase tracking-wide text-ink-faint">{label}</span>
      <span className={`font-mono text-2xl font-semibold tabular-nums leading-none ${TONE_STYLES[tone]}`}>{value}</span>
      {meta && <span className="text-xs text-ink-soft">{meta}</span>}
    </div>
  );
}
