import type { Cart } from "@/lib/types";

interface Props {
  cart: Cart | null;
  onRemove: (itemId: number) => void;
  removingId: number | null;
}

export default function CartSidebar({ cart, onRemove, removingId }: Props) {
  return (
    <aside className="flex h-fit flex-col gap-3 rounded-lg border border-gray-200 p-4 lg:sticky lg:top-4">
      <h2 className="font-semibold">Cart</h2>

      {!cart || cart.items.length === 0 ? (
        <p className="text-sm text-gray-500">Your cart is empty.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {cart.items.map((item) => (
            <li key={item.id} className="flex items-start justify-between gap-2 text-sm">
              <div>
                <p className="font-medium leading-snug">{item.name}</p>
                <p className="text-gray-500">
                  {item.quantity} × {item.unit_price_display} = {item.line_total_display}
                </p>
              </div>
              <button
                onClick={() => onRemove(item.id)}
                disabled={removingId === item.id}
                className="text-xs text-gray-400 hover:text-red-600 disabled:opacity-40"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex items-center justify-between border-t border-gray-200 pt-3 font-semibold">
        <span>Total</span>
        <span>{cart?.total_display ?? "₹0.00"}</span>
      </div>
    </aside>
  );
}
