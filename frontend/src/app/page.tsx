"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { addCartItem, fetchCart, fetchCategories, fetchProducts, initiateCheckout, removeCartItem } from "@/lib/api";
import { getOrCreateSessionId, openRazorpayCheckout } from "@/lib/checkout";
import type { Cart, Category, Product } from "@/lib/types";
import CategoryTabs from "@/components/CategoryTabs";
import SearchBox from "@/components/SearchBox";
import ProductGrid from "@/components/ProductGrid";
import ProductDetailModal from "@/components/ProductDetailModal";
import CartSidebar from "@/components/CartSidebar";
import FloatingChatLauncher from "@/components/FloatingChatLauncher";
import RequireAuth from "@/components/RequireAuth";

const CHAT_SESSION_STORAGE_KEY = "razorpay-agent-session-id";

export default function Home() {
  return (
    <RequireAuth allow={["buyer"]}>
      <Shop />
    </RequireAuth>
  );
}

function Shop() {
  const router = useRouter();
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [products, setProducts] = useState<Product[]>([]);
  const [cart, setCart] = useState<Cart | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addingSku, setAddingSku] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [viewingProduct, setViewingProduct] = useState<Product | null>(null);
  const [buyingNow, setBuyingNow] = useState(false);

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

  async function handleAddFromModal(sku: string) {
    await handleAdd(sku);
    setViewingProduct(null);
  }

  function currentSessionId(): string | null {
    try {
      return window.localStorage.getItem(CHAT_SESSION_STORAGE_KEY);
    } catch {
      return null;
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

  async function handleBuyNow() {
    setBuyingNow(true);
    setError(null);
    try {
      const payment = await initiateCheckout(getOrCreateSessionId());
      openRazorpayCheckout(payment, `Order #${payment.order_id}`, {
        onSuccess: () => {
          refreshCart();
          setBuyingNow(false);
          router.push("/orders");
        },
        onFailure: (result) => {
          setError(result.message);
          setBuyingNow(false);
        },
        onDismiss: () => setBuyingNow(false),
        onUnavailable: () => {
          setError("Razorpay Checkout hasn't loaded yet — please try again in a moment.");
          setBuyingNow(false);
        },
        onError: (message) => {
          setError(message);
          setBuyingNow(false);
        },
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBuyingNow(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-6 py-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Shop</h1>
        <p className="mt-1 text-sm text-ink-soft">
          Browse and add manually, or ask the assistant. Every money action it takes is policy-gated and logged.
        </p>
      </header>

      {error && <div className="rounded-lg border border-danger/25 bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
        <main className="flex flex-col gap-4">
          <SearchBox value={search} onChange={setSearch} />
          <CategoryTabs categories={categories} selected={selectedCategory} onSelect={setSelectedCategory} />
          <ProductGrid products={products} onAdd={handleAdd} onView={setViewingProduct} addingSku={addingSku} loading={loading} />
        </main>

        <CartSidebar cart={cart} onRemove={handleRemove} removingId={removingId} onBuyNow={handleBuyNow} buyingNow={buyingNow} />
      </div>

      {viewingProduct && (
        <ProductDetailModal
          product={viewingProduct}
          sessionId={currentSessionId()}
          onClose={() => setViewingProduct(null)}
          onAdd={handleAddFromModal}
          adding={addingSku === viewingProduct.sku}
        />
      )}

      <FloatingChatLauncher onCartChanged={refreshCart} />
    </div>
  );
}
