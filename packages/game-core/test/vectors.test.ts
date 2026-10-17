import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  crashFromR,
  crashFromSeed,
  displayMultiplierAt,
  estimatePayoutMinor,
  first52Bits,
  formatMultiplier,
  hexToBytes,
  roundHash,
  bytesToHex,
  verifyCommitment,
} from "../src/index";

interface Vectors {
  params: { house_edge_bp: number; max_multiplier_x10000: number; curve_lambda_per_ms: string };
  salt: string;
  r_vectors: { r: string; crash_x10000: number }[];
  seed_vectors: { seed: string; round_hash: string; r: string; crash_x10000: number }[];
  chain: string[];
  curve_samples: { t_ms: number; multiplier_x10000: number }[];
  payouts: {
    stake_minor: number;
    multiplier_x10000: number;
    max_win_minor: number | null;
    payout_minor: number;
  }[];
}

const vectors = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("../../../contracts/math/lr-crash-1/vectors.json", import.meta.url)),
    "utf8",
  ),
) as Vectors;
const { house_edge_bp: edge, max_multiplier_x10000: max } = vectors.params;

describe("LR-CRASH-1 parity with the Python reference", () => {
  it("matches r vectors", () => {
    for (const v of vectors.r_vectors) expect(crashFromR(BigInt(v.r), edge, max)).toBe(v.crash_x10000);
  });

  it("matches seed vectors", async () => {
    const salt = hexToBytes(vectors.salt);
    for (const v of vectors.seed_vectors) {
      const seed = hexToBytes(v.seed);
      const h = await roundHash(seed, salt);
      expect(bytesToHex(h)).toBe(v.round_hash);
      expect(first52Bits(h)).toBe(BigInt(v.r));
      expect(await crashFromSeed(seed, salt, edge, max)).toBe(v.crash_x10000);
    }
  });

  it("verifies chain commitments", async () => {
    const chain = vectors.chain.map(hexToBytes);
    for (let i = 0; i + 1 < chain.length; i++) {
      expect(await verifyCommitment(chain[i]!, chain[i + 1]!)).toBe(true);
    }
    expect(await verifyCommitment(chain[0]!, chain[2]!)).toBe(false);
  });

  it("matches payout vectors", () => {
    for (const v of vectors.payouts) {
      const maxWin = v.max_win_minor === null ? undefined : BigInt(v.max_win_minor);
      expect(estimatePayoutMinor(BigInt(v.stake_minor), v.multiplier_x10000, maxWin)).toBe(
        BigInt(v.payout_minor),
      );
    }
  });

  it("float display curve stays within one unit of the authoritative table", () => {
    for (const s of vectors.curve_samples) {
      const shown = displayMultiplierAt({ lambdaPerMs: vectors.params.curve_lambda_per_ms }, s.t_ms);
      expect(Math.abs(shown - s.multiplier_x10000)).toBeLessThanOrEqual(1);
    }
  });

  it("formats display multipliers floored to two decimals", () => {
    expect(formatMultiplier(23_456)).toBe("2.34x");
    expect(formatMultiplier(10_000)).toBe("1.00x");
  });
});
