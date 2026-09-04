"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { MessageCircle, Plus, X } from "lucide-react";
import ChatPanel from "@/components/ChatPanel";
import { fetchAgents } from "@/lib/api";
import type { AgentSummary } from "@/lib/types";

interface Props {
  onCartChanged?: () => void;
}

// Reachable from every buyer page — routes to agent creation instead of
// opening chat when the buyer has no usable agent yet. Interactive chat
// only runs as an EMBEDDED, ACTIVE credential (see
// app/auth/credentials_router.py's chat/confirm/quick-buy) — an EXTERNAL
// or REVOKED one doesn't count as "usable" here even if it exists.
export default function FloatingChatLauncher({ onCartChanged }: Props) {
  const [agents, setAgents] = useState<AgentSummary[] | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    fetchAgents()
      .then((all) => setAgents(all.filter((a) => a.delivery_mode === "EMBEDDED" && a.status === "ACTIVE")))
      .catch(() => setAgents([]));
  }, []);

  if (agents === null) return null;

  if (agents.length === 0) {
    return (
      <Link
        href="/agents"
        title="Create an agent to start chatting"
        className="fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-ink text-white shadow-elevated transition-colors duration-150 hover:bg-ink/90 focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
      >
        <Plus size={22} strokeWidth={2} />
      </Link>
    );
  }

  return (
    <>
      <button
        onClick={() => setOpen((v) => !v)}
        title="Chat with your shopping assistant"
        className="fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-ink text-white shadow-elevated transition-colors duration-150 hover:bg-ink/90 focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
      >
        {open ? <X size={20} /> : <MessageCircle size={20} />}
      </button>
      {open && (
        <div className="fixed bottom-24 right-6 z-40 max-h-[75vh] w-[380px] max-w-[calc(100vw-2rem)] overflow-y-auto rounded-lg border border-line bg-surface shadow-elevated">
          <ChatPanel agents={agents} onCartChanged={onCartChanged ?? (() => {})} />
        </div>
      )}
    </>
  );
}
