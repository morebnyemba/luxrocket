"use client";
/**
 * Scene + multiplier HUD. Per-frame values are written straight to DOM refs from the
 * animation loop, never through React state (doc 14 §2).
 */
import { displayMultiplierAt, formatMultiplier } from "@luxrocket/game-core";
import { useEffect, useRef, useState } from "react";
import type { GameController } from "@/lib/controller";
import { useStore } from "@/lib/hooks";
import { milestoneAt } from "@/scene/journey";
import { initialTier } from "@/scene/quality";
import type { RocketScene } from "@/scene/RocketScene";

export function Stage({ controller, reducedMotion }: { controller: GameController; reducedMotion: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const multRef = useRef<HTMLParagraphElement>(null);
  const subRef = useRef<HTMLParagraphElement>(null);
  const [noWebGL, setNoWebGL] = useState(false);
  const phase = useStore(controller.store, (s) => s.round.phase);

  useEffect(() => {
    let scene: RocketScene | null = null;
    let raf = 0;
    let observer: ResizeObserver | null = null;
    let cancelled = false;

    // Three.js loads after the HUD is interactive (doc 14 §4.5).
    import("@/scene/RocketScene")
      .then(({ RocketScene }) => {
        if (cancelled || !canvasRef.current) return;
        try {
          scene = new RocketScene(canvasRef.current, initialTier());
        } catch {
          setNoWebGL(true);
        }
        observer = new ResizeObserver(([entry]) => {
          if (entry) scene?.resize(entry.contentRect.width, entry.contentRect.height);
        });
        if (wrapRef.current) observer.observe(wrapRef.current);
      })
      .catch(() => setNoWebGL(true));

    let lastMilestone: string | null = null;
    const loop = () => {
      const { round } = controller.store.get();
      const now = controller.clock.now();
      let mult = 10_000;
      let main = "";
      let sub = "";
      if (round.phase === "FLYING") {
        mult = displayMultiplierAt({ lambdaPerMs: round.lambdaPerMs }, now - round.launchAt);
        main = formatMultiplier(mult);
        const ms = milestoneAt(mult);
        sub = ms ? `${ms.label} · ${ms.distance}` : "Ascending";
        if (ms && ms.key !== lastMilestone) lastMilestone = ms.key;
      } else if (round.phase === "CRASHED" && round.crash !== null) {
        mult = round.crash;
        main = formatMultiplier(round.crash);
        sub = round.endReason === "MAX_MULTIPLIER" ? "Journey complete" : "Exploded";
        lastMilestone = null;
      } else if (round.phase === "BETTING_OPEN" || round.phase === "BETTING_CLOSED") {
        const seconds = Math.max(0, (round.launchAt - now) / 1000);
        main = `${seconds.toFixed(1)}s`;
        sub = round.phase === "BETTING_OPEN" ? "Place your bets" : "Launching…";
      } else if (round.phase === "VOIDED") {
        main = "—";
        sub = "Round cancelled";
      } else {
        main = "…";
        sub = "Waiting for the next round";
      }
      if (multRef.current && multRef.current.textContent !== main) multRef.current.textContent = main;
      if (subRef.current && subRef.current.textContent !== sub) subRef.current.textContent = sub;
      scene?.render({ phase: round.phase, multiplierX10000: mult, reducedMotion });
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      observer?.disconnect();
      scene?.dispose();
    };
  }, [controller, reducedMotion]);

  const crashed = phase === "CRASHED";
  const flying = phase === "FLYING";
  return (
    <div
      ref={wrapRef}
      className="relative min-h-[34dvh] flex-1 overflow-hidden rounded-2xl bg-[#0b1020]"
      style={{ containerType: "inline-size" }}
    >
      {!noWebGL && <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-hidden="true" />}
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-b from-transparent via-transparent to-black/40 text-center">
        <p
          ref={multRef}
          data-testid="multiplier"
          aria-hidden={flying ? "true" : "false"}
          className={`font-black tabular-nums tracking-tight drop-shadow-[0_4px_24px_rgba(0,0,0,0.6)] text-[clamp(48px,14cqi,128px)] ${
            crashed ? "text-[var(--danger)]" : flying ? "text-white" : "text-[var(--accent)]"
          }`}
        />
        <p ref={subRef} className="mt-1 text-sm font-medium uppercase tracking-[0.2em] text-white/80" />
      </div>
    </div>
  );
}
