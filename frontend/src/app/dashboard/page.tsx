"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchDashboardSummary } from "@/lib/api";
import type { DashboardSummary } from "@/lib/types";
import RequireAuth from "@/components/RequireAuth";
import FloatingChatLauncher from "@/components/FloatingChatLauncher";
import DevRoleSwitch from "@/components/DevRoleSwitch";
import { useAuth } from "@/lib/auth";

function paise(p: number): string {
  return `₹${(p / 100).toFixed(2)}`;
}

const ORDER_STATUS_STYLES: Record<string, string> = {
  PAID: "bg-green-100 text-green-800",
  FAILED: "bg-red-100 text-red-800",
};

function DashboardInner() {
  const { user, logout } = useAuth();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDashboardSummary()
      .then(setSummary)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 p-6">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Your dashboard</h1>
          <p className="text-sm text-gray-500">{user?.email}</p>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/" className="text-sm text-gray-500 underline hover:text-gray-800">
            Go to shop →
          </Link>
          <DevRoleSwitch />
          <button onClick={logout} className="text-sm text-gray-500 underline hover:text-gray-800">
            Sign out
          </button>
        </div>
      </header>

      {error && <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

      {loading ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : summary ? (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <section className="rounded-lg border border-gray-200 p-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Your agent</h2>
              <Link href="/agents" className="text-xs text-gray-400 underline hover:text-gray-700">
                Manage agents →
              </Link>
            </div>
            {summary.agent ? (
              <div className="mt-2 text-sm">
                <p className="font-medium">{summary.agent.name}</p>
                <p className="text-gray-500">
                  {summary.agent.delivery_mode} · {summary.agent.status}
                  {summary.agent_count > 1 && ` · ${summary.agent_count} total`}
                </p>
              </div>
            ) : (
              <div className="mt-3 flex flex-col items-start gap-2">
                <p className="text-sm text-gray-500">You haven&rsquo;t created an agent yet.</p>
                <Link
                  href="/agents"
                  className="rounded-md bg-black px-3 py-1.5 text-xs text-white hover:bg-gray-800"
                >
                  Create an agent
                </Link>
              </div>
            )}
          </section>

          <section className="rounded-lg border border-gray-200 p-4">
            <h2 className="font-semibold">Current cart</h2>
            {summary.cart.items.length === 0 ? (
              <p className="mt-2 text-sm text-gray-400">Empty — nothing added yet.</p>
            ) : (
              <>
                <ul className="mt-2 flex flex-col gap-1 text-sm">
                  {summary.cart.items.map((item) => (
                    <li key={item.id} className="flex justify-between">
                      <span>
                        {item.quantity} × {item.name}
                      </span>
                      <span>{item.line_total_display}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 border-t border-gray-100 pt-2 text-sm font-medium">
                  Total: {summary.cart.total_display}
                </p>
              </>
            )}
            <Link href="/" className="mt-3 inline-block text-xs text-gray-400 underline hover:text-gray-700">
              Go to shop →
            </Link>
          </section>

          <section className="rounded-lg border border-gray-200 p-4 md:col-span-2">
            <h2 className="font-semibold">Recent orders</h2>
            {summary.recent_orders.length === 0 ? (
              <p className="mt-2 text-sm text-gray-400">No orders yet.</p>
            ) : (
              <table className="mt-2 w-full border-collapse text-sm">
                <thead className="text-left text-gray-500">
                  <tr>
                    <th className="p-1.5">Order</th>
                    <th className="p-1.5">Amount</th>
                    <th className="p-1.5">Status</th>
                    <th className="p-1.5">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.recent_orders.map((o) => (
                    <tr key={o.id} className="border-t border-gray-100">
                      <td className="p-1.5">#{o.id}</td>
                      <td className="p-1.5">{paise(o.amount_paise)}</td>
                      <td className="p-1.5">
                        <span
                          className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                            ORDER_STATUS_STYLES[o.status] ?? "bg-gray-100 text-gray-700"
                          }`}
                        >
                          {o.status}
                        </span>
                      </td>
                      <td className="p-1.5 text-gray-400">{new Date(o.created_at + "Z").toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>
      ) : null}

      <FloatingChatLauncher onCartChanged={() => fetchDashboardSummary().then(setSummary).catch(() => undefined)} />
    </div>
  );
}

export default function DashboardPage() {
  return (
    <RequireAuth allow={["buyer"]}>
      <DashboardInner />
    </RequireAuth>
  );
}
