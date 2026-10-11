/** Money is integer minor units (bigint); strings on the wire (ADR-008). Display only. */

export function formatMoney(minor: bigint | string, exponent: number, currency: string): string {
  const value = typeof minor === "string" ? BigInt(minor) : minor;
  const negative = value < 0n;
  const abs = negative ? -value : value;
  const base = 10n ** BigInt(exponent);
  const whole = (abs / base).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const frac = exponent > 0 ? "." + (abs % base).toString().padStart(exponent, "0") : "";
  return `${negative ? "-" : ""}${whole}${frac} ${currency}`;
}

/** Parse a user-entered decimal amount ("12.5") into minor units; null if invalid. */
export function parseMoney(input: string, exponent: number): bigint | null {
  const trimmed = input.trim();
  const re = new RegExp(`^\\d{1,15}(\\.\\d{0,${exponent}})?$`);
  if (!re.test(trimmed)) return null;
  const [whole = "0", frac = ""] = trimmed.split(".");
  return BigInt(whole) * 10n ** BigInt(exponent) + BigInt((frac + "0".repeat(exponent)).slice(0, exponent) || "0");
}

/** Minor units to a plain decimal string for inputs ("12.50"). */
export function toDecimalString(minor: bigint, exponent: number): string {
  const base = 10n ** BigInt(exponent);
  const frac = exponent > 0 ? "." + (minor % base).toString().padStart(exponent, "0") : "";
  return `${minor / base}${frac}`;
}
