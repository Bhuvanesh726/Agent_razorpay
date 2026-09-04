"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { LogIn, ShoppingBag, Store } from "lucide-react";
import { googleLoginUrl, setToken, useAuth } from "@/lib/auth";
import { demoLogin, fetchDemoLoginOptions } from "@/lib/api";
import type { DemoPrincipalOption } from "@/lib/types";
import { clearSessionId } from "@/lib/checkout";
import { Card, CardBody } from "@/components/ui/Card";

const ROLE_ICONS = {
  BUYER: ShoppingBag,
  MERCHANT: Store,
} as const;

function LoginInner() {
  const { user, loading } = useAuth();
  const searchParams = useSearchParams();
  const error = searchParams.get("error");

  const [demoPrincipals, setDemoPrincipals] = useState<DemoPrincipalOption[]>([]);
  const [pendingRole, setPendingRole] = useState<string | null>(null);
  const [demoError, setDemoError] = useState<string | null>(null);
  const [redirectTo, setRedirectTo] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && user) {
      window.location.href = "/";
    }
  }, [loading, user]);

  // A full navigation, not router.push — AuthProvider only fetches
  // /api/auth/me on mount, so this is what picks up the new token. Same
  // approach as the Google sign-in callback.
  useEffect(() => {
    if (redirectTo) window.location.href = redirectTo;
  }, [redirectTo]);

  useEffect(() => {
    let cancelled = false;
    fetchDemoLoginOptions()
      .then((options) => {
        if (!cancelled && options.available) setDemoPrincipals(options.principals);
      })
      // Not an error worth showing: outside development there are simply no
      // demo principals to offer, and Google sign-in above still works.
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleDemoLogin(role: "BUYER" | "MERCHANT") {
    setPendingRole(role);
    setDemoError(null);
    try {
      const result = await demoLogin(role);
      setToken(result.token);
      // Same reasoning as the Google callback: a chat session id left in
      // localStorage belongs to whoever last used this browser.
      clearSessionId();
      setRedirectTo("/");
    } catch (e) {
      setDemoError(e instanceof Error ? e.message : "Demo sign-in failed.");
      setPendingRole(null);
    }
  }

  if (!loading && user) {
    return null;
  }

  return (
    <div className="mx-auto flex min-h-[70vh] w-full max-w-sm flex-col justify-center px-6 py-8">
      <Card>
        <CardBody className="flex flex-col items-center gap-4 text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Sign in</h1>
          <p className="text-sm text-ink-soft">
            Buyers and merchants both sign in with Google — this store assigns your role at first login. Software
            agents never sign in here; see <span className="font-medium text-ink">My Agents</span> once you&rsquo;re
            in.
          </p>
          {error && (
            <div className="w-full rounded-lg border border-danger/25 bg-danger-soft px-3 py-2 text-left text-sm text-danger">
              {error}
            </div>
          )}
          <a
            href={googleLoginUrl()}
            className="inline-flex w-full items-center justify-center gap-2.5 rounded-md border border-line-strong bg-surface px-4 py-2.5 text-sm font-medium text-ink transition-colors duration-150 hover:bg-black/[0.02] focus-visible:outline-2 focus-visible:outline-accent"
          >
            <LogIn size={15} />
            Sign in with Google
          </a>

          {demoPrincipals.length > 0 && (
            <div className="mt-2 w-full border-t border-line pt-4 text-left">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium uppercase tracking-wide text-ink-soft">Or explore the demo</span>
                <span className="rounded-full border border-warning/30 bg-warning-soft px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-warning">
                  Dev only
                </span>
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-ink-soft">
                Pre-seeded accounts so you can look around without registering a Google OAuth client. Available only
                when the server runs with <code className="font-mono">APP_ENV=development</code> — the same gate that
                controls chaos injection.
              </p>
              {demoError && (
                <div className="mt-2 rounded-lg border border-danger/25 bg-danger-soft px-3 py-2 text-sm text-danger">
                  {demoError}
                </div>
              )}
              <div className="mt-3 flex flex-col gap-2">
                {demoPrincipals.map((principal) => {
                  const Icon = ROLE_ICONS[principal.role];
                  return (
                    <button
                      key={principal.role}
                      type="button"
                      onClick={() => handleDemoLogin(principal.role)}
                      disabled={pendingRole !== null}
                      className="flex w-full items-start gap-2.5 rounded-md border border-line-strong bg-surface px-3 py-2.5 text-left transition-colors duration-150 hover:bg-black/[0.02] focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <Icon size={15} className="mt-0.5 shrink-0 text-ink-soft" />
                      <span className="min-w-0">
                        <span className="block text-sm font-medium text-ink">
                          {pendingRole === principal.role ? "Signing in…" : `Continue as ${principal.name}`}
                        </span>
                        <span className="block text-xs leading-relaxed text-ink-soft">{principal.description}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto flex w-full max-w-sm flex-col gap-3 px-6 py-8">
          <div className="h-40 w-full animate-pulse rounded-lg bg-black/[0.05]" />
        </div>
      }
    >
      <LoginInner />
    </Suspense>
  );
}
