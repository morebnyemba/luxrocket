"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { Shell } from "@/components/Shell";
import { Card, Mono, Notice, Status, Table, toneFor } from "@/components/ui";
import { money, multiplier, when } from "@/lib/format";
import { useResource } from "@/lib/hooks";

type Detail = {
  bet_id: string;
  round_id: string;
  panel: number;
  currency: string;
  stake: string;
  status: string;
  auto_cashout_x10000: number | null;
  cashout_x10000: number | null;
  payout: string | null;
  player_id?: string;
  transactions: { transaction_id: string; type: string; amount: string; status: string }[];
  settlement: { outcome: string; status: string; payout: string; confirmed_at: string | null } | null;
  attempts: { type: string; attempt: number; outcome: string; operator_code: string; latency_ms: number; at: string }[];
};

function Body() {
  const id = useSearchParams().get("id");
  const { data, error } = useResource<Detail>(id ? `bets/${encodeURIComponent(id)}` : null);
  if (!id) return <Notice>No bet selected.</Notice>;
  if (error) return <Notice tone="critical">{error}</Notice>;
  if (!data) return <p className="text-sm text-[var(--text-muted)]">Loading…</p>;
  return (
    <>
      <Card title="Bet">
        <dl className="tabular grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-[var(--text-muted)]">Bet id</dt>
          <dd><Mono>{data.bet_id}</Mono></dd>
          <dt className="text-[var(--text-muted)]">Round</dt>
          <dd><Mono>{data.round_id}</Mono></dd>
          {data.player_id && (
            <>
              <dt className="text-[var(--text-muted)]">Player</dt>
              <dd>{data.player_id}</dd>
            </>
          )}
          <dt className="text-[var(--text-muted)]">Panel</dt>
          <dd>{data.panel + 1}</dd>
          <dt className="text-[var(--text-muted)]">Stake</dt>
          <dd>{money(data.stake, data.currency)}</dd>
          <dt className="text-[var(--text-muted)]">Auto cash-out</dt>
          <dd>{multiplier(data.auto_cashout_x10000)}</dd>
          <dt className="text-[var(--text-muted)]">Cashed out at</dt>
          <dd>{multiplier(data.cashout_x10000)}</dd>
          <dt className="text-[var(--text-muted)]">Payout</dt>
          <dd>{money(data.payout, data.currency)}</dd>
          <dt className="text-[var(--text-muted)]">Status</dt>
          <dd><Status tone={toneFor(data.status)}>{data.status}</Status></dd>
          <dt className="text-[var(--text-muted)]">Settlement</dt>
          <dd>
            {data.settlement ? (
              <Status tone={toneFor(data.settlement.status)}>
                {data.settlement.outcome} · {data.settlement.status} · {when(data.settlement.confirmed_at)}
              </Status>
            ) : (
              "—"
            )}
          </dd>
        </dl>
      </Card>
      <Card title="Wallet transactions">
        <Table head={["Transaction id", "Type", "Amount", "Status"]} empty={!data.transactions.length}>
          {data.transactions.map((t) => (
            <tr key={t.transaction_id}>
              <td><Mono>{t.transaction_id}</Mono></td>
              <td>{t.type}</td>
              <td className="tabular">{money(t.amount, data.currency)}</td>
              <td><Status tone={toneFor(t.status)}>{t.status}</Status></td>
            </tr>
          ))}
        </Table>
      </Card>
      <Card title="Wallet call attempts">
        <Table head={["Type", "#", "Outcome", "Your code", "Latency", "At"]} empty={!data.attempts.length}>
          {data.attempts.map((a, i) => (
            <tr key={i}>
              <td>{a.type}</td>
              <td className="tabular">{a.attempt}</td>
              <td><Status tone={toneFor(a.outcome)}>{a.outcome}</Status></td>
              <td>{a.operator_code || "—"}</td>
              <td className="tabular">{a.latency_ms} ms</td>
              <td className="text-xs">{when(a.at)}</td>
            </tr>
          ))}
        </Table>
      </Card>
    </>
  );
}

export default function BetDetailPage() {
  return (
    <Shell title="Bet detail">
      <Suspense>
        <Body />
      </Suspense>
    </Shell>
  );
}
