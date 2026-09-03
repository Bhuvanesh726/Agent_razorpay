"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { setToken } from "@/lib/auth";

function LoginCallbackInner() {
  const params = useSearchParams();
  const router = useRouter();

  useEffect(() => {
    const token = params.get("token");
    if (!token) {
      router.replace("/login");
      return;
    }
    setToken(token);
    // A full navigation, not a router.push — AuthProvider only fetches
    // /api/auth/me on mount, so this is what actually picks up the new token.
    window.location.href = "/";
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div className="p-6 text-sm text-gray-400">Signing you in…</div>;
}

export default function LoginCallbackPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-gray-400">Signing you in…</div>}>
      <LoginCallbackInner />
    </Suspense>
  );
}
