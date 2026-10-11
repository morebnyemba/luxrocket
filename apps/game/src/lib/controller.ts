/**
 * Game controller: owns the session, the real-time connection and the game state store.
 *
 * Server events are the only source of truth. The UI sends intents (bet, cash out, edit);
 * results arrive as separate events (doc 10 §3). Reconnects always use a fresh single-use
 * WS ticket, then resynchronise from an authoritative snapshot.
 */
import {
  ServerClock,
  initialPanel,
  panelReducer,
  type PanelEvent,
  type PanelState,
  type PanelStatus,
} from "@luxrocket/game-core";
import { Channel, Socket } from "phoenix";
import { ApiError, GameApi, type SessionView } from "./api";
import { RT_URL } from "./config";
import { acquireLaunchToken, postToParent } from "./launch";
import { createStore, type Store } from "./store";

export type Connection = "launching" | "connecting" | "online" | "reconnecting" | "ended" | "error";
export type RoundPhase = "WAITING" | "BETTING_OPEN" | "BETTING_CLOSED" | "FLYING" | "CRASHED" | "VOIDED";

export interface RoundView {
  id: string | null;
  number: number;
  phase: RoundPhase;
  opensAt: number;
  closeAt: number;
  launchAt: number;
  lambdaPerMs: string;
  commitment: string;
  crash: number | null;
  endReason: string | null;
  seed: string | null;
}

export interface Toast {
  id: number;
  tone: "info" | "success" | "error";
  text: string;
}

export interface GameState {
  connection: Connection;
  error: string | null;
  session: SessionView | null;
  balance: bigint | null;
  round: RoundView;
  recent: number[];
  panels: PanelState[];
  toasts: Toast[];
}

const EMPTY_ROUND: RoundView = {
  id: null,
  number: 0,
  phase: "WAITING",
  opensAt: 0,
  closeAt: 0,
  launchAt: 0,
  lambdaPerMs: "0.00006",
  commitment: "",
  crash: null,
  endReason: null,
  seed: null,
};

type Envelope<D = Record<string, unknown>> = {
  type: string;
  round_id?: string;
  seq?: number;
  pseq?: number;
  server_ts: number;
  data: D;
};

const PUBLIC_EVENTS = [
  "ROUND_OPEN",
  "BETTING_CLOSED",
  "ROCKET_LAUNCHED",
  "MULTIPLIER_UPDATE",
  "ROUND_CRASHED",
  "ROUND_VOIDED",
] as const;

const PRIVATE_EVENTS = [
  "BET_ACCEPTED",
  "BET_REJECTED",
  "CASHOUT_ACCEPTED",
  "CASHOUT_REJECTED",
  "BET_LOST",
  "SETTLEMENT_CONFIRMED",
  "SESSION_REVOKED",
  "ROUND_SNAPSHOT",
  "TIME_PONG",
] as const;

const REJECT_MESSAGES: Record<string, string> = {
  INSUFFICIENT_FUNDS: "Insufficient balance",
  BETTING_CLOSED: "Betting is closed for this round",
  STAKE_OUT_OF_RANGE: "Stake is outside the allowed range",
  PANEL_BUSY: "This panel already has a bet",
  UNCERTAIN: "Bet not placed — any deducted amount will be returned",
  LATE: "Bet missed the launch — your stake will be returned",
  EXPOSURE_LIMIT: "Bet limit reached for this round",
  OPERATOR_UNAVAILABLE: "Betting temporarily unavailable",
  RATE_LIMITED: "Too many requests — slow down",
};

export class GameController {
  readonly store: Store<GameState>;
  readonly clock = new ServerClock();
  private readonly api = new GameApi();
  private socket: Socket | null = null;
  private channel: Channel | null = null;
  private lastSeq = 0;
  private lastPseq = 0;
  private toastId = 0;
  private reconnectAttempt = 0;
  private timers: number[] = [];
  private stopped = false;
  private started = false;

  constructor() {
    this.store = createStore<GameState>({
      connection: "launching",
      error: null,
      session: null,
      balance: null,
      round: EMPTY_ROUND,
      recent: [],
      panels: [initialPanel(0, 100n), initialPanel(1, 100n)],
      toasts: [],
    });
  }

