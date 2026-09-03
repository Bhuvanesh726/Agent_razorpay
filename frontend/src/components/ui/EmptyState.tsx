import type { LucideIcon } from "lucide-react";

interface Props {
  icon?: LucideIcon;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}

/** A real empty state, not a grey one-liner: an icon, a plain-language
 * heading, a short description of what will show up here and when, and
 * an optional next action. Used for every list in the app that can be
 * legitimately empty. */
export default function EmptyState({ icon: Icon, title, description, action, className = "" }: Props) {
  return (
    <div className={`flex flex-col items-center gap-2 rounded-lg border border-line bg-surface px-6 py-14 text-center ${className}`}>
      {Icon && <Icon size={22} className="mb-1 text-ink-faint" strokeWidth={1.5} />}
      <p className="text-sm font-medium text-ink">{title}</p>
      {description && <p className="max-w-sm text-sm text-ink-soft">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
