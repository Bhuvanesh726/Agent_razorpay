"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  actOnNotification,
  fetchHeadlineNumbers,
  fetchMerchantNotifications,
  fetchMerchantProducts,
  setProductDiscount,
  setProductPrice,
  toggleProductStock,
} from "@/lib/api";
import type { HeadlineNumbers, MerchantNotification, MerchantProductRow } from "@/lib/types";
import RequireAuth from "@/components/RequireAuth";
import DevRoleSwitch from "@/components/DevRoleSwitch";
import { useAuth } from "@/lib/auth";

function paise(p: number): string {
  return `₹${(p / 100).toFixed(2)}`;
}

const NOTIFICATION_LABELS: Record<string, string> = {
  UNMET_DEMAND: "Unmet demand",
  OUT_OF_STOCK_DEMAND: "Out-of-stock demand",
  BROWSE_ABANDONMENT: "Browse abandonment",
  ATTRIBUTE_GAP: "Attribute gap",
};

function NotificationCard({ n, onChanged }: { n: MerchantNotification; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function act(status: "ACTED" | "DISMISSED") {
    setBusy(true);
    setError(null);
    try {
      await actOnNotification(n.id, status);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-gray-200 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-xs font-medium text-indigo-800">
              {NOTIFICATION_LABELS[n.type] ?? n.type}
            </span>
            <span
              className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                n.status === "NEW"
                  ? "bg-amber-100 text-amber-800"
                  : n.status === "ACTED"
                    ? "bg-green-100 text-green-800"
                    : "bg-gray-100 text-gray-600"
              }`}
            >
              {n.status}
            </span>
          </div>
          <p className="mt-1.5 text-sm">{n.suggested_action}</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5 text-xs text-gray-500">
            {Object.entries(n.evidence).map(([k, v]) => (
              <span key={k} className="rounded bg-gray-100 px-1.5 py-0.5">
                {k}: {String(Array.isArray(v) ? v.join(", ") : v)}
              </span>
            ))}
          </div>
          {n.status === "ACTED" && (
            <p className="mt-1.5 text-xs text-green-700">
              Since you acted: {n.conversions_since_acted} matching purchase(s).
            </p>
          )}
        </div>
        {n.status === "NEW" && (
          <div className="flex shrink-0 gap-2">
            <button
              onClick={() => act("ACTED")}
              disabled={busy}
              className="rounded-md bg-black px-3 py-1.5 text-xs text-white disabled:opacity-40"
            >
              Mark acted
            </button>
            <button
              onClick={() => act("DISMISSED")}
              disabled={busy}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-xs disabled:opacity-40"
            >
              Dismiss
            </button>
          </div>
        )}
      </div>
      {error && <p className="mt-2 text-xs text-red-700">{error}</p>}
    </div>
  );
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
    <tr className="border-t border-gray-100 align-top">
      <td className="p-2">
        <div className="font-medium">{p.name}</div>
        <div className="text-xs text-gray-400">{p.sku}</div>
      </td>
      <td className="p-2 text-xs text-gray-500">{p.category}</td>
      <td className="p-2">
        <div className="flex items-center gap-1">
          <input
            value={priceInput}
            onChange={(e) => setPriceInput(e.target.value)}
            className="w-20 rounded-md border border-gray-300 px-2 py-1 text-xs"
          />
          <button onClick={savePrice} disabled={busy} className="text-xs text-gray-400 underline hover:text-gray-700">
            Save
          </button>
        </div>
        {p.discount_pct ? (
          <div className="mt-1 text-xs">
            <span className="text-gray-400 line-through">{paise(p.price_paise)}</span>{" "}
            <span className="font-medium text-green-700">{paise(p.effective_price_paise)}</span>{" "}
            <span className="text-green-700">(-{p.discount_pct}%)</span>
          </div>
        ) : null}
      </td>
      <td className="p-2">
        <div className="flex items-center gap-1">
          <input
            value={discountInput}
            onChange={(e) => setDiscountInput(e.target.value)}
            placeholder="0"
            className="w-14 rounded-md border border-gray-300 px-2 py-1 text-xs"
          />
          <span className="text-xs text-gray-400">%</span>
          <button onClick={saveDiscount} disabled={busy} className="text-xs text-gray-400 underline hover:text-gray-700">
            Set
          </button>
        </div>
      </td>
      <td className="p-2">
        <button
          onClick={toggleStock}
          disabled={busy}
          className={`rounded px-2 py-1 text-xs font-medium ${
            p.is_out_of_stock ? "bg-red-100 text-red-800" : "bg-green-100 text-green-800"
          }`}
        >
          {p.is_out_of_stock ? "Out of stock" : "In stock"}
        </button>
      </td>
      {error && (
        <td className="p-2 text-xs text-red-700" colSpan={1}>
          {error}
        </td>
      )}
    </tr>
  );
}

function MerchantDashboardInner() {
  const { user, logout } = useAuth();
  const [notifications, setNotifications] = useState<MerchantNotification[]>([]);
  const [products, setProducts] = useState<MerchantProductRow[]>([]);
  const [headline, setHeadline] = useState<HeadlineNumbers | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    Promise.all([fetchMerchantNotifications(), fetchMerchantProducts(), fetchHeadlineNumbers()])
      .then(([n, p, h]) => {
        setNotifications(n);
        setProducts(p);
        setHeadline(h);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-6">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Merchant dashboard</h1>
          <p className="text-sm text-gray-500">{user?.email}</p>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/campaigns" className="text-sm text-gray-500 underline hover:text-gray-800">
            Campaigns →
          </Link>
          <Link href="/audit" className="text-sm text-gray-500 underline hover:text-gray-800">
            Audit trail →
          </Link>
          <DevRoleSwitch />
          <button onClick={logout} className="text-sm text-gray-500 underline hover:text-gray-800">
            Sign out
          </button>
        </div>
      </header>

      {error && <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

      {headline && (
        <div className="grid grid-cols-2 gap-3 rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm sm:grid-cols-5">
          <div>
            <div className="text-xs text-gray-500">Queries received</div>
            <div className="text-lg font-semibold">{headline.queries_received}</div>
          </div>
          <div>
            <div className="text-xs text-gray-500">Match rate</div>
            <div className="text-lg font-semibold">{(headline.match_rate * 100).toFixed(0)}%</div>
          </div>
          <div>
            <div className="text-xs text-gray-500">Unmet demand</div>
            <div className="text-lg font-semibold">{headline.unmet_demand_count}</div>
          </div>
          <div>
            <div className="text-xs text-gray-500">Upsell revenue</div>
            <div className="text-lg font-semibold">{paise(headline.upsell_revenue_paise)}</div>
          </div>
          <div>
            <div className="text-xs text-gray-500">Campaign net margin</div>
            <div
              className={`text-lg font-semibold ${headline.campaign_net_margin_impact_paise < 0 ? "text-red-600" : "text-green-700"}`}
            >
              {paise(headline.campaign_net_margin_impact_paise)}
            </div>
          </div>
        </div>
      )}

      <section className="flex flex-col gap-3">
        <h2 className="font-semibold">Notifications</h2>
        {loading ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : notifications.length === 0 ? (
          <p className="text-sm text-gray-400">
            Nothing yet — notifications appear once enough buyers cross a demand threshold.
          </p>
        ) : (
          notifications.map((n) => <NotificationCard key={n.id} n={n} onChanged={refresh} />)
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="font-semibold">Products</h2>
        <div className="overflow-x-auto rounded-md border border-gray-200">
          <table className="w-full min-w-[720px] border-collapse text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                <th className="p-2">Product</th>
                <th className="p-2">Category</th>
                <th className="p-2">Price (₹)</th>
                <th className="p-2">Discount</th>
                <th className="p-2">Stock</th>
              </tr>
            </thead>
            <tbody>
              {products.map((p) => (
                <ProductActionsRow key={p.sku} p={p} onChanged={refresh} />
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

export default function MerchantDashboardPage() {
  return (
    <RequireAuth allow={["merchant"]}>
      <MerchantDashboardInner />
    </RequireAuth>
  );
}
