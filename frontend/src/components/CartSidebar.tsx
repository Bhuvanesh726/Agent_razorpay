import { ShoppingBag, X } from "lucide-react";
import type { Cart } from "@/lib/types";
import Button from "@/components/ui/Button";

interface Props {
  cart: Cart | null;
  onRemove: (itemId: number) => void;
  removingId: number | null;
  onBuyNow: () => void;
  buyingNow: boolean;
}

export default function CartSidebar({ cart, onRemove, removingId, onBuyNow, buyingNow }: Props) {
  const hasItems = !!cart && cart.items.length > 0;

  return (
    <aside className="flex h-fit flex-col gap-3 rounded-lg border border-line bg-surface p-4 lg:sticky lg:top-[4.5rem]">
      <h2 className="text-sm font-semibold tracking-tight text-ink">Cart</h2>

      {!hasItems ? (
        <div className="flex flex-col items-center gap-1.5 py-6 text-center">
          <ShoppingBag size={20} className="text-ink-faint" strokeWidth={1.5} />
          <p className="text-sm text-ink-soft">Your cart is empty</p>
        </div>
      ) : (
        <ul className="flex flex-col divide-y divide-line">
          {cart.items.map((item) => (
            <li key={item.id} className="flex items-start justify-between gap-3 py-3 first:pt-0 last:pb-0">
              <div className="min-w-0">
                <p className="text-sm font-medium leading-snug text-ink">{item.name}</p>
                <p className="mt-0.5 font-mono text-xs tabular-nums text-ink-faint">
                  Qty {item.quantity} · {item.unit_price_display}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <span className="font-mono text-sm tabular-nums text-ink">{item.line_total_display}</span>
                <button
                  onClick={() => onRemove(item.id)}
                  disabled={removingId === item.id}
                  aria-label={`Remove ${item.name}`}
                  className="rounded-md p-1 text-ink-faint transition-colors duration-150 hover:bg-danger-soft hover:text-danger disabled:opacity-40"
                >
                  <X size={14} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="flex items-center justify-between border-t border-line pt-3 text-sm font-semibold text-ink">
        <span>Total</span>
        <span className="font-mono tabular-nums">{cart?.total_display ?? "₹0.00"}</span>
      </div>

      {hasItems && (
        <Button variant="primary" onClick={onBuyNow} disabled={buyingNow} className="w-full">
          {buyingNow ? "Starting checkout…" : "Buy Now"}
        </Button>
      )}
    </aside>
  );
}
