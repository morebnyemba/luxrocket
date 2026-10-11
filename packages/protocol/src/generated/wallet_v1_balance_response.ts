/* Generated from /contracts by packages/protocol/scripts/generate.mjs. Do not edit. */

/**
 * Wallet balance response (operator -> platform)
 */
export interface WalletV1BalanceResponse {
  status: "OK";
  /**
   * Integer amount in currency minor units, as a string
   */
  balance: string;
  currency: string;
}
