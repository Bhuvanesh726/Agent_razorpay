import { ButtonHTMLAttributes, forwardRef } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "destructive";
export type ButtonSize = "sm" | "md";

const BASE =
  "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-40";

const VARIANT_STYLES: Record<ButtonVariant, string> = {
  primary: "bg-ink text-white hover:bg-accent",
  secondary: "border border-line bg-surface text-ink hover:border-line-strong hover:bg-black/[0.02]",
  ghost: "text-ink-soft hover:bg-black/[0.04] hover:text-ink",
  destructive: "border border-danger/25 bg-danger-soft text-danger hover:bg-danger/10",
};

const SIZE_STYLES: Record<ButtonSize, string> = {
  sm: "px-2.5 py-1.5 text-xs",
  md: "px-3.5 py-2 text-sm",
};

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

const Button = forwardRef<HTMLButtonElement, Props>(
  ({ variant = "secondary", size = "md", className = "", ...props }, ref) => (
    <button
      ref={ref}
      className={`${BASE} ${VARIANT_STYLES[variant]} ${SIZE_STYLES[size]} ${className}`}
      {...props}
    />
  )
);
Button.displayName = "Button";

export default Button;
