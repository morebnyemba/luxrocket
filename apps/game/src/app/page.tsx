// The game is only reachable through an operator launch (doc 11). This page explains that.
export default function Home() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-3 p-6 text-center">
      <p className="text-sm font-black tracking-[0.3em] text-[var(--accent)]">LUX ROCKET</p>
      <p className="max-w-md text-[var(--text-muted)]">
        Open the game from an operator site. For local development, run <code>make demo-launch</code> to get a sandbox launch link.
      </p>
    </main>
  );
}
