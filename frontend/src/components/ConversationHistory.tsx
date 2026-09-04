"use client";

import { useEffect, useState } from "react";
import { Archive, ArchiveRestore, MessageSquare } from "lucide-react";
import { archiveAgentConversation, fetchAgentConversations } from "@/lib/api";
import type { ConversationSummary } from "@/lib/types";

interface Props {
  credentialId: string;
  activeSessionId: string;
  onOpen: (sessionId: string) => void;
}

/** "2 hours ago". Deliberately coarse — a history list needs recency, not precision. */
export function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  // The API serialises naive UTC timestamps, which Date() would otherwise read
  // as local time and render as "in 5 hours".
  const withZone = /[zZ]|[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`;
  const then = new Date(withZone).getTime();
  if (Number.isNaN(then)) return "unknown";

  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 45) return "just now";

  const units: [number, Intl.RelativeTimeFormatUnit][] = [
    [60, "second"],
    [60, "minute"],
    [24, "hour"],
    [7, "day"],
    [4.35, "week"],
    [12, "month"],
    [Number.POSITIVE_INFINITY, "year"],
  ];

  let value = seconds;
  for (const [step, unit] of units) {
    if (Math.abs(value) < step || unit === "year") {
      return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(-Math.round(value), unit);
    }
    value /= step;
  }
  return "unknown";
}

export default function ConversationHistory({ credentialId, activeSessionId, onOpen }: Props) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Deferred to a microtask so these setState calls don't run synchronously
    // inside the effect body — same pattern as OrderDetailModal.tsx.
    Promise.resolve().then(() => {
      if (cancelled) return;
      setLoading(true);
      setError(null);
      fetchAgentConversations(credentialId, showArchived)
        .then((rows) => {
          if (!cancelled) setConversations(rows);
        })
        .catch((e) => {
          if (!cancelled) setError(e instanceof Error ? e.message : "Could not load history.");
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    });
    return () => {
      cancelled = true;
    };
  }, [credentialId, showArchived]);

  async function toggleArchive(session: ConversationSummary) {
    setBusyId(session.session_id);
    try {
      await archiveAgentConversation(credentialId, session.session_id, !session.archived);
      const rows = await fetchAgentConversations(credentialId, showArchived);
      setConversations(rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update this conversation.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="flex flex-col gap-2 border-t border-line pt-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-ink-soft">
          This agent&rsquo;s conversations
        </span>
        <button
          type="button"
          onClick={() => setShowArchived((v) => !v)}
          className="rounded-md px-1.5 py-0.5 text-[11px] font-medium text-ink-soft transition-colors duration-150 hover:bg-black/[0.04] hover:text-ink"
        >
          {showArchived ? "Hide archived" : "Show archived"}
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-danger/25 bg-danger-soft px-3 py-2 text-xs text-danger">{error}</div>
      )}

      {loading ? (
        <div className="h-16 animate-pulse rounded-md bg-black/[0.05]" />
      ) : conversations.length === 0 ? (
        <p className="py-2 text-xs text-ink-faint">
          No conversations yet. Ask this agent for something and it will show up here.
        </p>
      ) : (
        <ul className="flex max-h-56 flex-col gap-1 overflow-y-auto">
          {conversations.map((c) => {
            const isActive = c.session_id === activeSessionId;
            return (
              <li key={c.session_id} className="flex items-stretch gap-1">
                <button
                  type="button"
                  onClick={() => onOpen(c.session_id)}
                  className={`flex min-w-0 flex-1 flex-col items-start rounded-md px-2 py-1.5 text-left transition-colors duration-150 hover:bg-black/[0.04] focus-visible:outline-2 focus-visible:outline-accent ${
                    isActive ? "bg-black/[0.04]" : ""
                  }`}
                >
                  {/* Titles are derived from user text and rewritten by a model.
                      React escapes them on render; the server caps their length. */}
                  <span className="w-full truncate text-sm text-ink">
                    {c.title ?? "Untitled conversation"}
                  </span>
                  <span className="flex items-center gap-1.5 text-[11px] text-ink-faint">
                    <MessageSquare size={11} />
                    {c.message_count}
                    <span aria-hidden>·</span>
                    {relativeTime(c.last_active_at)}
                    {isActive && <span className="font-medium text-accent">· current</span>}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => toggleArchive(c)}
                  disabled={busyId === c.session_id}
                  title={c.archived ? "Restore" : "Archive"}
                  aria-label={c.archived ? "Restore conversation" : "Archive conversation"}
                  className="shrink-0 rounded-md px-1.5 text-ink-faint transition-colors duration-150 hover:bg-black/[0.04] hover:text-ink disabled:opacity-50"
                >
                  {c.archived ? <ArchiveRestore size={13} /> : <Archive size={13} />}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
