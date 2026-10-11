"use client";
/** One independent betting panel (doc 08 §1, doc 14 §2.1). */
import {
  displayMultiplierAt,
  estimatePayoutMinor,
  formatMoney,
  formatMultiplier,
  hasLiveBet,
  parseMoney,
  toDecimalString,
  type PanelState,
} from "@luxrocket/game-core";
import { useEffect, useRef, useState } from "react";
import type { GameController } from "@/lib/controller";
import { useStore } from "@/lib/hooks";

const QUICK = [1n, 2n, 5n, 10n];

export function BetPanel({ controller, index }: { controller: GameController; index: number }) {
  const panel = useStore(controller.store, (s) => s.panels[index]);
  const session = useStore(controller.store, (s) => s.session);
  const phase = useStore(controller.store, (s) => s.round.phase);
  const exponent = session?.exponent ?? 2;
  const currency = session?.currency ?? "";
  const [stakeText, setStakeText] = useState(() => (panel ? toDecimalString(panel.stake, exponent) : ""));
  const [autoText, setAutoText] = useState(() => (panel ? (panel.autoTarget / 10_000).toFixed(2) : "2.00"));
  const cashRef = useRef<HTMLSpanElement>(null);

  // Live potential return on the CASH OUT button (estimate only; server decides).
  useEffect(() => {
    if (!panel || panel.status !== "ACTIVE") return;
    let raf = 0;
    const tick = () => {
      const { round } = controller.store.get();
      const mult = displayMultiplierAt({ lambdaPerMs: round.lambdaPerMs }, controller.clock.now() - round.launchAt);
      const est = estimatePayoutMinor(panel.stake, Math.max(mult, 10_000));
      if (cashRef.current) cashRef.current.textContent = formatMoney(est, exponent, currency);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [panel, controller, exponent, currency]);

  if (!panel || !session) return null;
  const locked = hasLiveBet(panel) || panel.status === "QUEUED";
  const min = BigInt(session.limits.min_stake);

  const commitStake = (text: string) => {
    const parsed = parseMoney(text, exponent);
    if (parsed !== null) controller.edit(index, { stake: parsed });
    else setStakeText(toDecimalString(panel.stake, exponent));
  };
  const commitAuto = (text: string) => {
    const value = Math.round(Number(text) * 100) * 100;
    if (Number.isFinite(value) && value >= 10_100) {
      controller.edit(index, { autoTarget: value });
      setAutoText((value / 10_000).toFixed(2));
    } else setAutoText((panel.autoTarget / 10_000).toFixed(2));
  };

  return (
    <section
      aria-label={`Bet panel ${index + 1}`}
      data-testid={`panel-${index}`}
      data-status={panel.status}
      className="flex flex-col gap-2 rounded-2xl border border-white/10 bg-[var(--surface)] p-2.5 backdrop-blur sm:p-3"
    >
      <div className="flex items-center gap-2">
        <label className="sr-only" htmlFor={`stake-${index}`}>Stake</label>
        <button
          type="button"
          aria-label="Decrease stake"
          disabled={locked}
          onClick={() => {
            const next = panel.stake / 2n < min ? min : panel.stake / 2n;
            controller.edit(index, { stake: next });
            setStakeText(toDecimalString(next, exponent));
          }}
          className="h-10 w-10 rounded-full bg-white/10 text-lg disabled:opacity-40"
        >
          −
        </button>
        <input
          id={`stake-${index}`}
          inputMode="decimal"
          value={stakeText}
          disabled={locked}
          onChange={(e) => setStakeText(e.target.value)}
          onBlur={(e) => commitStake(e.target.value)}
          className="h-10 min-w-0 flex-1 rounded-xl bg-black/30 px-3 text-center text-lg font-semibold tabular-nums disabled:opacity-60"
        />
        <button
          type="button"
          aria-label="Double stake"
          disabled={locked}
          onClick={() => {
            const next = panel.stake * 2n;
            controller.edit(index, { stake: next });
            setStakeText(toDecimalString(next, exponent));
          }}
          className="h-10 w-10 rounded-full bg-white/10 text-lg disabled:opacity-40"
        >
          +
        </button>
      </div>

      <div className="hidden grid-cols-4 gap-1 sm:grid">
        {QUICK.map((q) => {
          const value = min * 10n * q;
          return (
            <button
              key={q.toString()}
              type="button"
              disabled={locked}
              onClick={() => {
                controller.edit(index, { stake: value });
                setStakeText(toDecimalString(value, exponent));
              }}
              className="rounded-lg bg-white/5 py-1 text-xs tabular-nums text-[var(--text-muted)] disabled:opacity-40"
            >
              {toDecimalString(value, exponent)}
            </button>
          );
        })}
      </div>

      <div className="flex items-center justify-between gap-2 text-sm">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={panel.autoEnabled}
            disabled={locked}
            onChange={(e) => controller.edit(index, { autoEnabled: e.target.checked })}
            className="h-4 w-4 accent-[var(--accent)]"
          />
          <span className="sm:hidden">Auto</span>
          <span className="hidden sm:inline">Auto cash out at</span>
        </label>
        <input
          aria-label="Auto cash-out multiplier"
          inputMode="decimal"
          value={autoText}
          disabled={locked || !panel.autoEnabled}
          onChange={(e) => setAutoText(e.target.value)}
          onBlur={(e) => commitAuto(e.target.value)}
          className="h-8 w-20 rounded-lg bg-black/30 px-2 text-right tabular-nums disabled:opacity-50"
        />
        <span className="text-[var(--text-muted)]">x</span>
      </div>

      <ActionButton controller={controller} panel={panel} phase={phase} cashRef={cashRef} currency={currency} exponent={exponent} />
      <p className="min-h-4 text-center text-xs text-[var(--text-muted)]" aria-live="polite">
        {statusLine(panel, exponent, currency)}
      </p>
    </section>
  );
}

function ActionButton({
  controller,
  panel,
  phase,
  cashRef,
  currency,
  exponent,
}: {
  controller: GameController;
  panel: PanelState;
  phase: string;
  cashRef: React.RefObject<HTMLSpanElement | null>;
  currency: string;
  exponent: number;
}) {
  const base =
    "min-h-12 w-full rounded-2xl py-1 text-base font-bold tracking-wide transition active:scale-[0.99] disabled:opacity-60 sm:min-h-14 sm:text-lg";
  switch (panel.status) {
    case "ACTIVE":
      return (
        <button type="button" data-testid="cashout" onClick={() => controller.cashOut(panel.index)} className={`${base} bg-[var(--success)] text-black`}>
          CASH OUT <span ref={cashRef} className="block text-sm font-semibold tabular-nums" />
        </button>
      );
    case "CASHING_OUT":
      return <button type="button" disabled className={`${base} bg-[var(--success)] text-black`}>Cashing out…</button>;
    case "PLACING":
      return <button type="button" disabled className={`${base} bg-white/20`}>Placing bet…</button>;
    case "PLACED":
      return <button type="button" disabled className={`${base} bg-white/15`}>Waiting for launch</button>;
    case "QUEUED":
      return (
        <button type="button" onClick={() => controller.cancelQueued(panel.index)} className={`${base} bg-white/20`}>
          Cancel · next round
        </button>
      );
    default:
      return (
        <button type="button" data-testid="bet" onClick={() => controller.bet(panel.index)} className={`${base} bg-[var(--accent)] text-black`}>
          {phase === "BETTING_OPEN" ? "BET" : "BET (next round)"}
          <span className="block text-sm font-semibold tabular-nums">{formatMoney(panel.stake, exponent, currency)}</span>
        </button>
      );
  }
}

function statusLine(p: PanelState, exponent: number, currency: string): string {
  switch (p.status) {
    case "CASHED_OUT":
      return `Cashed out ${formatMultiplier(p.cashout ?? 10_000)} · +${formatMoney(p.payout ?? 0n, exponent, currency)}${
        p.settled ? " · credited" : " · crediting…"
      }`;
    case "LOST":
      return "Lost this round";
    case "REJECTED":
      return `Not placed (${p.error ?? "rejected"})`;
    case "REFUND_PENDING":
      return "Stake being returned…";
    case "REFUNDED":
      return "Stake returned";
    case "ACTIVE":
      return p.autoEnabled ? `Auto cash out at ${formatMultiplier(p.autoTarget)}` : "In flight";
    default:
      return "";
  }
}
