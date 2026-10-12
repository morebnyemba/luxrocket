"use client";

import { Card, Notice, Status, Table, multiplier, toneFor, useResource } from "@luxrocket/console-kit";
import Link from "next/link";

import { Shell } from "@/components/Shell";
import { api } from "@/lib/api";

type Round = { round_id: string; stream: string; number: number; state: string; crash_x10000: number | null; outcome_verified: boolean | null; settlement_status: string; bets: number };

function Body() {
  const { data, error } = useResource<{ rounds: Round[] }>(api, "rounds");
  if (error) return <Notice tone="critical">{error}</Notice>;
  return (
    <Card title="Finished rounds">
      <p className="mb-3 text-sm text-[var(--text-muted)]">Read-only by design: no console action can change a round or its outcome.</p>
      {data && (
        <Table head={["Stream", "#", "Result", "Verified", "Settlement", "Bets", ""]} empty={!data.rounds.length}>
          {data.rounds.map((r) => (
            <tr key={r.round_id}>
              <td>{r.stream}</td>
              <td className="tabular">{r.number}</td>
              <td className="tabular">{r.state === "VOIDED" ? "Voided" : multiplier(r.crash_x10000)}</td>
              <td><Status tone={r.outcome_verified ? "good" : "critical"}>{r.outcome_verified ? "Verified" : "Not verified"}</Status></td>
              <td><Status tone={toneFor(r.settlement_status)}>{r.settlement_status}</Status></td>
              <td className="tabular">{r.bets}</td>
              <td><Link className="underline" href={`/rounds/detail?id=${r.round_id}`}>Journal</Link></td>
            </tr>
          ))}
        </Table>
      )}
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
