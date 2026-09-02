"use client";

import { useEffect, useState } from "react";
import { addCartItem, fetchCart, fetchCategories, fetchProducts, removeCartItem } from "@/lib/api";
import type { Cart, Category, Product } from "@/lib/types";
import CategoryTabs from "@/components/CategoryTabs";
import SearchBox from "@/components/SearchBox";
import ProductGrid from "@/components/ProductGrid";
import CartSidebar from "@/components/CartSidebar";

export default function Home() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [products, setProducts] = useState<Product[]>([]);
  const [cart, setCart] = useState<Cart | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addingSku, setAddingSku] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<number | null>(null);

  useEffect(() => {
    fetchCategories().then(setCategories).catch((e) => setError(e.message));
    fetchCart().then(setCart).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    const handle = setTimeout(() => {
      setLoading(true);
      fetchProducts({ category: selectedCategory, search, pageSize: 50 })
        .then((res) => {
          setProducts(res.items);
          setError(null);
        })
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false));
    }, 200);
    return () => clearTimeout(handle);
  }, [selectedCategory, search]);

  async function handleAdd(sku: string) {
    setAddingSku(sku);
    try {
      setCart(await addCartItem(sku));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAddingSku(null);
    }
  }

  async function handleRemove(itemId: number) {
    setRemovingId(itemId);
    try {
      setCart(await removeCartItem(itemId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRemovingId(null);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-6">
      <header>
        <h1 className="text-2xl font-semibold">Razorpay Shop</h1>
        <p className="text-sm text-gray-500">Layer 0 — no AI yet, just the shopping basics.</p>
      </header>

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_300px]">
        <main className="flex flex-col gap-4">
          <SearchBox value={search} onChange={setSearch} />
          <CategoryTabs categories={categories} selected={selectedCategory} onSelect={setSelectedCategory} />
          {loading ? (
            <p className="text-sm text-gray-500">Loading products...</p>
          ) : (
            <ProductGrid products={products} onAdd={handleAdd} addingSku={addingSku} />
          )}
        </main>

        <CartSidebar cart={cart} onRemove={handleRemove} removingId={removingId} />
      </div>
    </div>
  );
}
