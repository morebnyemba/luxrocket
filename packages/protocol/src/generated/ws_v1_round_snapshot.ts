/* Generated from /contracts by packages/protocol/scripts/generate.mjs. Do not edit. */

/**
 * ROUND_SNAPSHOT
 */
export interface WsV1RoundSnapshot {
  stream_id: string;
  seq: number;
  server_ts: number;
  round: {
    round_id: string;
    number: number;
    state: "PENDING" | "BETTING_OPEN" | "BETTING_CLOSED" | "FLYING" | "CRASHED" | "VOIDED";
    opens_at?: number;
    close_at?: number;
    launch_at?: number;
    commitment?: string;
    curve?: {
      kind: "exp";
      lambda_per_ms: string;
      table_hash: string;
    };
    /**
     * Present ONLY when state is CRASHED
     */
    crash_x10000?: number;
    /**
     * Present ONLY when state is CRASHED or VOIDED
     */
    seed?: string;
  };
  player_bets?: {
    panel: number;
    bet_id?: string;
    status: "PENDING" | "ACCEPTED" | "ACTIVE" | "CASHED_OUT" | "LOST" | "REJECTED" | "REFUND_PENDING" | "REFUNDED";
    /**
     * Positive integer amount in minor units, as a string
     */
    stake?: string;
    /**
     * Multiplier in ten-thousandths restricted to the 0.01x grid
     */
    auto_cashout_x10000?: number;
    /**
     * Multiplier in ten-thousandths (10000 = 1.00x)
     */
    cashout_x10000?: number;
    /**
     * Integer amount in currency minor units, as a string
     */
    payout?: string;
    settlement?: "NONE" | "PENDING" | "CONFIRMED";
  }[];
  /**
   * @maxItems 30
   *
   * Items: Multiplier in ten-thousandths restricted to the 0.01x grid
   */
  recent_crashes?: number[];
}
