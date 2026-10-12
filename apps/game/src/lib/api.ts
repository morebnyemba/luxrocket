/** Game API client. The session token lives only in memory (doc 11 §4). */
import { API_URL } from "./config";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
  ) {
    super(code);
  }
}

export interface SessionView {
  session_id: string;
  operator_id: string;
  player_alias: string;
  currency: string;
  exponent: number;
  locale: string;
  mode: string;
  stream_id: string;
  panels: number;
  limits: { min_stake: string; max_stake: string; max_win: string };
}

export interface RoundVerification {
  round_id: string;
  number: number;
  state: string;
  crash_x10000: number | null;
  commitment: string;
  seed: string;
  salt: string;
  house_edge_bp: number | null;
  max_multiplier_x10000: number | null;
  formula_version: string;
  outcome_verified: boolean | null;
}

export class GameApi {
  private token: string | null = null;

  setToken(token: string): void {
    this.token = token;
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const response = await fetch(API_URL + path, {
      method,
      credentials: "omit",
      headers: {
        "Content-Type": "application/json",
        ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    const data = (await response.json().catch(() => ({}))) as Record<string, unknown>;
    if (!response.ok) throw new ApiError(response.status, String(data.code ?? "HTTP_" + response.status));
    return data as T;
  }

  exchange(launchToken: string) {
    return this.request<{ game_session_token: string; session: SessionView; balance: string | null }>(
      "POST",
      "/game/v1/sessions/exchange",
      { launch_token: launchToken },
    );
  }

  renew() {
    return this.request<{ game_session_token: string }>("POST", "/game/v1/sessions/renew");
  }

  wsTicket() {
    return this.request<{ ticket: string }>("POST", "/game/v1/ws-tickets");
  }

  config() {
    return this.request<{ session: SessionView; balance: string | null }>("GET", "/game/v1/config");
  }

  myBets() {
    return this.request<{ bets: Array<Record<string, unknown>> }>("GET", "/game/v1/me/bets");
  }

  verification(roundId: string) {
    return this.request<RoundVerification>("GET", `/game/v1/rounds/${roundId}/verification`);
  }
}
