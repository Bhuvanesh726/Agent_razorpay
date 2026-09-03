"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
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
        className="fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-black text-2xl text-white shadow-lg hover:bg-gray-800"
      >
        +
      </Link>
    );
  }

  return (
    <>
      <button
        onClick={() => setOpen((v) => !v)}
        title="Chat with your shopping assistant"
        className="fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-black text-2xl text-white shadow-lg hover:bg-gray-800"
      >
        {open ? "✕" : "💬"}
      </button>
      {open && (
        <div className="fixed bottom-24 right-6 z-40 max-h-[75vh] w-[380px] max-w-[calc(100vw-2rem)] overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-2xl">
          <ChatPanel onCartChanged={onCartChanged ?? (() => {})} />
        </div>
      )}
    </>
  );
}
