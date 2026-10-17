/* Generated from /contracts by packages/protocol/scripts/generate.mjs. Do not edit. */

/**
 * PLACE_BET command
 */
export interface WsV1PlaceBet {
  type: "PLACE_BET";
  v: 1;
  command_id: string;
  round_id: string;
  data: {
    panel: number;
    /**
     * Positive integer amount in minor units, as a string
     */
    stake: string;
    /**
     * Multiplier in ten-thousandths restricted to the 0.01x grid
     */
    auto_cashout_x10000?: number;
  };
}
