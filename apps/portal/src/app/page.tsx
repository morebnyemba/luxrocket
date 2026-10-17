"use client";

import { Shell } from "@/components/Shell";
import { Card, money, Notice, percentBp, Status } from "@luxrocket/console-kit";
import { useResource } from "@/lib/hooks";

type Overview = {
  window_hours: number;
  currencies: {
    currency: string;
    bets: number;
    players: number;
    turnover: string;
    payouts: string;
    ggr: string;
    rtp_bp: number | null;
  }[];
  wallet: {
    calls: number;
    answered_rate_bp: number | null;
    p95_latency_ms: number | null;
    pending: number;
    needs_attention: number;
  };
  webhooks: { delivered: number; pending: number; failed: number };
  open_discrepancies: number;
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
  const { data, error } = useResource<Overview>("overview?hours=24");
  if (error) return <Notice tone="critical">{error}</Notice>;
  if (!data) return <p className="text-sm text-[var(--text-muted)]">Loading…</p>;
  const w = data.wallet;
  const walletTone = w.needs_attention ? "critical" : w.answered_rate_bp != null && w.answered_rate_bp < 9900 ? "warning" : "good";
  return (
    <>
      <p className="text-sm text-[var(--text-muted)]">Last {data.window_hours} hours · settled bets only · GGR from the ledger</p>
      {data.currencies.length === 0 && <Notice>No settled bets in this window.</Notice>}
      {data.currencies.map((c) => (
        <section key={c.currency} aria-label={`${c.currency} performance`} className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Tile label={`Turnover · ${c.currency}`} value={money(c.turnover, c.currency)} sub={`${c.bets} bets · ${c.players} players`} />
          <Tile label="Payouts" value={money(c.payouts, c.currency)} />
          <Tile label="GGR" value={money(c.ggr, c.currency)} sub="turnover − payouts" />
          <Tile label="Actual RTP" value={percentBp(c.rtp_bp)} sub={`theoretical 97.00% · n=${c.bets}`} />
        </section>
      ))}
      <div className="grid gap-3 md:grid-cols-3">
        <Card title="Wallet health">
          <div className="flex flex-col gap-2 text-sm">
            <Status tone={walletTone}>
              {walletTone === "good" ? "Healthy" : walletTone === "warning" ? "Degraded" : "Needs attention"}
            </Status>
            <dl className="tabular grid grid-cols-2 gap-1">
              <dt className="text-[var(--text-muted)]">Calls</dt>
              <dd>{w.calls}</dd>
              <dt className="text-[var(--text-muted)]">Answered</dt>
              <dd>{percentBp(w.answered_rate_bp)}</dd>
              <dt className="text-[var(--text-muted)]">p95 latency</dt>
              <dd>{w.p95_latency_ms == null ? "—" : `${w.p95_latency_ms} ms`}</dd>
              <dt className="text-[var(--text-muted)]">Pending</dt>
              <dd>{w.pending}</dd>
              <dt className="text-[var(--text-muted)]">Needs attention</dt>
              <dd>{w.needs_attention}</dd>
            </dl>
          </div>
        </Card>
        <Card title="Webhooks">
          <dl className="tabular grid grid-cols-2 gap-1 text-sm">
            <dt className="text-[var(--text-muted)]">Delivered</dt>
            <dd>{data.webhooks.delivered}</dd>
            <dt className="text-[var(--text-muted)]">Pending</dt>
            <dd>{data.webhooks.pending}</dd>
            <dt className="text-[var(--text-muted)]">Failed</dt>
            <dd>{data.webhooks.failed}</dd>
          </dl>
        </Card>
        <Card title="Reconciliation">
          {data.open_discrepancies ? (
            <Status tone="critical">{data.open_discrepancies} open discrepancies</Status>
          ) : (
            <Status tone="good">No open discrepancies</Status>
          )}
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
