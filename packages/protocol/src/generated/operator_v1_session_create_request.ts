/* Generated from /contracts by packages/protocol/scripts/generate.mjs. Do not edit. */

/**
 * Create launch session (operator -> platform)
 */
export interface OperatorV1SessionCreateRequest {
  player: {
    id: string;
    alias?: string;
    country: string;
  };
  currency: string;
  game: "lux-rocket";
  mode: "REAL" | "SANDBOX";
  locale?: string;
  operator_session_token?: string;
  return_url?: string;
  rg?: {
    session_reminder_minutes?: number;
    session_time_limit_minutes?: number;
  };
}
