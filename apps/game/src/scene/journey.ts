/**
 * Journey map (doc 14 §4.1): presentation only. Position along the path is proportional to
 * ln(multiplier), so milestones arrive at roughly regular time intervals. Reaching a planet is
 * never a reward, and crashes near a planet are rendered like any other crash.
 */
export interface Milestone {
  key: string;
  label: string;
  /** Multiplier x10000 at which the rocket passes the body. */
  at: number;
  /** Real distance description (light-based units are distances, not times). */
  distance: string;
}

export const MILESTONES: Milestone[] = [
  { key: "orbit", label: "Earth orbit", at: 12_000, distance: "400 km" },
  { key: "moon", label: "Passing the Moon", at: 20_000, distance: "≈ 1.3 light-seconds" },
  { key: "mars", label: "Passing Mars", at: 50_000, distance: "≈ 3–22 light-minutes" },
  { key: "jupiter", label: "Passing Jupiter", at: 200_000, distance: "≈ 33–54 light-minutes" },
  { key: "saturn", label: "Passing Saturn", at: 500_000, distance: "≈ 1.1–1.5 light-hours" },
  { key: "deep", label: "Deep space", at: 1_000_000, distance: "Outer solar system" },
  { key: "helio", label: "Heliopause", at: 10_000_000, distance: "≈ 16–17 light-hours" },
];

/** World units of altitude per unit of ln(multiplier). */
export const ALTITUDE_SCALE = 60;

export const altitudeFor = (multiplierX10000: number): number =>
  Math.log(Math.max(multiplierX10000, 10_000) / 10_000) * ALTITUDE_SCALE;

export function milestoneAt(multiplierX10000: number): Milestone | null {
  let current: Milestone | null = null;
  for (const m of MILESTONES) if (multiplierX10000 >= m.at) current = m;
  return current;
}
