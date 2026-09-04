"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import { fetchOrderDetail } from "@/lib/api";
import type { OrderDetail } from "@/lib/types";
import { StatusBadge } from "@/components/ui/Badge";
import Modal from "@/components/ui/Modal";
import { Skeleton } from "@/components/ui/Skeleton";
import { Table, TableWrap, THead, Th, Tr, Td } from "@/components/ui/Table";

function paise(p: number): string {
  return `₹${(p / 100).toFixed(2)}`;
}

// Locally-signed capture ids — the payment was never processed by Razorpay and
// will not resolve in their API. Kept as a prefix check because that is exactly
// how the ids are minted (app/routers/payments.py::test_complete_payment and
// app/agent/harness.py::_auto_complete_agent_payment). Verify any order for
// yourself with backend/scripts/verify_payments.py; see docs/PAYMENT-REALITY.md.
const SIMULATED_PAYMENT_PREFIXES = ["pay_test_", "pay_auto_", "pay_demo"];
// Orders written by the development-only demo seed (backend/app/testing/demo_login.py).
// These differ from the rest: their Razorpay *order* was never created either, so the
// weaker "the order is real, only the capture is local" wording would overstate them.
const SEEDED_PAYMENT_PREFIX = "pay_demo_seed";

function isSimulatedCapture(paymentId: string | null): boolean {
  return !!paymentId && SIMULATED_PAYMENT_PREFIXES.some((prefix) => paymentId.startsWith(prefix));
}

function isSeededCapture(paymentId: string | null): boolean {
  return !!paymentId && paymentId.startsWith(SEEDED_PAYMENT_PREFIX);
}

interface Props {
  orderId: number;
  onClose: () => void;
  showBuyer?: boolean;
}

export default function OrderDetailModal({ orderId, onClose, showBuyer = false }: Props) {
  const [order, setOrder] = useState<OrderDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Deferred to a microtask so the reset + fetch's setState calls don't
    // run synchronously inside the effect body itself.
    Promise.resolve().then(() => {
      setOrder(null);
      setError(null);
      fetchOrderDetail(orderId)
        .then(setOrder)
        .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    });
  }, [orderId]);

  return (
    <Modal onClose={onClose} maxWidth="max-w-xl">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-ink">Order #{orderId}</h2>
          {order && (
            <p className="mt-1 flex items-center gap-2 text-sm text-ink-soft">
              {new Date(order.created_at + "Z").toLocaleString()}
              <StatusBadge status={order.status} />
              {showBuyer && <span className="text-ink-faint">· {order.buyer_email}</span>}
            </p>
          )}
        </div>
        <button
          onClick={onClose}
          className="rounded-md p-1 text-ink-faint transition-colors duration-150 hover:bg-black/[0.04] hover:text-ink"
        >
          <X size={16} />
        </button>
      </div>

      {error && <div className="mt-4 rounded-lg border border-danger/25 bg-danger-soft px-3 py-2 text-sm text-danger">{error}</div>}

      {!order && !error && (
        <div className="mt-4 flex flex-col gap-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      )}

      {order && (
        <>
          <div className="mt-4">
            <TableWrap>
              <Table>
                <THead>
                  <tr>
                    <Th>Item</Th>
                    <Th align="right">Qty</Th>
                    <Th align="right">Unit price</Th>
                    <Th align="right">Line total</Th>
                  </tr>
                </THead>
                <tbody>
                  {order.items.map((item) => (
                    <Tr key={item.sku}>
                      <Td>
                        <div className="font-medium text-ink">{item.name}</div>
                        <div className="font-mono text-xs text-ink-faint">{item.sku}</div>
                      </Td>
                      <Td align="right" numeric>
                        {item.quantity}
                      </Td>
                      <Td align="right" numeric>
                        {paise(item.unit_price_paise)}
                      </Td>
                      <Td align="right" numeric>
                        {paise(item.line_total_paise)}
                      </Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
            </TableWrap>
            <div className="mt-3 flex items-center justify-between border-t border-line pt-3 text-sm font-semibold text-ink">
              <span>Total</span>
              <span className="font-mono tabular-nums">{paise(order.amount_paise)}</span>
            </div>
          </div>

          {order.status === "FAILED" && (order.failure_code || order.failure_description) && (
            <div className="mt-4 rounded-lg border border-danger/25 bg-danger-soft p-3.5 text-sm">
              <div className="flex items-start gap-2">
                <AlertTriangle size={16} className="mt-0.5 shrink-0 text-danger" />
                <div>
                  <p className="font-medium text-danger">Payment failed</p>
                  {order.failure_description && <p className="mt-0.5 text-danger/90">{order.failure_description}</p>}
                  {order.failure_code && (
                    <p className="mt-1.5 font-mono text-[11px] tracking-tight text-danger/70">{order.failure_code}</p>
                  )}
                </div>
              </div>
            </div>
          )}

          {order.status === "PAID" && order.razorpay_payment_id && (
            <div className="mt-4">
              <p className="text-xs text-ink-faint">
                Payment ID <span className="font-mono text-ink-soft">{order.razorpay_payment_id}</span>
              </p>
              {isSimulatedCapture(order.razorpay_payment_id) && (
                <div className="mt-2 rounded-lg border border-warning/25 bg-warning-soft p-3 text-xs">
                  <div className="flex items-start gap-2">
                    <AlertTriangle size={14} className="mt-0.5 shrink-0 text-warning" />
                    {isSeededCapture(order.razorpay_payment_id) ? (
                      <p className="text-warning">
                        <span className="font-medium">Seeded demo order — no money moved.</span> Nothing here reached
                        Razorpay: neither this payment nor its order was ever created there. It exists so a reviewer
                        has history to look at. See <span className="font-mono">docs/PAYMENT-REALITY.md</span>.
                      </p>
                    ) : (
                      <p className="text-warning">
                        <span className="font-medium">Simulated capture (test mode).</span> The Razorpay order is
                        real, but this payment id was signed locally — Razorpay never processed it, so it will not
                        resolve in their dashboard or API. See{" "}
                        <span className="font-mono">docs/PAYMENT-REALITY.md</span>.
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </Modal>
  );
}
