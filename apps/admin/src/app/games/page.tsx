"use client";

import { Button, Card, Field, Input, Mono, Notice, Select, Status, Table, message, multiplier, percentBp, useResource, when } from "@luxrocket/console-kit";
import { useState } from "react";

import { Shell, useMe } from "@/components/Shell";
import { api } from "@/lib/api";

type Ruleset = {
  code: string;
  formula: string;
  house_edge_bp: number;
  rtp_bp: number;
  max_multiplier_x10000: number;
  status: string;
  certification_ref: string;
  created_by: string;
  approved_by: string;
  approved_at: string | null;
  streams: string[];
};
type StreamRow = {
  stream: string;
  desired: { ruleset: string; version: number };
  applied: { ruleset: string; version: number | null; round: number; approved: boolean | null } | null;
  operators: number;
};
type Chain = { chain_id: string; stream: string; length: number; terminal_hash: string; salt_source: string; status: string; created_at: string; rounds_used: number; usage_bp: number };

function Rulesets() {
  const { me } = useMe();
  const canManage = me.permissions.includes("games.manage");
  const { data, reload } = useResource<{ rulesets: Ruleset[] }>(api, "games/rulesets");
  const [form, setForm] = useState({ code: "", edge: "300", max: "10000" });
  const [certs, setCerts] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const edge = Number(form.edge) || 0;

  return (
    <Card title="Rulesets">
      <p className="mb-3 text-sm text-[var(--text-muted)]">
        LR-CRASH-1 with a fixed curve: a ruleset sets only the house edge and the maximum multiplier. Approved rulesets are
        immutable; approval needs a test-lab certificate and a second person.
      </p>
      {data && (
        <Table head={["Code", "RTP", "Max", "Status", "Certificate", "Streams", ""]} empty={!data.rulesets.length}>
          {data.rulesets.map((r) => (
            <tr key={r.code}>
              <td><Mono>{r.code}</Mono></td>
              <td className="tabular">{percentBp(r.rtp_bp)}</td>
              <td className="tabular">{multiplier(r.max_multiplier_x10000)}</td>
              <td><Status tone={r.status === "APPROVED" ? "good" : r.status === "DRAFT" ? "warning" : "neutral"}>{r.status}</Status></td>
              <td className="text-xs">{r.certification_ref || "—"}{r.approved_by && <div>approved by {r.approved_by} · {when(r.approved_at)}</div>}</td>
              <td>{r.streams.join(", ") || "—"}</td>
              <td>
                {canManage && r.status === "DRAFT" && (
                  <div className="flex gap-2">
                    <Input aria-label={`Certificate for ${r.code}`} placeholder="lab certificate ref" value={certs[r.code] ?? ""} onChange={(e) => setCerts({ ...certs, [r.code]: e.target.value })} />
                    <Button
                      variant="ghost"
                      onClick={async () => {
                        try {
                          await api.post("approvals", { action: "APPROVE_RULESET", subject: r.code, reason: "certification received", payload: { certification_ref: certs[r.code] ?? "" } });
                          setNote(`Approval requested for ${r.code} — a different approver must decide.`);
                        } catch (err) {
                          setNote(message(err));
                        }
                      }}
                    >
                      Request approval
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </Table>
      )}
      {canManage && (
        <form
          className="mt-4 flex flex-wrap items-end gap-3"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await api.post("games/rulesets", {
                code: form.code,
                house_edge_bp: edge,
                max_multiplier_x10000: Math.round(Number(form.max) * 10000),
              });
              setNote(`Draft ${form.code.toUpperCase()} created.`);
              reload();
            } catch (err) {
              setNote(message(err));
            }
          }}
        >
          <Field label="Code"><Input required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="LR-STD-96" /></Field>
          <Field label="House edge (bp)" hint={`RTP preview: ${percentBp(10000 - edge)} at every target`}>
            <Input type="number" min={100} max={1000} value={form.edge} onChange={(e) => setForm({ ...form, edge: e.target.value })} className="w-32" />
          </Field>
          <Field label="Max multiplier (×)" hint="100 – 10000">
            <Input type="number" min={100} max={10000} step="0.01" value={form.max} onChange={(e) => setForm({ ...form, max: e.target.value })} className="w-32" />
          </Field>
          <Button type="submit">Create draft</Button>
        </form>
      )}
      {note && <p role="status" className="mt-2 text-sm">{note}</p>}
    </Card>
  );
}

function Streams() {
  const { me } = useMe();
  const canManage = me.permissions.includes("games.manage");
  const streams = useResource<{ streams: StreamRow[] }>(api, "games/streams");
  const rulesets = useResource<{ rulesets: Ruleset[] }>(api, "games/rulesets");
  const [pick, setPick] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const approved = (rulesets.data?.rulesets ?? []).filter((r) => r.status === "APPROVED");
  return (
    <Card title="Streams">
      <p className="mb-3 text-sm text-[var(--text-muted)]">
        A new binding never touches the round in flight: the engine adopts it when it creates the next round, and journals
        the ruleset each round used.
      </p>
      {streams.data && (
        <Table head={["Stream", "Bound (desired)", "Applied by the engine", "Operators", ""]} empty={!streams.data.streams.length}>
          {streams.data.streams.map((s) => (
            <tr key={s.stream}>
              <td className="font-medium">{s.stream}</td>
              <td><Mono>{s.desired.ruleset}</Mono> v{s.desired.version}</td>
              <td>
                {s.applied ? (
                  <Status tone={s.applied.approved === false ? "critical" : s.applied.ruleset === s.desired.ruleset ? "good" : "warning"}>
                    {s.applied.ruleset} v{s.applied.version ?? 0} · round {s.applied.round}
                    {s.applied.approved === false ? " · NOT APPROVED" : s.applied.ruleset !== s.desired.ruleset ? " · switching at next round" : ""}
                  </Status>
                ) : (
                  "no rounds yet"
                )}
              </td>
              <td className="tabular">{s.operators}</td>
              <td>
                {canManage && (
                  <div className="flex gap-2">
                    <Select aria-label={`Ruleset for ${s.stream}`} value={pick[s.stream] ?? ""} onChange={(e) => setPick({ ...pick, [s.stream]: e.target.value })}>
                      <option value="">Choose approved ruleset…</option>
                      {approved.filter((r) => r.code !== s.desired.ruleset).map((r) => (
                        <option key={r.code} value={r.code}>{r.code} ({percentBp(r.rtp_bp)})</option>
                      ))}
                    </Select>
                    <Button
                      variant="ghost"
                      disabled={!pick[s.stream]}
                      onClick={async () => {
                        try {
                          await api.post("approvals", { action: "BIND_RULESET", subject: s.stream, reason: "ruleset change", payload: { ruleset: pick[s.stream] } });
                          setNote(`Binding requested for ${s.stream} — a different approver must decide.`);
                        } catch (err) {
                          setNote(message(err));
                        }
                      }}
                    >
                      Request binding
                    </Button>
                  </div>
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

function SeedChains() {
  const { data, error } = useResource<{ seed_chains: Chain[] }>(api, "games/seed-chains");
  return (
    <Card title="Seed chains">
      <p className="mb-3 text-sm text-[var(--text-muted)]">Public facts only — seeds are never shown. Each round reveals the previous link of the hash chain.</p>
      {error && <Notice tone="critical">{error}</Notice>}
      {data && (
        <Table head={["Stream", "Status", "Usage", "Terminal hash (commitment)", "Salt source", "Created"]} empty={!data.seed_chains.length}>
          {data.seed_chains.map((c) => (
            <tr key={c.chain_id}>
              <td>{c.stream}</td>
              <td><Status tone={c.status === "ACTIVE" ? "good" : "neutral"}>{c.status}</Status></td>
              <td className="tabular">{c.rounds_used.toLocaleString()} / {c.length.toLocaleString()} ({percentBp(c.usage_bp)})</td>
              <td><Mono>{c.terminal_hash}</Mono></td>
              <td>{c.salt_source}</td>
              <td className="text-xs">{when(c.created_at)}</td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

export default function GamesPage() {
  return (
    <Shell title="Games">
      <Rulesets />
      <Streams />
      <SeedChains />
    </Shell>
  );
}
