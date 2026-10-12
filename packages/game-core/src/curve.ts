/**
 * Multiplier curve for presentation (doc 07 §3, doc 14 §3). The client computes the curve in
 * float from the server's launch time; the authoritative table lives on the server.
 */
import { UNIT } from "./multiplier";

export interface CurveParams {
  /** Decimal string, e.g. "0.00006" (per ms). */
  readonly lambdaPerMs: string;
}

/** Displayed multiplier (x10000) at `elapsedMs` after launch. Presentation only. */
export function displayMultiplierAt(params: CurveParams, elapsedMs: number): number {
  if (elapsedMs <= 0) return UNIT;
  return Math.floor(UNIT * Math.exp(Number(params.lambdaPerMs) * elapsedMs));
}

/** Smallest t with table[t] >= target — the crossing rule shared with the server. */
export function crossingTimeMs(table: Int32Array, targetX10000: number): number {
  let lo = 0;
  let hi = table.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if ((table[mid] as number) < targetX10000) lo = mid + 1;
    else hi = mid;
  }
  if (lo >= table.length) throw new RangeError("target beyond table");
  return lo;
}
