"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { MessageCircle, Plus, X } from "lucide-react";
import ChatPanel from "@/components/ChatPanel";
import { fetchAgents } from "@/lib/api";

interface Props {
  onCartChanged?: () => void;
}

// Reachable from every buyer page — routes to agent creation instead of
// opening chat when the buyer has no agent yet, per Layer 4.8's spec.
// Reuses the existing Layer 4.7 ChatPanel wholesale rather than rebuilding
// a second chat surface; see docs/048-demand-loop.md.
export default function FloatingChatLauncher({ onCartChanged }: Props) {
  const [hasAgent, setHasAgent] = useState<boolean | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    fetchAgents()
      .then((agents) => setHasAgent(agents.length > 0))
      .catch(() => setHasAgent(false));
  }, []);

  if (hasAgent === null) return null;

  if (!hasAgent) {
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
          <ChatPanel onCartChanged={onCartChanged ?? (() => {})} />
        </div>
      )}
    </>
  );
}
