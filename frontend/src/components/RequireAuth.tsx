"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

interface Props {
  /** Which principal types may see this page. Omit to allow any signed-in human. */
  allow?: Array<"buyer" | "merchant">;
  children: React.ReactNode;
}

export default function RequireAuth({ allow, children }: Props) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    if (allow && !allow.includes(user.type as "buyer" | "merchant")) {
      // Never redirect to "/" for a role that isn't allowed there (e.g. a
      // merchant hitting the buyer-only shop) — "/" itself requires
      // allow={["buyer"]}, so that would just bounce right back here.
      router.replace(user.type === "merchant" ? "/campaigns" : "/");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, user]);

  if (loading) return <div className="p-6 text-sm text-gray-400">Loading…</div>;
  if (!user) return null;
  if (allow && !allow.includes(user.type as "buyer" | "merchant")) return null;
  return <>{children}</>;
}
