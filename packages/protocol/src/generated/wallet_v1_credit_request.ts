/* Generated from /contracts by packages/protocol/scripts/generate.mjs. Do not edit. */

/**
 * Wallet credit request (platform -> operator)
 */
export interface WalletV1CreditRequest {
  transaction_id: string;
  debit_transaction_id: string;
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
  type: "WIN";
  /**
   * Multiplier in ten-thousandths (10000 = 1.00x)
   */
  multiplier_x10000: number;
  created_at: string;
}
