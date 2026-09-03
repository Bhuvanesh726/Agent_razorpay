"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Megaphone, Package, ScrollText, ShoppingBag, Bot, Receipt, LogOut } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { Badge } from "@/components/ui/Badge";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  /** A path this item should also read as "active" for (e.g. the shop
   * itself has no separate top-level route beyond "/"). */
  match?: (pathname: string) => boolean;
}

const BUYER_NAV: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Shop", href: "/", icon: ShoppingBag, match: (p) => p === "/" },
  { label: "My Agent", href: "/agents", icon: Bot },
  { label: "Orders", href: "/orders", icon: Receipt },
];

const MERCHANT_NAV: NavItem[] = [
  { label: "Dashboard", href: "/merchant", icon: LayoutDashboard, match: (p) => p === "/merchant" },
  { label: "Orders", href: "/merchant/orders", icon: Receipt },
  { label: "Products", href: "/merchant/products", icon: Package },
  { label: "Campaigns", href: "/campaigns", icon: Megaphone },
  { label: "Audit", href: "/audit", icon: ScrollText },
];

function NavLink({ item, pathname }: { item: NavItem; pathname: string }) {
  const active = item.match ? item.match(pathname) : pathname === item.href;
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors duration-150 ${
        active ? "bg-accent-soft text-accent" : "text-ink-soft hover:bg-black/[0.04] hover:text-ink"
      }`}
    >
      <Icon size={15} />
      {item.label}
    </Link>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const pathname = usePathname();

  const nav = user?.type === "merchant" ? MERCHANT_NAV : user?.type === "buyer" ? BUYER_NAV : [];
  const homeHref = user?.type === "merchant" ? "/merchant" : user?.type === "buyer" ? "/dashboard" : "/";

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur-sm">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
          <div className="flex items-center gap-6">
            <Link href={homeHref} className="text-sm font-semibold tracking-tight text-ink">
              Razorpay Shop
            </Link>
            {nav.length > 0 && (
              <nav className="flex items-center gap-1">
                {nav.map((item) => (
                  <NavLink key={item.label} item={item} pathname={pathname} />
                ))}
              </nav>
            )}
          </div>

          {user && user.type !== "pending" && (
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 text-sm">
                <span className="text-ink-soft">{user.email}</span>
                {user.role && (
                  <Badge variant="neutral" className="font-mono text-[10px] uppercase tracking-wide">
                    {user.role}
                  </Badge>
                )}
              </div>
              <button
                onClick={logout}
                className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-ink-soft transition-colors duration-150 hover:bg-black/[0.04] hover:text-ink"
              >
                <LogOut size={14} />
                Sign out
              </button>
            </div>
          )}
        </div>
      </header>

      <main className="flex-1">{children}</main>
    </div>
  );
}
