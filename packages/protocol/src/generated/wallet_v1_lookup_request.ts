/* Generated from /contracts by packages/protocol/scripts/generate.mjs. Do not edit. */

/**
 * Transaction lookup (platform -> operator, optional, used by reconciliation)
 */
export interface WalletV1LookupRequest {
  /**
   * @minItems 1
   * @maxItems 200
   */
  transaction_ids: [string, ...string[]];
}
