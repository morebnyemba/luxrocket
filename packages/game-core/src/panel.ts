/**
 * Betting panel state machine (doc 08 §1.1). Pure: (state, event) -> state. Each panel is
 * independent; the shared round only drives transitions through server events.
 */

export type PanelStatus =
  | "IDLE"
  | "QUEUED"
  | "PLACING"
  | "PLACED"
  | "ACTIVE"
  | "CASHING_OUT"
  | "CASHED_OUT"
  | "LOST"
  | "REJECTED"
  | "REFUND_PENDING"
  | "REFUNDED";

export interface PanelState {
  readonly index: number;
  readonly status: PanelStatus;
  /** Stake in minor units (what the player has entered). */
  readonly stake: bigint;
  readonly autoEnabled: boolean;
  /** Auto cash-out target, x10000, on the 0.01x grid. */
  readonly autoTarget: number;
  readonly roundId: string | null;
  readonly commandId: string | null;
  readonly betId: string | null;
  readonly cashout: number | null;
  readonly payout: bigint | null;
  readonly settled: boolean;
  readonly error: string | null;
}

export type PanelEvent =
  | { type: "EDIT"; stake?: bigint; autoEnabled?: boolean; autoTarget?: number }
  | { type: "QUEUE" }
  | { type: "UNQUEUE" }
  | { type: "PLACE"; roundId: string; commandId: string }
  | { type: "ROUND_OPEN"; roundId: string }
  | { type: "BET_ACCEPTED"; commandId: string; betId: string; stake: bigint }
  | { type: "BET_REJECTED"; commandId: string; code: string; refund: "NONE" | "PENDING" }
  | { type: "LAUNCHED"; roundId: string }
  | { type: "CASHING_OUT"; commandId: string }
  | { type: "CASHOUT_ACCEPTED"; betId: string; cashout: number; payout: bigint }
  | { type: "CASHOUT_REJECTED"; betId: string; code: string }
  | { type: "LOST"; betId: string }
  | { type: "CRASHED"; roundId: string }
  | { type: "VOIDED"; roundId: string }
  | { type: "SETTLED"; betId: string; kind: "CREDIT" | "REFUND" }
  | {
      type: "RESTORE";
      status: PanelStatus;
      betId: string | null;
      roundId: string;
      commandId: string | null;
      cashout: number | null;
      payout: bigint | null;
    };

export function initialPanel(index: number, stake: bigint, autoTarget = 20_000): PanelState {
  return {
    index,
    status: "IDLE",
    stake,
    autoEnabled: false,
    autoTarget,
    roundId: null,
    commandId: null,
    betId: null,
    cashout: null,
    payout: null,
    settled: false,
    error: null,
  };
}

const TERMINAL: readonly PanelStatus[] = ["IDLE", "CASHED_OUT", "LOST", "REJECTED", "REFUNDED", "REFUND_PENDING"];

export const isEditable = (s: PanelState): boolean => s.status === "IDLE" || s.status === "REJECTED" || TERMINAL.includes(s.status);
export const hasLiveBet = (s: PanelState): boolean => ["PLACING", "PLACED", "ACTIVE", "CASHING_OUT"].includes(s.status);

function reset(s: PanelState): PanelState {
  return { ...s, status: "IDLE", roundId: null, commandId: null, betId: null, cashout: null, payout: null, settled: false, error: null };
}

export function panelReducer(s: PanelState, e: PanelEvent): PanelState {
  switch (e.type) {
    case "EDIT":
      if (!isEditable(s) && s.status !== "QUEUED") return s;
      return {
        ...s,
        stake: e.stake ?? s.stake,
        autoEnabled: e.autoEnabled ?? s.autoEnabled,
        autoTarget: e.autoTarget ?? s.autoTarget,
      };
    case "QUEUE":
      return isEditable(s) ? { ...reset(s), status: "QUEUED" } : s;
    case "UNQUEUE":
      return s.status === "QUEUED" ? reset(s) : s;
    case "PLACE":
      if (s.status !== "QUEUED" && !isEditable(s)) return s;
      return { ...reset(s), status: "PLACING", roundId: e.roundId, commandId: e.commandId };
    case "ROUND_OPEN":
      // A finished bet from an earlier round clears when the next round opens (QUEUED stays).
      if (s.roundId !== null && s.roundId !== e.roundId && !hasLiveBet(s)) return { ...reset(s), status: s.status === "QUEUED" ? "QUEUED" : "IDLE" };
      return s;
    case "BET_ACCEPTED":
      if (s.status !== "PLACING" || s.commandId !== e.commandId) return s;
      return { ...s, status: "PLACED", betId: e.betId, stake: e.stake, error: null };
    case "BET_REJECTED":
      if (s.commandId !== e.commandId || (s.status !== "PLACING" && s.status !== "PLACED")) return s;
      return { ...s, status: e.refund === "PENDING" ? "REFUND_PENDING" : "REJECTED", error: e.code };
    case "LAUNCHED":
      return s.status === "PLACED" && s.roundId === e.roundId ? { ...s, status: "ACTIVE" } : s;
    case "CASHING_OUT":
      return s.status === "ACTIVE" ? { ...s, status: "CASHING_OUT", commandId: e.commandId } : s;
    case "CASHOUT_ACCEPTED":
      if (s.betId !== e.betId) return s;
      return { ...s, status: "CASHED_OUT", cashout: e.cashout, payout: e.payout, error: null };
    case "CASHOUT_REJECTED":
      if (s.betId !== e.betId || s.status !== "CASHING_OUT") return s;
      return { ...s, status: e.code === "ROUND_ENDED" ? "LOST" : "ACTIVE", error: e.code === "ROUND_ENDED" ? null : e.code };
    case "LOST":
      return s.betId === e.betId && (s.status === "ACTIVE" || s.status === "CASHING_OUT" || s.status === "PLACED") ? { ...s, status: "LOST" } : s;
    case "CRASHED":
      if (s.roundId !== e.roundId) return s;
      if (s.status === "ACTIVE" || s.status === "CASHING_OUT") return { ...s, status: "LOST" };
      if (s.status === "PLACING" || s.status === "PLACED") return { ...s, status: "REFUND_PENDING" };
      return s;
    case "VOIDED":
      if (s.roundId !== e.roundId || !hasLiveBet(s)) return s;
      return { ...s, status: "REFUND_PENDING" };
    case "SETTLED":
      if (s.betId !== e.betId) return s;
      return { ...s, settled: true, status: e.kind === "REFUND" ? "REFUNDED" : s.status };
    case "RESTORE":
      return {
        ...s,
        status: e.status,
        betId: e.betId,
        roundId: e.roundId,
        commandId: e.commandId ?? s.commandId,
        cashout: e.cashout,
        payout: e.payout,
      };
  }
}
