"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { setToken } from "@/lib/auth";
import { clearSessionId } from "@/lib/checkout";

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
    // A fresh login — any chat session id already sitting in localStorage
    // belongs to whoever last used this browser, not necessarily this
    // principal. Drop it so the next chat mints a new one instead of
    // colliding with someone else's AgentSession row.
    clearSessionId();
    // A full navigation, not a router.push — AuthProvider only fetches
    // /api/auth/me on mount, so this is what actually picks up the new token.
    window.location.href = "/";
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div className="mx-auto w-full max-w-sm px-6 py-8 text-sm text-ink-soft">Signing you in…</div>;
}

export default function LoginCallbackPage() {
  return (
    <Suspense fallback={<div className="mx-auto w-full max-w-sm px-6 py-8 text-sm text-ink-soft">Signing you in…</div>}>
      <LoginCallbackInner />
    </Suspense>
  );
}