  // ---- lifecycle -------------------------------------------------------------------------

  /** Idempotent: React strict mode mounts, unmounts and remounts once in development. */
  async start(): Promise<void> {
    this.stopped = false;
    if (this.started) return;
    this.started = true;
    try {
      const launchToken = await acquireLaunchToken();
      const exchanged = await this.api.exchange(launchToken);
      this.api.setToken(exchanged.game_session_token);
      const session = exchanged.session;
      const defaultStake = BigInt(session.limits.min_stake) * 10n;
      this.store.set((s) => ({
        ...s,
        session,
        balance: exchanged.balance === null ? null : BigInt(exchanged.balance),
        panels: Array.from({ length: session.panels }, (_, i) =>
          initialPanel(i, clampStake(defaultStake, session), i === 0 ? 20_000 : 50_000),
        ),
        connection: "connecting",
      }));
      postToParent("LR_SESSION_STARTED", { session_id: session.session_id });
      this.scheduleRenewal();
      document.addEventListener("visibilitychange", this.onVisibility);
      await this.connect();
    } catch (error) {
      const code = error instanceof ApiError ? error.code : error instanceof Error ? error.message : "LAUNCH_FAILED";
      this.store.set((s) => ({ ...s, connection: "error", error: code }));
      postToParent("LR_RELAUNCH_REQUIRED", { reason: code });
    }
  }

  stop(): void {
    this.stopped = true;
    this.timers.forEach((t) => window.clearTimeout(t));
    document.removeEventListener("visibilitychange", this.onVisibility);
    this.channel?.leave();
    this.socket?.disconnect();
  }

  private scheduleRenewal(): void {
    // Renew at ~80 % of the 15-minute token lifetime.
    const t = window.setTimeout(async () => {
      try {
        const { game_session_token } = await this.api.renew();
        this.api.setToken(game_session_token);
        this.scheduleRenewal();
      } catch {
        this.end("SESSION_EXPIRED");
      }
    }, 12 * 60 * 1000);
    this.timers.push(t);
  }

  private async connect(): Promise<void> {
    if (this.stopped) return;
    let ticket: string;
    try {
      ticket = (await this.api.wsTicket()).ticket;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return this.end("SESSION_ENDED");
      return this.scheduleReconnect();
    }
    const session = this.store.get().session;
    if (!session) return;

    // Automatic reconnects are disabled: tickets are single-use, so we reconnect ourselves.
    const socket = new Socket(RT_URL, {
      params: { ticket },
      reconnectAfterMs: () => 24 * 60 * 60 * 1000,
      heartbeatIntervalMs: 15_000,
    });
    this.socket = socket;
    socket.onError(() => this.onDisconnect(socket));
    socket.onClose(() => this.onDisconnect(socket));
    socket.connect();

    const channel = socket.channel(`stream:${session.stream_id}`, { protocol: "lr.v1" });
    this.channel = channel;
    for (const ev of PUBLIC_EVENTS) channel.on(ev, (m: Envelope) => this.onPublic(m));
    for (const ev of PRIVATE_EVENTS) channel.on(ev, (m: Envelope) => this.onPrivate(m));

    channel
      .join()
      .receive("ok", (reply: Envelope<{ snapshot: Snapshot }>) => {
        this.reconnectAttempt = 0;
        this.lastPseq = 0;
        this.store.set((s) => ({ ...s, connection: "online", error: null }));
        this.applySnapshot(reply.data.snapshot);
        this.syncClock();
      })
      .receive("error", () => this.end("JOIN_REFUSED"));
  }

  private onDisconnect(socket: Socket): void {
    if (socket !== this.socket || this.stopped) return;
    socket.disconnect();
    this.socket = null;
    this.channel = null;
    if (this.store.get().connection === "ended") return;
    this.store.set((s) => ({ ...s, connection: "reconnecting" }));
    this.scheduleReconnect();
  }

