/** Rendering quality tiers (doc 14 §4.4). Initial guess from device hints, then measured. */
export type Tier = "low" | "medium" | "high";

export interface TierSettings {
  dpr: number;
  stars: number;
  exhaust: number;
  antialias: boolean;
  sphereSegments: number;
}

export const TIERS: Record<Tier, TierSettings> = {
  low: { dpr: 1, stars: 1_500, exhaust: 120, antialias: false, sphereSegments: 24 },
  medium: { dpr: 1.5, stars: 4_000, exhaust: 300, antialias: false, sphereSegments: 40 },
  high: { dpr: 2, stars: 9_000, exhaust: 700, antialias: true, sphereSegments: 64 },
};

export function initialTier(): Tier {
  const nav = navigator as Navigator & { deviceMemory?: number };
  const memory = nav.deviceMemory ?? 4;
  const cores = nav.hardwareConcurrency ?? 4;
  const small = Math.min(window.screen.width, window.screen.height) < 500;
  if (memory <= 2 || cores <= 4) return "low";
  if (memory >= 8 && cores >= 8 && !small) return "high";
  return "medium";
}

export function lower(tier: Tier): Tier {
  return tier === "high" ? "medium" : "low";
}
