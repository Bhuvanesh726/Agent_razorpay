"use client";

import { Suspense, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { LogIn } from "lucide-react";
import { googleLoginUrl, useAuth } from "@/lib/auth";
import { Card, CardBody } from "@/components/ui/Card";

function LoginInner() {
  const { user, loading } = useAuth();
  const searchParams = useSearchParams();
  const error = searchParams.get("error");

  useEffect(() => {
    if (!loading && user) {
      window.location.href = "/";
    }
  }, [loading, user]);

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
