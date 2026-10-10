import { formatMultiplier, UNIT } from "@luxrocket/game-core";

// Placeholder shell. The playable prototype (two panels, simulated rounds) arrives in Phase B.
export default function GamePage() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4 p-4">
      <p className="text-sm uppercase tracking-[0.3em] text-[var(--text-muted)]">Lux Rocket</p>
      <p className="text-7xl font-extrabold text-[var(--accent)]" aria-label="Multiplier">
        {formatMultiplier(UNIT)}
      </p>
      <p className="text-[var(--text-muted)]">Prototype in progress</p>
    </main>
  );
}
