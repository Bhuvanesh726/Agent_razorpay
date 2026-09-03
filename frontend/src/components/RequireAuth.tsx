"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { AuthUser, useAuth } from "@/lib/auth";

interface Props {
  /** Which principal types may see this page. Omit to allow any onboarded human. */
  allow?: Array<"buyer" | "merchant">;
  children: React.ReactNode;
}

function landingPathFor(type: AuthUser["type"]): string {
  if (type === "merchant") return "/merchant";
  if (type === "buyer") return "/dashboard";
  return "/onboarding";
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
    if (user.type === "pending") {
      // A hard gate, not a suggestion — every ordinary page requires an
      // onboarded role, so a pending user always lands here first,
      // regardless of what this particular page's `allow` says.
      router.replace("/onboarding");
      return;
    }
    if (allow && !allow.includes(user.type as "buyer" | "merchant")) {
      // Redirect to that role's OWN landing page, never to "/" or some
      // other allow-restricted page — that would just bounce right back.
      router.replace(landingPathFor(user.type));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, user]);

  if (loading) return <div className="p-6 text-sm text-gray-400">Loading…</div>;
  if (!user || user.type === "pending") return null;
  if (allow && !allow.includes(user.type as "buyer" | "merchant")) return null;
  return <>{children}</>;
}
