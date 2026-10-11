"use client";

import { Button, Card, Field, Input, Mono, Notice, Status, Table, useResource, when } from "@luxrocket/console-kit";
import { useState } from "react";

import { Shell } from "@/components/Shell";
import { api } from "@/lib/api";

type Event = { seq: number; at: string; realm: string; operator: string | null; actor: string; action: string; target: string; data: Record<string, unknown>; ip: string | null; hash: string };
type Verify = { ok: boolean; first_broken_seq: number | null; events: number; head_hash: string | null };

function Body() {
  const [filters, setFilters] = useState({ action: "", actor: "", operator: "" });
  const [query, setQuery] = useState("audit");
  const verify = useResource<Verify>(api, "audit/verify");
  const { data, error } = useResource<{ events: Event[]; next: string | null }>(api, query);
  const search = (before?: string) => {
    const p = new URLSearchParams(Object.entries(filters).filter(([, v]) => v));
    if (before) p.set("before", before);
    setQuery(`audit?${p}`);
  };
  return (
    <>
      <Card title="Chain integrity">
        {verify.data && (
          <Status tone={verify.data.ok ? "good" : "critical"}>
            {verify.data.ok
              ? `Intact: ${verify.data.events} events, head ${verify.data.head_hash?.slice(0, 16)}…`
              : `BROKEN at event #${verify.data.first_broken_seq} — treat as a security incident`}
          </Status>
        )}
      </Card>
      <Card title="Audit log (platform and operator portals)">
        <form className="mb-3 flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); search(); }}>
          <Field label="Action prefix"><Input value={filters.action} onChange={(e) => setFilters({ ...filters, action: e.target.value })} placeholder="e.g. approval." /></Field>
          <Field label="Actor"><Input value={filters.actor} onChange={(e) => setFilters({ ...filters, actor: e.target.value })} /></Field>
          <Field label="Operator id"><Input value={filters.operator} onChange={(e) => setFilters({ ...filters, operator: e.target.value })} /></Field>
          <Button type="submit">Filter</Button>
        </form>
        {error && <Notice tone="critical">{error}</Notice>}
        {data && (
          <Table head={["#", "When", "Realm", "Actor", "Action", "Target", "Details"]} empty={!data.events.length}>
            {data.events.map((e) => (
              <tr key={e.seq}>
                <td className="tabular">{e.seq}</td>
                <td className="text-xs">{when(e.at)}</td>
                <td>{e.realm}{e.operator && <div><Mono>{e.operator}</Mono></div>}</td>
                <td>{e.actor}</td>
                <td>{e.action}</td>
                <td><Mono>{e.target}</Mono></td>
                <td><Mono>{Object.keys(e.data).length ? JSON.stringify(e.data) : ""}</Mono></td>
              </tr>
            ))}
          </Table>
        )}
        {data?.next && (
          <div className="mt-3"><Button variant="ghost" onClick={() => search(data.next ?? undefined)}>Older</Button></div>
        )}
      </Card>
    </>
  );
}

export default function AuditPage() {
  return (
    <Shell title="Audit">
      <Body />
    </Shell>
  );
}
