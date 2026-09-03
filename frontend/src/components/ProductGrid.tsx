import { PackageSearch } from "lucide-react";
import type { Product } from "@/lib/types";
import Button from "@/components/ui/Button";
import EmptyState from "@/components/ui/EmptyState";
import { SkeletonCards } from "@/components/ui/Skeleton";

interface Props {
  products: Product[];
  onAdd: (sku: string) => void;
  onView: (product: Product) => void;
  addingSku: string | null;
  loading?: boolean;
}

export default function ProductGrid({ products, onAdd, onView, addingSku, loading = false }: Props) {
  if (loading) return <SkeletonCards count={8} className="sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" />;

  if (products.length === 0) {
    return (
      <EmptyState
        icon={PackageSearch}
        title="No products match your filters"
        description="Try a different search term, or clear the category filter."
      />
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {products.map((p) => (
        <div
          key={p.sku}
          className="flex flex-col justify-between rounded-lg border border-line bg-surface p-4 transition-colors duration-150 hover:border-line-strong"
        >
          <button onClick={() => onView(p)} className="text-left">
            <p className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">{p.brand}</p>
            <h3 className="mt-0.5 font-medium leading-snug text-ink hover:text-accent">{p.name}</h3>
            <p className="mt-1 text-xs text-ink-soft">{p.unit}</p>
            {p.discount_pct ? (
              <p className="mt-2 flex items-baseline gap-1.5">
                <span className="font-mono text-xs tabular-nums text-ink-faint line-through">{p.price_display}</span>
                <span className="font-mono text-lg font-semibold tabular-nums text-success">
                  {p.effective_price_display}
                </span>
                <span className="text-xs font-medium text-success">-{p.discount_pct}%</span>
              </p>
            ) : (
              <p className="mt-2 font-mono text-lg font-semibold tabular-nums text-ink">{p.price_display}</p>
            )}
            <p className="mt-0.5 text-xs text-ink-faint">{p.stock > 0 ? `${p.stock} in stock` : "Out of stock"}</p>
          </button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => onAdd(p.sku)}
            disabled={p.stock === 0 || addingSku === p.sku}
            className="mt-3 w-full"
          >
            {addingSku === p.sku ? "Adding…" : "Add to cart"}
          </Button>
        </div>
      ))}
    </div>
  );
}
