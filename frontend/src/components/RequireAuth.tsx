"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { AuthUser, useAuth } from "@/lib/auth";

interface Props {
  /** Which principal types may see this page. Omit to allow any signed-in human. */
  allow?: Array<"buyer" | "merchant">;
  children: React.ReactNode;
}

function landingPathFor(type: AuthUser["type"]): string {
  return type === "merchant" ? "/merchant" : "/dashboard";
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
      // Redirect to that role's OWN landing page, never to "/" or some
      // other allow-restricted page — that would just bounce right back.
      router.replace(landingPathFor(user.type));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, user]);

  if (loading) {
    return (
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-6 py-8">
        <div className="h-7 w-40 animate-pulse rounded-md bg-black/[0.05]" />
        <div className="h-4 w-72 animate-pulse rounded-md bg-black/[0.05]" />
        <div className="mt-4 h-40 w-full animate-pulse rounded-lg bg-black/[0.05]" />
      </div>
    );
  }
  if (!user) return null;
  if (allow && !allow.includes(user.type as "buyer" | "merchant")) return null;
  return <>{children}</>;
}
