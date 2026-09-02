import type { Product } from "@/lib/types";

interface Props {
  products: Product[];
  onAdd: (sku: string) => void;
  addingSku: string | null;
}

export default function ProductGrid({ products, onAdd, addingSku }: Props) {
  if (products.length === 0) {
    return <p className="text-sm text-gray-500">No products match your filters.</p>;
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {products.map((p) => (
        <div key={p.sku} className="flex flex-col justify-between rounded-lg border border-gray-200 p-4">
          <div>
            <p className="text-xs uppercase text-gray-400">{p.brand}</p>
            <h3 className="font-medium leading-snug">{p.name}</h3>
            <p className="mt-1 text-xs text-gray-500">{p.unit}</p>
            <p className="mt-2 text-lg font-semibold">{p.price_display}</p>
            <p className="text-xs text-gray-400">{p.stock > 0 ? `${p.stock} in stock` : "Out of stock"}</p>
          </div>
          <button
            onClick={() => onAdd(p.sku)}
            disabled={p.stock === 0 || addingSku === p.sku}
            className="mt-3 rounded-md bg-black px-3 py-2 text-sm text-white disabled:opacity-40"
          >
            {addingSku === p.sku ? "Adding..." : "Add to cart"}
          </button>
        </div>
      ))}
    </div>
  );
}
