"use client";

import { useEffect, useState } from "react";
import { addCartItem, fetchCart, fetchCategories, fetchProducts, removeCartItem } from "@/lib/api";
import type { Cart, Category, Product } from "@/lib/types";
import CategoryTabs from "@/components/CategoryTabs";
import SearchBox from "@/components/SearchBox";
import ProductGrid from "@/components/ProductGrid";
import CartSidebar from "@/components/CartSidebar";
import ChatPanel from "@/components/ChatPanel";

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

  function refreshCart() {
    fetchCart().then(setCart).catch((e) => setError(e.message));
  }

  useEffect(() => {
    fetchCategories().then(setCategories).catch((e) => setError(e.message));
    refreshCart();
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
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Razorpay Shop</h1>
          <p className="text-sm text-gray-500">
            Browse and add manually, or ask the assistant. Every money action it takes is policy-gated and logged.
          </p>
        </div>
        <div className="flex gap-4">
          <a href="/campaigns" className="text-sm text-gray-500 underline hover:text-gray-800">
            Campaigns →
          </a>
          <a href="/audit" className="text-sm text-gray-500 underline hover:text-gray-800">
            Audit trail viewer →
          </a>
        </div>
      </header>

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_360px_300px]">
        <main className="flex flex-col gap-4">
          <SearchBox value={search} onChange={setSearch} />
          <CategoryTabs categories={categories} selected={selectedCategory} onSelect={setSelectedCategory} />
          {loading ? (
            <p className="text-sm text-gray-500">Loading products...</p>
          ) : (
            <ProductGrid products={products} onAdd={handleAdd} addingSku={addingSku} />
          )}
        </main>

        <ChatPanel onCartChanged={refreshCart} />

        <CartSidebar cart={cart} onRemove={handleRemove} removingId={removingId} />
      </div>
    </div>
  );
}
