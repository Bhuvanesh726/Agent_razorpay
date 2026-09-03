"use client";

import { useEffect, useState } from "react";
import { ReceiptText } from "lucide-react";
import { fetchOrders } from "@/lib/api";
import type { OrderListItem } from "@/lib/types";
import RequireAuth from "@/components/RequireAuth";
import OrderDetailModal from "@/components/OrderDetailModal";
import { StatusBadge } from "@/components/ui/Badge";
import EmptyState from "@/components/ui/EmptyState";
import { SkeletonRows } from "@/components/ui/Skeleton";
import { Table, TableWrap, THead, Th, Tr, Td } from "@/components/ui/Table";

function paise(p: number): string {
  return `₹${(p / 100).toFixed(2)}`;
}

function OrdersInner() {
  const [orders, setOrders] = useState<OrderListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openOrderId, setOpenOrderId] = useState<number | null>(null);

  useEffect(() => {
    fetchOrders()
      .then(setOrders)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-6 py-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Your orders</h1>
        <p className="mt-1 text-sm text-ink-soft">
          Every order you&rsquo;ve placed — manually or through the shopping assistant. Click one for the full item list,
          total, and status.
        </p>
      </header>

      {error && <div className="rounded-lg border border-danger/25 bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>}

      {loading ? (
        <SkeletonRows count={5} />
      ) : orders.length === 0 ? (
        <EmptyState icon={ReceiptText} title="No orders yet" description="Orders you place will show up here." />
      ) : (
        <TableWrap>
          <Table>
            <THead>
              <tr>
                <Th>Order</Th>
                <Th>Date</Th>
                <Th align="right">Items</Th>
                <Th align="right">Total</Th>
                <Th>Status</Th>
              </tr>
            </THead>
            <tbody>
              {orders.map((o) => (
                <Tr key={o.id} onClick={() => setOpenOrderId(o.id)}>
                  <Td className="font-mono">#{o.id}</Td>
                  <Td className="text-ink-faint">{new Date(o.created_at + "Z").toLocaleDateString()}</Td>
                  <Td align="right" numeric>
                    {o.item_count}
                  </Td>
                  <Td align="right" numeric>
                    {paise(o.amount_paise)}
                  </Td>
                  <Td>
                    <StatusBadge status={o.status} />
                  </Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        </TableWrap>
      )}

      {openOrderId != null && <OrderDetailModal orderId={openOrderId} onClose={() => setOpenOrderId(null)} />}
    </div>
  );
}

export default function OrdersPage() {
  return (
    <RequireAuth allow={["buyer"]}>
      <OrdersInner />
    </RequireAuth>
  );
}
