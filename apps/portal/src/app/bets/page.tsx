"use client";

import Link from "next/link";
import { useState } from "react";

import { Shell, useMe } from "@/components/Shell";
import { Button, Card, Field, Input, Mono, Notice, Select, Status, Table, toneFor } from "@/components/ui";
import { api, message } from "@/lib/api";
import { money, multiplier, when } from "@/lib/format";
import type { BetRow } from "@/lib/types";

const STATUSES = ["", "ACTIVE", "CASHED_OUT", "LOST", "REJECTED", "EXCLUDED", "VOIDED", "DEBIT_UNKNOWN"];

function Body() {
  const { me } = useMe();
  const players = me.permissions.includes("players.read");
  const [status, setStatus] = useState("");
  const [player, setPlayer] = useState("");
  const [rows, setRows] = useState<BetRow[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState("");

  const load = async (before?: string) => {
    const q = new URLSearchParams();
    if (status) q.set("status", status);
    if (player) q.set("player_id", player);
    if (before) q.set("before", before);
    try {
      const r = await api.get<{ bets: BetRow[]; next: string | null }>(`bets?${q}`);
      setRows((prev) => (before && prev ? [...prev, ...r.bets] : r.bets));
      setNext(r.next);
      setError("");
    } catch (err) {
      setError(message(err));
    }
  };

  return (
    <Card>
      <form
        className="mb-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void load();
        }}
      >
        <Field label="Status">
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s || "Any"}
              </option>
            ))}
          </Select>
        </Field>
        {players && (
          <Field label="Player id">
            <Input value={player} onChange={(e) => setPlayer(e.target.value)} placeholder="exact match" />
          </Field>
        )}
        <Button type="submit">Search</Button>
      </form>
      {error && <Notice tone="critical">{error}</Notice>}
      {rows === null ? (
        <p className="text-sm text-[var(--text-muted)]">Choose filters and search.</p>
      ) : (
        <Table
          head={["Bet", ...(players ? ["Player"] : []), "Stake", "Cash-out", "Payout", "Status", "Placed"]}
          empty={rows.length === 0}
        >
          {rows.map((b) => (
            <tr key={b.bet_id}>
              <td>
                <Link className="underline" href={`/bets/detail?id=${encodeURIComponent(b.bet_id)}`}>
                  <Mono>{b.bet_id}</Mono>
                </Link>
              </td>
              {players && <td>{b.player_id}</td>}
              <td className="tabular">{money(b.stake, b.currency)}</td>
              <td className="tabular">{multiplier(b.cashout_x10000)}</td>
              <td className="tabular">{money(b.payout, b.currency)}</td>
              <td>
                <Status tone={toneFor(b.status)}>{b.status}</Status>
              </td>
              <td className="text-xs">{when(b.created_at)}</td>
            </tr>
          ))}
        </Table>
      )}
      {next && (
        <div className="mt-3">
          <Button variant="ghost" onClick={() => void load(next)}>
            Load more
          </Button>
        </div>
      )}
    </Card>
  );
}

export default function BetsPage() {
  return (
    <Shell title="Bets">
      <Body />
    </Shell>
  );
}
