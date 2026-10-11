// Display helpers. Amounts arrive as integer minor-unit strings; never parse them as floats.

const EXPONENT: Record<string, number> = { JPY: 0, KRW: 0, BHD: 3, KWD: 3 };

export function money(minor: string | null | undefined, currency: string): string {
  if (minor == null) return "—";
  const exp = EXPONENT[currency] ?? 2;
  const neg = minor.startsWith("-");
  const digits = (neg ? minor.slice(1) : minor).padStart(exp + 1, "0");
  const whole = digits.slice(0, digits.length - exp) || "0";
  const frac = exp ? `.${digits.slice(-exp)}` : "";
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${neg ? "−" : ""}${grouped}${frac} ${currency}`;
}

export function multiplier(x10000: number | null | undefined): string {
  if (x10000 == null) return "—";
  return `${(x10000 / 10000).toFixed(2)}×`;
}

export function percentBp(bp: number | null | undefined): string {
  return bp == null ? "—" : `${(bp / 100).toFixed(2)}%`;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}
