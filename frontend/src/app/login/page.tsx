"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { googleLoginUrl, useAuth } from "@/lib/auth";

function LoginInner() {
  const { user, loading } = useAuth();
  const searchParams = useSearchParams();
  const error = searchParams.get("error");

  if (!loading && user) {
    window.location.href = "/";
    return null;
  }

  return (
    <div className="mx-auto flex min-h-[70vh] w-full max-w-sm flex-col items-center justify-center gap-4 p-6 text-center">
      <h1 className="text-2xl font-semibold">Sign in</h1>
      <p className="text-sm text-gray-500">
        Buyers and merchants both sign in with Google — this store assigns your role at first login. Software agents
        never sign in here; see <span className="font-medium">My Agents</span> once you&rsquo;re in.
      </p>
      {error && (
        <div className="w-full rounded-md border border-red-300 bg-red-50 px-3 py-2 text-left text-sm text-red-700">
          {error}
        </div>
      )}
      <a
        href={googleLoginUrl()}
        className="rounded-md bg-black px-4 py-2 text-sm text-white hover:bg-gray-800"
      >
        Sign in with Google
      </a>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-gray-400">Loading…</div>}>
      <LoginInner />
    </Suspense>
  );
}
