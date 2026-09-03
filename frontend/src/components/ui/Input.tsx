import { forwardRef, InputHTMLAttributes, TextareaHTMLAttributes } from "react";

const FIELD_BASE =
  "w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint transition-colors duration-150 focus:border-accent disabled:cursor-not-allowed disabled:bg-black/[0.03] disabled:text-ink-faint";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className = "", ...props }, ref) => <input ref={ref} className={`${FIELD_BASE} ${className}`} {...props} />
);
Input.displayName = "Input";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className = "", ...props }, ref) => <textarea ref={ref} className={`${FIELD_BASE} ${className}`} {...props} />
);
Textarea.displayName = "Textarea";

export function Label({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <span className={`text-sm font-medium text-ink ${className}`}>{children}</span>;
}