  private scheduleReconnect(): void {
    const delays = [500, 1_000, 2_000, 4_000, 8_000, 10_000];
    const base = delays[Math.min(this.reconnectAttempt, delays.length - 1)] ?? 10_000;
    this.reconnectAttempt += 1;
    const t = window.setTimeout(() => void this.connect(), base * (0.75 + Math.random() * 0.5));
    this.timers.push(t);
  }

  private end(reason: string): void {
    this.store.set((s) => ({ ...s, connection: "ended", error: reason }));
    this.channel?.leave();
    this.socket?.disconnect();
    postToParent(reason === "SESSION_REVOKED" ? "LR_SESSION_REVOKED" : "LR_RELAUNCH_REQUIRED", { reason });
  }

  private onVisibility = (): void => {
    if (document.visibilityState === "visible") this.send("SYNC", {});
  };

  // ---- commands ---------------------------------------------------------------------------

  private send(type: string, data: Record<string, unknown>, roundId?: string): string {
    const commandId = crypto.randomUUID();
    this.channel?.push("cmd", { type, v: 1, command_id: commandId, ...(roundId ? { round_id: roundId } : {}), data });
    return commandId;
  }

  private syncClock(): void {
    for (let i = 0; i < 3; i++) {
      const t = window.setTimeout(() => this.send("TIME_PING", { client_ts: Date.now() }), i * 400);
      this.timers.push(t);
    }
  }

  edit(panel: number, patch: { stake?: bigint; autoEnabled?: boolean; autoTarget?: number }): void {
    this.dispatchPanel(panel, { type: "EDIT", ...patch });
  }

  /** BET pressed: place now if betting is open, otherwise queue for the next round. */
  bet(panelIndex: number): void {
    const { round, panels, session } = this.store.get();
    const panel = panels[panelIndex];
    if (!panel || !session) return;
    const error = this.validate(panel, session);
    if (error) return this.toast("error", error);
    if (round.phase === "BETTING_OPEN" && round.id && this.clock.now() < round.closeAt) {
      this.place(panelIndex, round.id);
    } else {
      this.dispatchPanel(panelIndex, { type: "QUEUE" });
    }
  }

  cancelQueued(panelIndex: number): void {
    this.dispatchPanel(panelIndex, { type: "UNQUEUE" });
  }

  cashOut(panelIndex: number): void {
    const { round, panels } = this.store.get();
    const panel = panels[panelIndex];
    if (!panel?.betId || panel.status !== "ACTIVE" || !round.id) return;
    const commandId = this.send("CASH_OUT", { bet_id: panel.betId }, round.id);
    this.dispatchPanel(panelIndex, { type: "CASHING_OUT", commandId });
  }

  private place(panelIndex: number, roundId: string): void {
    const panel = this.store.get().panels[panelIndex];
    if (!panel) return;
    const data: Record<string, unknown> = { panel: panelIndex, stake: panel.stake.toString() };
    if (panel.autoEnabled) data.auto_cashout_x10000 = panel.autoTarget;
    const commandId = this.send("PLACE_BET", data, roundId);
    this.dispatchPanel(panelIndex, { type: "PLACE", roundId, commandId });
  }

  private validate(panel: PanelState, session: SessionView): string | null {
    const min = BigInt(session.limits.min_stake);
    const max = BigInt(session.limits.max_stake);
    if (panel.stake < min || panel.stake > max) return "Stake is outside the allowed range";
    if (panel.autoEnabled && (panel.autoTarget < 10_100 || panel.autoTarget % 100 !== 0)) {
      return "Auto cash-out must be at least 1.01x";
    }
    const { balance } = this.store.get();
    if (balance !== null && panel.stake > balance) return "Insufficient balance";
    return null;
  }

  // ---- server events ----------------------------------------------------------------------

