/**
 * Multiplier units (ADR-008, doc 07). All multipliers are integers in ten-thousandths:
 * 10_000 === 1.00x. Display only — the server is authoritative for every payout.
 */
export const UNIT = 10_000;
export const GRID = 100;
export const MIN_AUTO_CASHOUT = 10_100;

export const isOnGrid = (multiplierX10000: number): boolean => multiplierX10000 % GRID === 0;

/** Estimated payout for display. Mirrors the server formula; never used to settle. */
export function estimatePayoutMinor(
  stakeMinor: bigint,
  multiplierX10000: number,
  maxWinMinor?: bigint,
): bigint {
  if (stakeMinor <= 0n) throw new RangeError("stake must be positive");
  if (multiplierX10000 < UNIT) throw new RangeError("multiplier must be >= 1.00x");
  const payout = (stakeMinor * BigInt(multiplierX10000)) / BigInt(UNIT);
  return maxWinMinor !== undefined && payout > maxWinMinor ? maxWinMinor : payout;
}

/** Two-decimal display, floored so the UI never shows more than the true value. */
export function formatMultiplier(multiplierX10000: number): string {
  const hundredths = Math.floor(multiplierX10000 / GRID);
  return `${Math.floor(hundredths / 100)}.${String(hundredths % 100).padStart(2, "0")}x`;
}
