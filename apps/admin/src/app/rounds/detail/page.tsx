"use client";

import { Card, Mono, Notice, Status, Table, multiplier, useResource, when } from "@luxrocket/console-kit";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { Shell } from "@/components/Shell";
import { api } from "@/lib/api";

type Detail = {
  round_id: string;
  stream: string;
  number: number;
  state: string;
  crash_x10000: number | null;
  commitment: string;
  seed: string;
  salt: string;
  outcome_verified: boolean | null;
  settlement_status: string;
  journal: { seq: number; type: string; payload: Record<string, unknown>; at: string }[];
  bets_by_status: Record<string, number>;
};

function Body() {
  const id = useSearchParams().get("id");
  const { data, error } = useResource<Detail>(api, id ? `rounds/${id}` : null);
  if (error) return <Notice tone="critical">{error}</Notice>;
  if (!data) return <p className="text-sm text-[var(--text-muted)]">Loading…</p>;
  return (
    <>
      <Card title={`Round ${data.stream} #${data.number}`}>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-[var(--text-muted)]">Result</dt><dd>{data.state === "VOIDED" ? "Voided" : multiplier(data.crash_x10000)}</dd>
          <dt className="text-[var(--text-muted)]">Verified</dt><dd><Status tone={data.outcome_verified ? "good" : "critical"}>{data.outcome_verified ? "sha256(seed) = commitment, crash recomputed" : "Not verified"}</Status></dd>
          <dt className="text-[var(--text-muted)]">Commitment</dt><dd><Mono>{data.commitment}</Mono></dd>
          <dt className="text-[var(--text-muted)]">Seed</dt><dd><Mono>{data.seed}</Mono></dd>
          <dt className="text-[var(--text-muted)]">Salt</dt><dd><Mono>{data.salt}</Mono></dd>
          <dt className="text-[var(--text-muted)]">Bets</dt><dd>{Object.entries(data.bets_by_status).map(([k, v]) => `${k} ${v}`).join(" · ") || "none"}</dd>
        </dl>
      </Card>
      <Card title="Journal (authoritative facts from the real-time engine)">
        <Table head={["Seq", "Fact", "Payload", "Recorded"]} empty={!data.journal.length}>
          {data.journal.map((j) => (
            <tr key={j.seq}>
              <td className="tabular">{j.seq}</td>
              <td>{j.type}</td>
              <td><Mono>{JSON.stringify(j.payload)}</Mono></td>
              <td className="text-xs">{when(j.at)}</td>
            </tr>
          ))}
        </Table>
      </Card>
    </>
  );
}

export default function RoundDetailPage() {
  return (
    <Shell title="Round">
      <Suspense>
        <Body />
      </Suspense>
    </Shell>
  );
}
