/** Shared data-table primitives — campaigns, audit, merchant products all
 * use these instead of styling <table> ad hoc. Headers are uppercase,
 * small, letterspaced, muted; numeric columns pass `align="right"` and
 * render in tabular Geist Mono; rows get a hairline top border and a
 * hover tint, never zebra stripes. */

export function TableWrap({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`overflow-x-auto rounded-lg border border-line ${className}`}>{children}</div>;
}

export function Table({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <table className={`w-full border-collapse text-sm ${className}`}>{children}</table>;
}

export function THead({ children }: { children: React.ReactNode }) {
  return <thead className="bg-black/[0.015]">{children}</thead>;
}

export function Th({
  children,
  align = "left",
  className = "",
}: {
  children?: React.ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  return (
    <th
      className={`border-b border-line px-3 py-2.5 text-xs font-semibold uppercase tracking-wide text-ink-faint ${
        align === "right" ? "text-right" : "text-left"
      } ${className}`}
    >
      {children}
    </th>
  );
}

export function Tr({
  children,
  onClick,
  className = "",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  className?: string;
}) {
  return (
    <tr
      onClick={onClick}
      className={`border-t border-line first:border-t-0 ${onClick ? "cursor-pointer" : ""} hover:bg-black/[0.015] ${className}`}
    >
      {children}
    </tr>
  );
}

export function Td({
  children,
  align = "left",
  numeric = false,
  className = "",
  ...rest
}: {
  children?: React.ReactNode;
  align?: "left" | "right";
  numeric?: boolean;
  className?: string;
} & React.TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      className={`px-3 py-3 align-middle text-sm text-ink ${align === "right" ? "text-right" : "text-left"} ${
        numeric ? "font-mono tabular-nums" : ""
      } ${className}`}
      {...rest}
    >
      {children}
    </td>
  );
}
