/* Generated from /contracts by packages/protocol/scripts/generate.mjs. Do not edit. */

/**
 * Server event envelope (lr.v1)
 */
export interface WsV1ServerEvent {
  type: string;
  v: 1;
  stream_id?: string;
  round_id?: string;
  /**
   * Per-stream sequence for public events
   */
  seq?: number;
  /**
   * Per-session sequence for private events
   */
  pseq?: number;
  /**
   * Unix epoch milliseconds
   */
  server_ts: number;
  data?: {};
}
