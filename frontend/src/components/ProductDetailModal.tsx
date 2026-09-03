"use client";

import { useEffect } from "react";
import { logProductView } from "@/lib/api";
import type { Product } from "@/lib/types";

interface Props {
  product: Product;
  sessionId: string | null;
  onClose: () => void;
  onAdd: (sku: string) => void;
  adding: boolean;
}

export default function ProductDetailModal({ product, sessionId, onClose, onAdd, adding }: Props) {
  useEffect(() => {
    // Fires once per open — this is the "product detail opened" signal
    // the browse-abandonment segment looks for. Fire-and-forget: logProductView
    // never throws and never blocks this render either way.
    logProductView(product.sku, sessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [product.sku]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs uppercase text-gray-400">{product.brand}</p>
            <h2 className="text-lg font-semibold leading-snug">{product.name}</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700" aria-label="Close">
            ✕
          </button>
        </div>

        <p className="mt-3 text-sm text-gray-600">{product.description}</p>

        <div className="mt-3 flex flex-wrap gap-1">
          {product.tags.map((t) => (
            <span key={t} className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
              {t}
            </span>
          ))}
        </div>

        <div className="mt-4 flex items-center justify-between">
          <div>
            {product.discount_pct ? (
              <p className="flex items-baseline gap-1.5">
                <span className="text-sm text-gray-400 line-through">{product.price_display}</span>
                <span className="text-xl font-semibold text-green-700">{product.effective_price_display}</span>
                <span className="text-xs font-medium text-green-700">-{product.discount_pct}%</span>
              </p>
            ) : (
              <p className="text-xl font-semibold">{product.price_display}</p>
            )}
            <p className="text-xs text-gray-400">
              {product.unit} · {product.stock > 0 ? `${product.stock} in stock` : "Out of stock"}
            </p>
          </div>
          <button
            onClick={() => onAdd(product.sku)}
            disabled={product.stock === 0 || adding}
            className="rounded-md bg-black px-4 py-2 text-sm text-white disabled:opacity-40"
          >
            {adding ? "Adding..." : "Add to cart"}
          </button>
        </div>
      </div>
    </div>
  );
}
