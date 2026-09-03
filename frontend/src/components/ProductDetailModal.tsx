"use client";

import { useEffect } from "react";
import { X } from "lucide-react";
import { logProductView } from "@/lib/api";
import type { Product } from "@/lib/types";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";

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
    <Modal onClose={onClose}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">{product.brand}</p>
          <h2 className="mt-0.5 text-lg font-semibold leading-snug tracking-tight text-ink">{product.name}</h2>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="-mr-1 -mt-1 rounded-md p-1.5 text-ink-faint transition-colors duration-150 hover:bg-black/[0.04] hover:text-ink"
        >
          <X size={18} />
        </button>
      </div>

      <p className="mt-3 text-sm leading-relaxed text-ink-soft">{product.description}</p>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {product.tags.map((t) => (
          <span key={t} className="rounded-full bg-black/[0.04] px-2 py-0.5 text-xs text-ink-soft">
            {t}
          </span>
        ))}
      </div>

      <div className="mt-5 flex items-center justify-between border-t border-line pt-4">
        <div>
          {product.discount_pct ? (
            <p className="flex items-baseline gap-1.5">
              <span className="font-mono text-sm tabular-nums text-ink-faint line-through">{product.price_display}</span>
              <span className="font-mono text-xl font-semibold tabular-nums text-success">
                {product.effective_price_display}
              </span>
              <span className="text-xs font-medium text-success">-{product.discount_pct}%</span>
            </p>
          ) : (
            <p className="font-mono text-xl font-semibold tabular-nums text-ink">{product.price_display}</p>
          )}
          <p className="mt-0.5 text-xs text-ink-faint">
            {product.unit} · {product.stock > 0 ? `${product.stock} in stock` : "Out of stock"}
          </p>
        </div>
        <Button variant="primary" onClick={() => onAdd(product.sku)} disabled={product.stock === 0 || adding}>
          {adding ? "Adding…" : "Add to cart"}
        </Button>
      </div>
    </Modal>
  );
}
