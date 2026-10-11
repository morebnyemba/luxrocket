"use client";

import { Shell } from "@/components/Shell";
import { Card, Mono, multiplier, Notice, Status, Table, toneFor } from "@luxrocket/console-kit";
import { useResource } from "@/lib/hooks";

type Round = {
  round_id: string;
  number: number;
  state: string;
  crash_x10000: number | null;
  outcome_verified: boolean | null;
  commitment: string;
  seed: string;
  settlement_status: string;
  your_bets: number;
};

function Body() {
  const { data, error } = useResource<{ rounds: Round[] }>("rounds");
  if (error) return <Notice tone="critical">{error}</Notice>;
  if (!data) return <p className="text-sm text-[var(--text-muted)]">Loading…</p>;
  return (
    <Card title="Finished rounds (newest first)">
      <Table head={["#", "Result", "Verified", "Settlement", "Your bets", "Seed (verify: sha256(seed) = commitment)"]} empty={!data.rounds.length}>
        {data.rounds.map((r) => (
          <tr key={r.round_id}>
            <td className="tabular">{r.number}</td>
            <td className="tabular">{r.state === "VOIDED" ? "Voided" : multiplier(r.crash_x10000)}</td>
            <td>
              <Status tone={r.outcome_verified ? "good" : "critical"}>{r.outcome_verified ? "Verified" : "Not verified"}</Status>
            </td>
            <td><Status tone={toneFor(r.settlement_status)}>{r.settlement_status}</Status></td>
            <td className="tabular">{r.your_bets}</td>
            <td><Mono>{r.seed}</Mono></td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}

export default function RoundsPage() {
  return (
    <Shell title="Rounds">
      <Body />
    </Shell>
  );
}
