"use client";
import { formatMoney, formatMultiplier } from "@luxrocket/game-core";
import { useState } from "react";
import type { GameController } from "@/lib/controller";
import { useReducedMotion, useStore } from "@/lib/hooks";
import { BetPanel } from "./BetPanel";
import { RulesDialog } from "./RulesDialog";
import { Stage } from "./Stage";
import { VerifyDialog } from "./VerifyDialog";

export function GameView({ controller }: { controller: GameController }) {
  const connection = useStore(controller.store, (s) => s.connection);
  const error = useStore(controller.store, (s) => s.error);
  const session = useStore(controller.store, (s) => s.session);
  const balance = useStore(controller.store, (s) => s.balance);
  const recent = useStore(controller.store, (s) => s.recent);
  const toasts = useStore(controller.store, (s) => s.toasts);
  const phase = useStore(controller.store, (s) => s.round.phase);
  const roundNumber = useStore(controller.store, (s) => s.round.number);
  const lastRoundId = useStore(controller.store, (s) => (s.round.phase === "CRASHED" ? s.round.id : null));
  const reducedMotion = useReducedMotion();
  const [dialog, setDialog] = useState<"rules" | "verify" | null>(null);

  if (connection === "launching" || (connection === "connecting" && !session)) {
    return <Centered title="LUX ROCKET" body="Preparing for launch…" />;
  }
  if (connection === "error" || connection === "ended") {
    return (
      <Centered
        title={error === "SESSION_REVOKED" ? "Session ended by the operator" : "Session ended"}
        body="Please reopen the game from your operator's site."
      />
    );
  }
  if (!session) return null;

  return (
    <div className="mx-auto flex h-dvh w-full max-w-5xl flex-col gap-2 p-2 sm:gap-3 sm:p-3">
      <header className="flex items-center gap-2">
        <span className="text-sm font-black tracking-[0.25em] text-[var(--accent)]">LUX ROCKET</span>
        <ol aria-label="Recent crash points" className="flex flex-1 gap-1 overflow-hidden">
          {recent.slice(0, 12).map((c, i) => (
            <li key={i} className={`shrink-0 rounded-full px-2 py-0.5 text-xs tabular-nums ${c >= 20_000 ? "bg-[var(--accent-2)]/20 text-[var(--accent-2)]" : "bg-white/10 text-white/80"}`}>
              {formatMultiplier(c)}
            </li>
          ))}
        </ol>
        <span data-testid="balance" className="rounded-full bg-white/10 px-3 py-1 text-sm tabular-nums">
          {balance === null ? "—" : formatMoney(balance, session.exponent, session.currency)}
        </span>
        <button type="button" onClick={() => setDialog("rules")} className="h-8 w-8 rounded-full bg-white/10 text-sm" aria-label="Rules">
          ?
        </button>
      </header>

      {session.mode === "SANDBOX" && (
        <p className="rounded-lg bg-[var(--accent-2)]/10 px-3 py-1 text-center text-xs text-[var(--accent-2)]">Sandbox · virtual credits</p>
      )}

      <Stage controller={controller} reducedMotion={reducedMotion} />

      <div className="flex items-center justify-between text-xs text-[var(--text-muted)]">
        <span>Round #{roundNumber || "—"}</span>
        <span aria-live="polite">{phaseLabel(phase)}</span>
        {lastRoundId ? (
          <button type="button" onClick={() => setDialog("verify")} className="underline">
            Verify last round
          </button>
        ) : (
          <span />
        )}
      </div>

      <div className="grid grid-cols-2 gap-2 sm:gap-3">
        {Array.from({ length: session.panels }, (_, i) => (
          <BetPanel key={i} controller={controller} index={i} />
        ))}
      </div>

      {connection === "reconnecting" && (
        <div role="status" className="fixed inset-x-0 top-0 z-40 bg-[var(--warning)] py-1 text-center text-sm font-semibold text-black">
          Reconnecting… your bets are safe.
        </div>
      )}

      <div aria-live="assertive" className="pointer-events-none fixed inset-x-0 bottom-3 z-40 flex flex-col items-center gap-2 px-3">
        {toasts.map((t) => (
          <p key={t.id} className={`rounded-xl px-4 py-2 text-sm shadow-lg ${t.tone === "error" ? "bg-[var(--danger)] text-white" : "bg-white text-black"}`}>
            {t.text}
          </p>
        ))}
      </div>

      {dialog === "rules" && (
        <RulesDialog onClose={() => setDialog(null)} maxWin={formatMoney(session.limits.max_win, session.exponent, session.currency)} />
      )}
      {dialog === "verify" && lastRoundId && <VerifyDialog controller={controller} roundId={lastRoundId} onClose={() => setDialog(null)} />}
    </div>
  );
}

function phaseLabel(phase: string): string {
  switch (phase) {
    case "BETTING_OPEN":
      return "Betting open";
    case "BETTING_CLOSED":
      return "Betting closed";
    case "FLYING":
      return "In flight";
    case "CRASHED":
      return "Round over";
    case "VOIDED":
      return "Round cancelled";
    default:
      return "";
  }
}

function Centered({ title, body }: { title: string; body: string }) {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-3 p-6 text-center">
      <p className="text-sm font-black tracking-[0.3em] text-[var(--accent)]">{title}</p>
      <p className="text-[var(--text-muted)]">{body}</p>
    </main>
  );
}
