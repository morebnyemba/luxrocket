/* Generated from /contracts by packages/protocol/scripts/generate.mjs. Do not edit. */

/**
 * Create launch session response
 */
export interface OperatorV1SessionCreateResponse {
  session_id: string;
  launch_token: string;
  launch_token_expires_at: string;
  iframe_url: string;
  fragment_launch_url?: string;
  sdk_url?: string;
  sdk_integrity?: string;
}
