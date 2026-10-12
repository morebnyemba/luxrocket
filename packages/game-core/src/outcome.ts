/**
 * LR-CRASH-1 verification (doc 07 §2, §6). Exact BigInt arithmetic; HMAC via WebCrypto so it
 * runs in browsers (round verification page) and Node 22. Must agree bit-for-bit with the
 * Python reference implementation (contracts/math/lr-crash-1/vectors.json).
 */
import { GRID } from "./multiplier";

export const FORMULA_VERSION = "LR-CRASH-1";
const D = 1n << 52n;

export function first52Bits(digest: Uint8Array): bigint {
  if (digest.length < 7) throw new RangeError("digest too short");
  let v = 0n;
  for (let i = 0; i < 7; i++) v = (v << 8n) | BigInt(digest[i] as number);
  return v >> 4n;
}

export function crashFromR(r: bigint, houseEdgeBp: number, maxMultiplierX10000: number): number {
  if (r < 0n || r >= D) throw new RangeError("r out of range");
  if (houseEdgeBp < 0 || houseEdgeBp >= 10_000) throw new RangeError("house edge out of range");
  if (maxMultiplierX10000 % GRID !== 0 || maxMultiplierX10000 < 101 * GRID) {
    throw new RangeError("max multiplier must be on the 0.01x grid and >= 1.01x");
  }
  let raw = (100n * BigInt(10_000 - houseEdgeBp) * D) / (10_000n * (D - r));
  const cap = BigInt(maxMultiplierX10000 / GRID);
  if (raw < 100n) raw = 100n;
  if (raw > cap) raw = cap;
  return Number(raw) * GRID;
}

/** Copy into an ArrayBuffer-backed view, as WebCrypto's BufferSource requires. */
const buf = (u: Uint8Array): Uint8Array<ArrayBuffer> => new Uint8Array(u);

const subtle = (): SubtleCrypto => {
  const c = globalThis.crypto;
  if (!c?.subtle) throw new Error("WebCrypto unavailable");
  return c.subtle;
};

export async function roundHash(seed: Uint8Array, salt: Uint8Array): Promise<Uint8Array> {
  const key = await subtle().importKey("raw", buf(seed), { name: "HMAC", hash: "SHA-256" }, false, [
    "sign",
  ]);
  return new Uint8Array(await subtle().sign("HMAC", key, buf(salt)));
}

export async function crashFromSeed(
  seed: Uint8Array,
  salt: Uint8Array,
  houseEdgeBp: number,
  maxMultiplierX10000: number,
): Promise<number> {
  return crashFromR(first52Bits(await roundHash(seed, salt)), houseEdgeBp, maxMultiplierX10000);
}

export async function chainNext(seed: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await subtle().digest("SHA-256", buf(seed)));
}

/** A round's commitment is the previous round's revealed seed (or the chain terminal). */
export async function verifyCommitment(revealed: Uint8Array, commitment: Uint8Array): Promise<boolean> {
  const next = await chainNext(revealed);
  return next.length === commitment.length && next.every((b, i) => b === commitment[i]);
}

export const hexToBytes = (hex: string): Uint8Array => {
  if (hex.length % 2 !== 0 || /[^0-9a-f]/i.test(hex)) throw new RangeError("invalid hex");
  return Uint8Array.from(hex.match(/../g) ?? [], (b) => parseInt(b, 16));
};

export const bytesToHex = (bytes: Uint8Array): string =>
  Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
