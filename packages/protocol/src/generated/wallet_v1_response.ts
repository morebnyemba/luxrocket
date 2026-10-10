/* Generated from /contracts by packages/protocol/scripts/generate.mjs. Do not edit. */

/**
 * Wallet response (operator -> platform)
 */
export interface WalletV1Response {
  status: "OK" | "REJECTED";
  transaction_id: string;
  operator_transaction_id?: string;
  /**
   * Integer amount in currency minor units, as a string
   */
  balance?: string;
  currency?: string;
  code?:
    | "INSUFFICIENT_FUNDS"
    | "PLAYER_BLOCKED"
    | "SESSION_EXPIRED"
    | "LIMIT_EXCEEDED"
    | "CURRENCY_MISMATCH"
    | "DUPLICATE_TRANSACTION"
    | "TRANSACTION_NOT_FOUND"
    | "INVALID_REQUEST"
    | "INTERNAL_ERROR";
  duplicate?: boolean;
}
