"use client";

import { useEffect, useMemo, useState } from "react";
import { Package } from "lucide-react";
import { fetchMerchantProducts, setProductDiscount, setProductPrice, toggleProductStock } from "@/lib/api";
import type { MerchantProductRow } from "@/lib/types";
import RequireAuth from "@/components/RequireAuth";
import { Badge } from "@/components/ui/Badge";
import EmptyState from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { Table, TableWrap, THead, Th, Tr, Td } from "@/components/ui/Table";

function paise(p: number): string {
  return `₹${(p / 100).toFixed(2)}`;
}

function slugify(category: string): string {
  return category.toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

// Matches CategoryTabs.tsx's convention on the shop page: raw slug ("cool_drinks")
// -> spaced + CSS-capitalized ("Cool Drinks"), so category names read the same
// way everywhere they appear.
function formatCategory(category: string): string {
  return category.replace(/_/g, " ");
}

function ProductActionsRow({ p, onChanged }: { p: MerchantProductRow; onChanged: () => void }) {
  const [priceInput, setPriceInput] = useState(String(p.price_paise / 100));
  const [discountInput, setDiscountInput] = useState(p.discount_pct ? String(p.discount_pct) : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function savePrice() {
    const rupees = Number(priceInput);
    if (!rupees || rupees <= 0) return;
    setBusy(true);
    setError(null);
    try {
      await setProductPrice(p.sku, Math.round(rupees * 100));
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveDiscount() {
    const pct = discountInput.trim() ? Number(discountInput) : null;
    setBusy(true);
    setError(null);
    try {
      await setProductDiscount(p.sku, pct);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function toggleStock() {
    setBusy(true);
    setError(null);
    try {
      await toggleProductStock(p.sku);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Tr className="align-top">
      <Td>
        <div className="font-medium text-ink">{p.name}</div>
        <div className="font-mono text-xs text-ink-faint">{p.sku}</div>
      </Td>
      <Td>
        <div className="flex items-center gap-1.5">
          <Input value={priceInput} onChange={(e) => setPriceInput(e.target.value)} className="w-20 py-1 font-mono tabular-nums" />
          <button onClick={savePrice} disabled={busy} className="text-xs font-medium text-accent hover:text-accent-hover disabled:opacity-40">
            Save
          </button>
        </div>
        {p.discount_pct ? (
          <div className="mt-1 font-mono text-xs tabular-nums">
            <span className="text-ink-faint line-through">{paise(p.price_paise)}</span>{" "}
            <span className="font-medium text-success">{paise(p.effective_price_paise)}</span>{" "}
            <span className="text-success">(-{p.discount_pct}%)</span>
          </div>
        ) : null}
      </Td>
      <Td>
        <div className="flex items-center gap-1.5">
          <Input
            value={discountInput}
            onChange={(e) => setDiscountInput(e.target.value)}
            placeholder="0"
            className="w-14 py-1 font-mono tabular-nums"
          />
          <span className="text-xs text-ink-faint">%</span>
          <button onClick={saveDiscount} disabled={busy} className="text-xs font-medium text-accent hover:text-accent-hover disabled:opacity-40">
            Set
          </button>
        </div>
      </Td>
      <Td>
        <button onClick={toggleStock} disabled={busy} className="transition-opacity duration-150 disabled:opacity-40">
          <Badge variant={p.is_out_of_stock ? "danger" : "success"}>{p.is_out_of_stock ? "Out of stock" : "In stock"}</Badge>
        </button>
        {error && <p className="mt-1 text-xs text-danger">{error}</p>}
      </Td>
    </Tr>
  );
}

function CategorySection({
  category,
  products,
  onChanged,
}: {
  category: string;
  products: MerchantProductRow[];
  onChanged: () => void;
}) {
  return (
    <section id={`cat-${slugify(category)}`} className="scroll-mt-20">
      <h2 className="mb-3 flex items-baseline gap-2 text-sm font-semibold capitalize tracking-tight text-ink">
        {formatCategory(category)}
        <span className="font-mono text-xs font-normal tabular-nums text-ink-faint">({products.length})</span>
      </h2>
      <TableWrap>
        <Table className="min-w-[640px]">
          <THead>
            <tr>
              <Th>Product</Th>
              <Th>Price (₹)</Th>
              <Th>Discount</Th>
              <Th>Stock</Th>
            </tr>
          </THead>
          <tbody>
            {products.map((p) => (
              <ProductActionsRow key={p.sku} p={p} onChanged={onChanged} />
            ))}
          </tbody>
        </Table>
      </TableWrap>
    </section>
  );
}

function MerchantProductsInner() {
  const [products, setProducts] = useState<MerchantProductRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    fetchMerchantProducts()
      .then((p) => {
        setProducts(p);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  const byCategory = useMemo(() => {
    const groups = new Map<string, MerchantProductRow[]>();
    for (const p of products) {
      const list = groups.get(p.category) ?? [];
      list.push(p);
      groups.set(p.category, list);
    }
    return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [products]);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-6 py-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Products</h1>
        <p className="mt-1 text-sm text-ink-soft">
          {loading ? "Loading catalog…" : `${products.length} products across ${byCategory.length} categories.`} Edit
          price, discount, and stock inline — changes apply immediately.
        </p>
      </header>

      {error && <div className="rounded-lg border border-danger/25 bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>}

      {!loading && byCategory.length > 0 && (
        <nav className="flex flex-wrap gap-1.5">
          {byCategory.map(([category, items]) => (
            <a
              key={category}
              href={`#cat-${slugify(category)}`}
              className="rounded-full border border-line px-3 py-1 text-xs font-medium capitalize text-ink-soft transition-colors duration-150 hover:border-line-strong hover:text-ink"
            >
              {formatCategory(category)} <span className="font-mono tabular-nums text-ink-faint">({items.length})</span>
            </a>
          ))}
        </nav>
      )}

      {loading ? (
        <div className="flex flex-col gap-6">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      ) : byCategory.length === 0 ? (
        <EmptyState icon={Package} title="No products in your catalog" />
      ) : (
        <div className="flex flex-col gap-8">
          {byCategory.map(([category, items]) => (
            <CategorySection key={category} category={category} products={items} onChanged={refresh} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function MerchantProductsPage() {
  return (
    <RequireAuth allow={["merchant"]}>
      <MerchantProductsInner />
    </RequireAuth>
  );
}
