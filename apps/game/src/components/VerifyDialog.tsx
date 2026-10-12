"use client";
/** In-browser round verification (doc 07 §6): recompute the crash point from public data. */
import { bytesToHex, chainNext, crashFromSeed, formatMultiplier, hexToBytes } from "@luxrocket/game-core";
import { useEffect, useState } from "react";
import type { RoundVerification } from "@/lib/api";
import type { GameController } from "@/lib/controller";

type Check = { commitment: boolean; crash: boolean; computed: number };

export function VerifyDialog({ controller, roundId, onClose }: { controller: GameController; roundId: string; onClose: () => void }) {
  const [data, setData] = useState<RoundVerification | null>(null);
  const [check, setCheck] = useState<Check | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    controller
      .verification(roundId)
      .then(async (v) => {
        if (!alive) return;
        setData(v);
        const seed = hexToBytes(v.seed);
        const computed = await crashFromSeed(seed, hexToBytes(v.salt), v.house_edge_bp ?? 300, v.max_multiplier_x10000 ?? 100_000_000);
        const commitment = bytesToHex(await chainNext(seed)) === v.commitment;
        if (alive) setCheck({ commitment, crash: computed === v.crash_x10000, computed });
      })
      .catch(() => alive && setError("Verification data is not available yet. Try again in a moment."));
    return () => {
      alive = false;
    };
  }, [controller, roundId]);

  return (
    <Dialog title="Verify round" onClose={onClose}>
      {error && <p className="text-[var(--danger)]">{error}</p>}
      {!data && !error && <p>Loading…</p>}
      {data && (
        <div className="space-y-3 text-sm">
          <p>
            Round #{data.number} crashed at <strong>{formatMultiplier(data.crash_x10000 ?? 10_000)}</strong>. Before betting opened,
            the platform published a commitment; after the crash it revealed the seed. Your browser now checks both.
          </p>
          <Field label="Commitment (published before the round)" value={data.commitment} />
          <Field label="Revealed seed" value={data.seed} />
          <Field label="Chain salt" value={data.salt} />
          <p className="text-[var(--text-muted)]">
            Formula {data.formula_version}: HMAC-SHA256(seed, salt) → first 52 bits → crash point with a {(data.house_edge_bp ?? 0) / 100}% edge.
          </p>
          {check && (
            <ul className="space-y-1" data-testid="verify-result">
              <li>{check.commitment ? "✓" : "✗"} SHA-256(seed) equals the commitment</li>
              <li>
                {check.crash ? "✓" : "✗"} Recomputed crash point {formatMultiplier(check.computed)} matches
              </li>
            </ul>
          )}
        </div>
      )}
    </Dialog>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wider text-[var(--text-muted)]">{label}</p>
      <p className="break-all font-mono text-xs">{value}</p>
    </div>
  );
}

export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div role="dialog" aria-modal="true" aria-label={title} className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-3 sm:items-center">
      <div className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-[#0e1220] p-5 shadow-2xl">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-bold">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="h-9 w-9 rounded-full bg-white/10">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
