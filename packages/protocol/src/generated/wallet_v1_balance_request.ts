/* Generated from /contracts by packages/protocol/scripts/generate.mjs. Do not edit. */

/**
 * Wallet balance request (platform -> operator, optional endpoint)
 */
export interface WalletV1BalanceRequest {
  player_id: string;
  currency: string;
  session_id?: string;
  operator_session_token?: string;
}