  private onPublic(m: Envelope): void {
    this.clock.hint(m.server_ts);
    if (typeof m.seq === "number") {
      if (this.lastSeq && m.seq > this.lastSeq + 1) this.send("SYNC", {});
      if (m.seq <= this.lastSeq && m.type !== "MULTIPLIER_UPDATE") return;
      this.lastSeq = Math.max(this.lastSeq, m.seq);
    }
    const d = m.data as Record<string, unknown>;
    switch (m.type) {
      case "ROUND_OPEN": {
        const roundId = m.round_id ?? null;
        this.store.set((s) => ({
          ...s,
          round: {
            ...EMPTY_ROUND,
            id: roundId,
            number: Number(d.number),
            phase: "BETTING_OPEN",
            opensAt: Number(d.opens_at),
            closeAt: Number(d.close_at),
            launchAt: Number(d.launch_at),
            commitment: String(d.commitment ?? ""),
            lambdaPerMs: String((d.curve as { lambda_per_ms?: string })?.lambda_per_ms ?? "0.00006"),
          },
        }));
        if (roundId) {
          this.forEachPanel({ type: "ROUND_OPEN", roundId });
          this.store.get().panels.forEach((p) => {
            if (p.status === "QUEUED") this.place(p.index, roundId);
          });
        }
        break;
      }
      case "BETTING_CLOSED":
        this.store.set((s) => ({ ...s, round: { ...s.round, phase: "BETTING_CLOSED" } }));
        break;
      case "ROCKET_LAUNCHED":
        this.store.set((s) => ({ ...s, round: { ...s.round, phase: "FLYING", launchAt: Number(d.launch_at) } }));
        if (m.round_id) this.forEachPanel({ type: "LAUNCHED", roundId: m.round_id });
        break;
      case "ROUND_CRASHED": {
        const crash = Number(d.crash_x10000);
        this.store.set((s) => ({
          ...s,
          round: { ...s.round, phase: "CRASHED", crash, endReason: String(d.end_reason ?? "CRASH"), seed: String(d.seed ?? "") },
          recent: [crash, ...s.recent].slice(0, 30),
        }));
        if (m.round_id) this.forEachPanel({ type: "CRASHED", roundId: m.round_id });
        break;
      }
      case "ROUND_VOIDED":
        this.store.set((s) => ({ ...s, round: { ...s.round, phase: "VOIDED", seed: String(d.seed ?? "") } }));
        if (m.round_id) this.forEachPanel({ type: "VOIDED", roundId: m.round_id });
        this.toast("info", "Round cancelled — open stakes will be returned");
        break;
    }
  }

  private onPrivate(m: Envelope): void {
    if (typeof m.pseq === "number") {
      if (this.lastPseq && m.pseq > this.lastPseq + 1) this.send("SYNC", {});
      this.lastPseq = Math.max(this.lastPseq, m.pseq);
    }
    const d = m.data as Record<string, unknown>;
    switch (m.type) {
      case "BET_ACCEPTED":
        this.dispatchPanel(Number(d.panel), {
          type: "BET_ACCEPTED",
          commandId: String(d.command_id),
          betId: String(d.bet_id),
          stake: BigInt(String(d.stake)),
        });
        if (typeof d.balance === "string") this.setBalance(d.balance);
        break;
      case "BET_REJECTED": {
        const code = String(d.code);
        this.dispatchPanel(Number(d.panel), {
          type: "BET_REJECTED",
          commandId: String(d.command_id),
          code,
          refund: d.refund === "PENDING" ? "PENDING" : "NONE",
        });
        this.toast("error", REJECT_MESSAGES[code] ?? `Bet rejected (${code})`);
        break;
      }
      case "CASHOUT_ACCEPTED":
        this.dispatchPanel(Number(d.panel), {
          type: "CASHOUT_ACCEPTED",
          betId: String(d.bet_id),
          cashout: Number(d.cashout_x10000),
          payout: BigInt(String(d.payout)),
        });
        break;
      case "CASHOUT_REJECTED":
        this.forEachPanel({ type: "CASHOUT_REJECTED", betId: String(d.bet_id), code: String(d.code) });
        break;
      case "BET_LOST":
        this.dispatchPanel(Number(d.panel), { type: "LOST", betId: String(d.bet_id) });
        break;
      case "SETTLEMENT_CONFIRMED":
        this.forEachPanel({ type: "SETTLED", betId: String(d.bet_id), kind: d.kind === "REFUND" ? "REFUND" : "CREDIT" });
        if (typeof d.balance === "string") this.setBalance(d.balance);
        postToParent("LR_BALANCE_HINT");
        break;
      case "SESSION_REVOKED":
        this.end("SESSION_REVOKED");
        break;
      case "ROUND_SNAPSHOT":
        this.applySnapshot(d as unknown as Snapshot);
        break;
      case "TIME_PONG":
        this.clock.sample(Number(d.client_ts), Date.now(), Number(d.server_ts));
        break;
    }
  }

