"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Bot, Package, ReceiptText } from "lucide-react";
import { fetchDashboardSummary } from "@/lib/api";
import type { DashboardSummary } from "@/lib/types";
import RequireAuth from "@/components/RequireAuth";
import FloatingChatLauncher from "@/components/FloatingChatLauncher";
import OrderDetailModal from "@/components/OrderDetailModal";
import DevRoleSwitch from "@/components/DevRoleSwitch";
import { useAuth } from "@/lib/auth";
import Button from "@/components/ui/Button";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/Card";
import { StatusBadge } from "@/components/ui/Badge";
import EmptyState from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Table, TableWrap, THead, Th, Tr, Td } from "@/components/ui/Table";

function paise(p: number): string {
  return `₹${(p / 100).toFixed(2)}`;
}

function DashboardInner() {
  const { user } = useAuth();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openOrderId, setOpenOrderId] = useState<number | null>(null);

  function refresh() {
    fetchDashboardSummary()
      .then(setSummary)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-6 py-8">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Your dashboard</h1>
          <p className="mt-1 text-sm text-ink-soft">{user?.email}</p>
        </div>
        <DevRoleSwitch />
      </header>

      {error && <div className="rounded-lg border border-danger/25 bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>}

      {loading ? (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          <Skeleton className="h-36" />
          <Skeleton className="h-36" />
          <Skeleton className="h-48 md:col-span-2" />
        </div>
      ) : summary ? (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Your agent</CardTitle>
              <Link href="/agents" className="text-xs font-medium text-accent hover:text-accent-hover">
                Manage agents →
              </Link>
            </CardHeader>
            <CardBody>
              {summary.agent ? (
                <div className="flex items-start gap-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
                    <Bot size={17} />
                  </div>
                  <div className="text-sm">
                    <p className="font-medium text-ink">{summary.agent.name}</p>
                    <p className="mt-0.5 flex items-center gap-1.5 text-ink-soft">
                      {summary.agent.delivery_mode}
                      <StatusBadge status={summary.agent.status} />
                      {summary.agent_count > 1 && <span>· {summary.agent_count} total</span>}
                    </p>
                  </div>
                </div>
              ) : (
                <EmptyState
                  icon={Bot}
                  title="No agent yet"
                  description="Create a bounded agent to shop on your behalf, with its own spend limit and scopes."
                  action={
                    <Link href="/agents">
                      <Button variant="primary" size="sm">
                        Create an agent
                      </Button>
                    </Link>
                  }
                  className="border-0 p-0 py-4"
                />
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Current cart</CardTitle>
              <Link href="/" className="text-xs font-medium text-accent hover:text-accent-hover">
                Go to shop →
              </Link>
            </CardHeader>
            <CardBody>
              {summary.cart.items.length === 0 ? (
                <EmptyState
                  icon={Package}
                  title="Cart is empty"
                  description="Nothing added yet — browse the shop or ask the assistant."
                  className="border-0 p-0 py-4"
                />
              ) : (
                <>
                  <ul className="flex flex-col gap-1.5 text-sm">
                    {summary.cart.items.map((item) => (
                      <li key={item.id} className="flex justify-between text-ink">
                        <span>
                          {item.quantity} × {item.name}
                        </span>
                        <span className="font-mono tabular-nums">{item.line_total_display}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 flex justify-between border-t border-line pt-2 text-sm font-semibold text-ink">
                    <span>Total</span>
                    <span className="font-mono tabular-nums">{summary.cart.total_display}</span>
                  </p>
                </>
              )}
            </CardBody>
          </Card>

          <Card className="md:col-span-2">
            <CardHeader>
              <CardTitle>Recent orders</CardTitle>
              <Link href="/orders" className="text-xs font-medium text-accent hover:text-accent-hover">
                View all →
              </Link>
            </CardHeader>
            <CardBody className={summary.recent_orders.length === 0 ? "" : "p-0"}>
              {summary.recent_orders.length === 0 ? (
                <EmptyState
                  icon={ReceiptText}
                  title="No orders yet"
                  description="Completed orders will show up here."
                  className="border-0 p-0 py-4"
                />
              ) : (
                <TableWrap className="rounded-none border-0">
                  <Table>
                    <THead>
                      <tr>
                        <Th>Order</Th>
                        <Th align="right">Amount</Th>
                        <Th>Status</Th>
                        <Th align="right">Date</Th>
                      </tr>
                    </THead>
                    <tbody>
                      {summary.recent_orders.map((o) => (
                        <Tr key={o.id} onClick={() => setOpenOrderId(o.id)}>
                          <Td className="font-mono">#{o.id}</Td>
                          <Td align="right" numeric>
                            {paise(o.amount_paise)}
                          </Td>
                          <Td>
                            <StatusBadge status={o.status} />
                          </Td>
                          <Td align="right" className="text-ink-faint">
                            {new Date(o.created_at + "Z").toLocaleDateString()}
                          </Td>
                        </Tr>
                      ))}
                    </tbody>
                  </Table>
                </TableWrap>
              )}
            </CardBody>
          </Card>
        </div>
      ) : null}

      {openOrderId != null && <OrderDetailModal orderId={openOrderId} onClose={() => setOpenOrderId(null)} />}

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
