"use client";

import { useEffect, useState } from "react";
import { ReceiptText } from "lucide-react";
import { fetchMerchantOrders } from "@/lib/api";
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

function MerchantOrdersInner() {
  const [orders, setOrders] = useState<OrderListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openOrderId, setOpenOrderId] = useState<number | null>(null);

  useEffect(() => {
    fetchMerchantOrders()
      .then(setOrders)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-6 py-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Orders</h1>
        <p className="mt-1 text-sm text-ink-soft">Every order placed by every buyer — click one for the full detail.</p>
      </header>

      {error && <div className="rounded-lg border border-danger/25 bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>}

      {loading ? (
        <SkeletonRows count={6} />
      ) : orders.length === 0 ? (
        <EmptyState icon={ReceiptText} title="No orders yet" description="Orders from buyers will show up here." />
      ) : (
        <TableWrap>
          <Table>
            <THead>
              <tr>
                <Th>Order</Th>
                <Th>Buyer</Th>
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
                  <Td>{o.buyer_email}</Td>
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

      {openOrderId != null && <OrderDetailModal orderId={openOrderId} onClose={() => setOpenOrderId(null)} showBuyer />}
    </div>
  );
}

export default function MerchantOrdersPage() {
  return (
    <RequireAuth allow={["merchant"]}>
      <MerchantOrdersInner />
    </RequireAuth>
  );
}
