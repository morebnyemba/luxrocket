/* Generated from /contracts by packages/protocol/scripts/generate.mjs. Do not edit. */

/**
 * Wallet debit request (platform -> operator)
 */
export interface WalletV1DebitRequest {
  transaction_id: string;
  bet_id: string;
  round_id: string;
  session_id?: string;
  operator_session_token?: string;
  player_id: string;
  currency: string;
  /**
   * Positive integer amount in minor units, as a string
   */
  amount: string;
  game: "lux-rocket";
  panel?: number;
  created_at: string;
}
