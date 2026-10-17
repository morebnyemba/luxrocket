/* Generated from /contracts by packages/protocol/scripts/generate.mjs. Do not edit. */

/**
 * Webhook event (platform -> operator)
 */
export type OperatorV1Webhook = {
  event_id: string;
  /**
   * Open enum: consumers MUST ignore types they do not know
   */
  type: "bet.settled" | "round.settled" | "transaction.needs_attention" | "reconciliation.discrepancy";
  occurred_at: string;
  operator_id: string;
  api_version: "v1";
  data: {};
};
