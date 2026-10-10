/* Generated from /contracts by packages/protocol/scripts/generate.mjs. Do not edit. */

/**
 * Wallet rollback request (platform -> operator)
 */
export interface WalletV1RollbackRequest {
  transaction_id: string;
  rolled_back_transaction_id: string;
  bet_id: string;
  round_id: string;
  player_id: string;
  currency: string;
  /**
   * Positive integer amount in minor units, as a string
   */
  amount: string;
  reason: "DEBIT_UNCERTAIN" | "BET_EXCLUDED" | "ROUND_VOIDED";
}
