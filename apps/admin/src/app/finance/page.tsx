"use client";

import { Button, Card, Field, Input, Mono, Notice, Status, Table, toneFor, useResource, message, money, when } from "@luxrocket/console-kit";
import { useState } from "react";

import { Shell, useMe } from "@/components/Shell";
import { api } from "@/lib/api";

type Tx = { transaction_id: string; type: string; status: string; amount: string; currency: string; operator: string; bet_id: string; attempts: number; operator_code: string; next_attempt_at: string | null; created_at: string };
type Item = { id: string; kind: string; severity: string; subject: string; operator: string | null; detail: Record<string, unknown>; status: string; created_at: string; resolution_note: string; resolved_by: string };
type Bet = { bet_id: string; operator: string; status: string; stake: string; currency: string; payout: string | null; player_id?: string; created_at: string };

function Pending() {
  const { me } = useMe();
  const { data, reload } = useResource<{ transactions: Tx[] }>(api, "finance/pending");
  const [note, setNote] = useState("");
  return (
    <Card title="Pending & failed wallet transactions">
      {data && (
        <Table head={["Transaction", "Type", "Operator", "Amount", "Status", "Attempts", "Operator code", ""]} empty={!data.transactions.length}>
          {data.transactions.map((t) => (
            <tr key={t.transaction_id}>
              <td><Mono>{t.transaction_id}</Mono><div className="text-xs">{when(t.created_at)}</div></td>
              <td>{t.type}</td>
              <td><Mono>{t.operator}</Mono></td>
              <td className="tabular">{money(t.amount, t.currency)}</td>
              <td><Status tone={toneFor(t.status)}>{t.status}</Status></td>
              <td className="tabular">{t.attempts}</td>
              <td>{t.operator_code || "—"}</td>
              <td>
                {me.permissions.includes("finance.retry") && t.type !== "DEBIT" && (
                  <Button
                    variant="ghost"
                    onClick={async () => {
                      try {
                        await api.post(`finance/transactions/${t.transaction_id}/retry`);
                        setNote(`Retrying ${t.transaction_id} (same id — the operator applies it at most once).`);
                        reload();
                      } catch (err) {
                        setNote(message(err));
                      }
                    }}
                  >
                    Retry now
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </Table>
      )}
      {note && <p role="status" className="mt-2 text-sm">{note}</p>}
    </Card>
  );
}

function Discrepancies() {
  const { me } = useMe();
  const { data, reload } = useResource<{ discrepancies: Item[] }>(api, "finance/discrepancies?status=OPEN");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  const canResolve = me.permissions.includes("reconciliation.resolve");
  return (
    <Card title="Open reconciliation discrepancies">
      {data && (
        <Table head={["Found", "Kind", "Severity", "Operator", "Subject", "Detail", ""]} empty={!data.discrepancies.length}>
          {data.discrepancies.map((d) => (
            <tr key={d.id}>
              <td className="text-xs">{when(d.created_at)}</td>
              <td>{d.kind}</td>
              <td><Status tone={toneFor(d.severity)}>{d.severity}</Status></td>
              <td><Mono>{d.operator ?? "platform"}</Mono></td>
              <td><Mono>{d.subject}</Mono></td>
              <td><Mono>{JSON.stringify(d.detail)}</Mono></td>
              <td>
                {canResolve && (
                  <div className="flex gap-2">
                    <Input aria-label="Resolution note" placeholder="resolution note" value={notes[d.id] ?? ""} onChange={(e) => setNotes({ ...notes, [d.id]: e.target.value })} />
                    <Button
                      variant="ghost"
                      onClick={async () => {
                        try {
                          await api.post(`finance/discrepancies/${d.id}/resolve`, { note: notes[d.id] ?? "" });
                          setMsg("Resolved. No money moved; corrections are separate transactions.");
                          reload();
                        } catch (err) {
                          setMsg(message(err));
                        }
                      }}
                    >
                      Resolve
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </Table>
      )}
      {msg && <p role="status" className="mt-2 text-sm">{msg}</p>}
    </Card>
  );
}

function BetSearch() {
  const { me } = useMe();
  const [q, setQ] = useState({ bet_id: "", operator: "", player_id: "" });
  const [rows, setRows] = useState<Bet[] | null>(null);
  const [err, setErr] = useState("");
  return (
    <Card title="Bet search">
      <form
        className="mb-3 flex flex-wrap items-end gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          const params = new URLSearchParams(Object.entries(q).filter(([, v]) => v));
          try {
            setRows((await api.get<{ bets: Bet[] }>(`finance/bets?${params}`)).bets);
            setErr("");
          } catch (error) {
            setErr(message(error));
          }
        }}
      >
        <Field label="Bet id"><Input value={q.bet_id} onChange={(e) => setQ({ ...q, bet_id: e.target.value })} /></Field>
        <Field label="Operator id"><Input value={q.operator} onChange={(e) => setQ({ ...q, operator: e.target.value })} /></Field>
        {me.permissions.includes("players.search") && (
          <Field label="Player id" hint="Player-level searches are audited"><Input value={q.player_id} onChange={(e) => setQ({ ...q, player_id: e.target.value })} /></Field>
        )}
        <Button type="submit">Search</Button>
      </form>
      {err && <Notice tone="critical">{err}</Notice>}
      {rows && (
        <Table head={["Bet", "Operator", "Player", "Stake", "Payout", "Status", "Placed"]} empty={!rows.length}>
          {rows.map((b) => (
            <tr key={b.bet_id}>
              <td><Mono>{b.bet_id}</Mono></td>
              <td><Mono>{b.operator}</Mono></td>
              <td>{b.player_id ?? "masked"}</td>
              <td className="tabular">{money(b.stake, b.currency)}</td>
              <td className="tabular">{money(b.payout, b.currency)}</td>
              <td><Status tone={toneFor(b.status)}>{b.status}</Status></td>
              <td className="text-xs">{when(b.created_at)}</td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

export default function FinancePage() {
  return (
    <Shell title="Finance">
      <Pending />
      <Discrepancies />
      <BetSearch />
    </Shell>
  );
}