  private applySnapshot(snap: Snapshot): void {
    this.lastSeq = snap.seq ?? this.lastSeq;
    const r = snap.round;
    if (r) {
      const phase = (["BETTING_OPEN", "BETTING_CLOSED", "FLYING", "CRASHED", "VOIDED"].includes(r.state)
        ? r.state
        : "WAITING") as RoundPhase;
      this.store.set((s) => ({
        ...s,
        round: {
          ...EMPTY_ROUND,
          id: r.round_id,
          number: r.number,
          phase,
          opensAt: r.opens_at ?? 0,
          closeAt: r.close_at ?? 0,
          launchAt: r.launch_at ?? 0,
          commitment: r.commitment ?? "",
          lambdaPerMs: r.curve?.lambda_per_ms ?? "0.00006",
          crash: r.crash_x10000 ?? null,
          seed: r.seed ?? null,
        },
        recent: snap.recent_crashes ?? s.recent,
      }));
      for (const b of snap.player_bets ?? []) {
        const status = mapSnapshotStatus(b.status);
        if (status) {
          this.dispatchPanel(b.panel, {
            type: "RESTORE",
            status,
            betId: b.bet_id ?? null,
            roundId: r.round_id,
            commandId: b.command_id ?? null,
            cashout: b.cashout_x10000 ?? null,
            payout: b.payout ? BigInt(b.payout) : null,
          });
        }
      }
    }
  }

  // ---- helpers ----------------------------------------------------------------------------

  private dispatchPanel(index: number, event: PanelEvent): void {
    this.store.set((s) => {
      const current = s.panels[index];
      if (!current) return s;
      const next = panelReducer(current, event);
      if (next === current) return s;
      const panels = s.panels.slice();
      panels[index] = next;
      return { ...s, panels };
    });
  }

  private forEachPanel(event: PanelEvent): void {
    this.store.get().panels.forEach((p) => this.dispatchPanel(p.index, event));
  }

  private setBalance(value: string): void {
    this.store.set((s) => ({ ...s, balance: BigInt(value) }));
  }

  toast(tone: Toast["tone"], text: string): void {
    const id = ++this.toastId;
    this.store.set((s) => ({ ...s, toasts: [...s.toasts.slice(-2), { id, tone, text }] }));
    const t = window.setTimeout(
      () => this.store.set((s) => ({ ...s, toasts: s.toasts.filter((x) => x.id !== id) })),
      4_000,
    );
    this.timers.push(t);
  }

  verification(roundId: string) {
    return this.api.verification(roundId);
  }

  myBets() {
    return this.api.myBets();
  }
}

interface Snapshot {
  seq?: number;
  round: {
    round_id: string;
    number: number;
    state: string;
    opens_at?: number;
    close_at?: number;
    launch_at?: number;
    commitment?: string;
    curve?: { lambda_per_ms?: string };
    crash_x10000?: number;
    seed?: string;
  } | null;
  recent_crashes?: number[];
  player_bets?: Array<{
    panel: number;
    bet_id?: string;
    command_id?: string;
    status: string;
    cashout_x10000?: number | null;
    payout?: string | null;
  }>;
}

function mapSnapshotStatus(status: string): PanelStatus | null {
  switch (status) {
    case "ACCEPTED":
      return "PLACED";
    case "ACTIVE":
      return "ACTIVE";
    case "CASHED_OUT":
      return "CASHED_OUT";
    case "LOST":
      return "LOST";
    case "PENDING":
      return "PLACING";
    default:
      return null;
  }
}

function clampStake(stake: bigint, session: SessionView): bigint {
  const min = BigInt(session.limits.min_stake);
  const max = BigInt(session.limits.max_stake);
  return stake < min ? min : stake > max ? max : stake;
}
