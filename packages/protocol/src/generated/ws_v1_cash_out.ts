/* Generated from /contracts by packages/protocol/scripts/generate.mjs. Do not edit. */

/**
 * CASH_OUT command
 */
export interface WsV1CashOut {
  type: "CASH_OUT";
  v: 1;
  command_id: string;
  round_id: string;
  data: {
    bet_id: string;
  };
}
