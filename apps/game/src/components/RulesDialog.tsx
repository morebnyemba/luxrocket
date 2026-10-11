"use client";
import { Dialog } from "./VerifyDialog";

/** Rules and RTP disclosure (doc 15 §6). Text is subject to certification review. */
export function RulesDialog({ onClose, maxWin }: { onClose: () => void; maxWin: string }) {
  return (
    <Dialog title="How to play" onClose={onClose}>
      <div className="space-y-3 text-sm leading-relaxed">
        <p>Place up to two bets before launch. The multiplier rises as the rocket climbs. Cash out any time before it explodes to win your stake times the multiplier.</p>
        <ul className="list-disc space-y-1 pl-5">
          <li>Return to player (RTP): <strong>97%</strong> for every strategy. House edge 3%.</li>
          <li>The rocket can explode on the launchpad at 1.00x (about 3.96% of rounds).</li>
          <li>Auto cash out pays exactly your target if the rocket reaches it — including when it explodes at exactly that multiplier.</li>
          <li>Manual cash outs are paid at the multiplier, to four decimal places, at the moment the server receives your request.</li>
          <li>Maximum multiplier 10,000x. Maximum win per bet: {maxWin}. Reaching either cashes out automatically.</li>
          <li>If a technical failure interrupts a round, the round is cancelled: open stakes are returned and cash outs already confirmed are paid.</li>
          <li>Planets are scenery only. Passing one does not change your odds or your winnings.</li>
          <li>Every round can be verified: the outcome is committed before betting opens.</li>
        </ul>
        <p className="text-[var(--text-muted)]">Play responsibly. Set limits with your operator.</p>
      </div>
    </Dialog>
  );
}
