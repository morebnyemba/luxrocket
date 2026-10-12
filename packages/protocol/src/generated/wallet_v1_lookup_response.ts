/* Generated from /contracts by packages/protocol/scripts/generate.mjs. Do not edit. */

/**
 * Transaction lookup response (operator -> platform)
 */
export interface WalletV1LookupResponse {
  transactions: {
    transaction_id: string;
    /**
     * VOIDED: the id was tombstoned by a rollback that arrived first; it can never apply
     */
    status: "OK" | "REJECTED" | "NOT_FOUND" | "VOIDED";
    amount?: string;
    currency?: string;
  }[];
}
