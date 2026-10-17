"use client";

import { Card, money, Notice, Status, useResource } from "@luxrocket/console-kit";
import Link from "next/link";

import { Shell } from "@/components/Shell";
import { api } from "@/lib/api";

type Overview = {
  operators: Record<string, number>;
  rounds_24h: { crashed: number; voided: number; unverified: number };
  ggr_24h: { currency: string; ggr: string }[];
  wallet: { pending: number; needs_attention: number };
  discrepancies: Record<string, number>;
  pending_approvals: number;
};

function Tile({ label, value, sub }: { label: string; value: string; sub?: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="text-xs text-[var(--text-muted)]">{label}</div>
      <div className="tabular mt-1 text-2xl font-semibold">{value}</div>
      {sub && <div className="mt-1 text-xs text-[var(--text-muted)]">{sub}</div>}
    </div>
  );
}

function Body() {
  const { data, error } = useResource<Overview>(api, "overview");
  if (error) return <Notice tone="critical">{error}</Notice>;
  if (!data) return <p className="text-sm text-[var(--text-muted)]">Loading…</p>;
  const ops = data.operators;
  const critical = data.discrepancies.CRITICAL ?? 0;
  return (
    <>
      <section aria-label="Platform at a glance" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile label="Live operators" value={String(ops.LIVE ?? 0)} sub={`${ops.SANDBOX ?? 0} sandbox · ${ops.SUSPENDED ?? 0} suspended`} />
        <Tile label="Rounds · 24 h" value={String(data.rounds_24h.crashed)} sub={`${data.rounds_24h.voided} voided`} />
        <Tile label="Wallet backlog" value={String(data.wallet.pending)} sub={`${data.wallet.needs_attention} need attention`} />
        <Tile label="Pending approvals" value={String(data.pending_approvals)} sub={<Link className="underline" href="/approvals">Review</Link>} />
      </section>
      <div className="grid gap-3 md:grid-cols-3">
        <Card title="Integrity">
          <div className="flex flex-col gap-2">
            <Status tone={data.rounds_24h.unverified ? "critical" : "good"}>
              {data.rounds_24h.unverified ? `${data.rounds_24h.unverified} unverified outcomes` : "All outcomes verified"}
            </Status>
            <Status tone={critical ? "critical" : "good"}>
              {critical ? `${critical} critical discrepancies` : "No critical discrepancies"}
            </Status>
            <Status tone={data.wallet.needs_attention ? "warning" : "good"}>
              {data.wallet.needs_attention ? `${data.wallet.needs_attention} transactions need attention` : "No stuck transactions"}
            </Status>
          </div>
        </Card>
        <Card title="GGR · 24 h (all operators, from the ledger)">
          {data.ggr_24h.length === 0 ? (
            <p className="text-sm text-[var(--text-muted)]">No settled play.</p>
          ) : (
            <dl className="tabular grid grid-cols-2 gap-1 text-sm">
              {data.ggr_24h.map((g) => (
                <div key={g.currency} className="contents">
                  <dt className="text-[var(--text-muted)]">{g.currency}</dt>
                  <dd>{money(g.ggr, g.currency)}</dd>
                </div>
              ))}
            </dl>
          )}
        </Card>
        <Card title="Open discrepancies">
          <dl className="tabular grid grid-cols-2 gap-1 text-sm">
            <dt className="text-[var(--text-muted)]">Critical</dt>
            <dd>{critical}</dd>
            <dt className="text-[var(--text-muted)]">Warning</dt>
            <dd>{data.discrepancies.WARNING ?? 0}</dd>
          </dl>
        </Card>
      </div>
    </>
  );
}

export default function OverviewPage() {
  return (
    <Shell title="Overview">
      <Body />
    </Shell>
  );
}
