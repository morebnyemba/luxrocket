"use client";

import { Button, Card, Input, Notice, Select, Status, Table, useResource, message, when } from "@luxrocket/console-kit";
import { useState } from "react";

import { Shell, useMe } from "@/components/Shell";
import { api } from "@/lib/api";

type Market = { country_code: string; status: string; evidence_ref: string; changed_at: string; operators: number };

function Row({ m, editable, onSaved }: { m: Market; editable: boolean; onSaved: (msg: string) => void }) {
  const [status, setStatus] = useState(m.status);
  const [evidence, setEvidence] = useState(m.evidence_ref);
  const tone = m.status === "REAL" ? "good" : m.status === "SANDBOX" ? "warning" : "neutral";
  return (
    <tr>
      <td className="font-medium">{m.country_code}</td>
      <td>
        {editable ? (
          <Select aria-label={`Status for ${m.country_code}`} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="DISABLED">DISABLED</option>
            <option value="SANDBOX">SANDBOX</option>
            <option value="REAL">REAL</option>
          </Select>
        ) : (
          <Status tone={tone}>{m.status}</Status>
        )}
      </td>
      <td>
        {editable ? (
          <Input aria-label={`Evidence for ${m.country_code}`} value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="licence / legal opinion ref" />
        ) : (
          m.evidence_ref || "—"
        )}
      </td>
      <td className="tabular">{m.operators}</td>
      <td className="text-xs">{when(m.changed_at)}</td>
      <td>
        {editable && (status !== m.status || evidence !== m.evidence_ref) && (
          <Button
            onClick={async () => {
              try {
                await api.put(`markets/${m.country_code}`, { status, evidence_ref: evidence });
                onSaved(`${m.country_code} is now ${status}.${m.status === "REAL" && status !== "REAL" ? " Live real-money sessions there were revoked." : ""}`);
              } catch (err) {
                onSaved(message(err));
              }
            }}
          >
            Save
          </Button>
        )}
      </td>
    </tr>
  );
}

function Body() {
  const { me } = useMe();
  const editable = me.permissions.includes("markets.write");
  const { data, error, reload } = useResource<{ markets: Market[] }>(api, "markets");
  const [note, setNote] = useState("");
  const [cc, setCc] = useState("");
  return (
    <Card title="Markets">
      <p className="mb-3 text-sm text-[var(--text-muted)]">
        Where the game may run, and in which mode. {editable ? "Only you (the owner) can change this." : "Read-only: only the platform owner can change markets (ADR-026)."}
      </p>
      {error && <Notice tone="critical">{error}</Notice>}
      {data && (
        <Table head={["Country", "Mode", "Evidence", "Operators", "Changed", ""]} empty={!data.markets.length}>
          {data.markets.map((m) => (
            <Row key={`${m.country_code}-${m.status}-${m.evidence_ref}`} m={m} editable={editable} onSaved={(msg) => { setNote(msg); reload(); }} />
          ))}
        </Table>
      )}
      {editable && (
        <div className="mt-3 flex items-end gap-2">
          <Input aria-label="New country code" placeholder="ISO code, e.g. KE" maxLength={2} value={cc} onChange={(e) => setCc(e.target.value.toUpperCase())} className="w-40" />
          <Button
            variant="ghost"
            onClick={async () => {
              try {
                await api.put(`markets/${cc}`, { status: "DISABLED" });
                setCc("");
                reload();
              } catch (err) {
                setNote(message(err));
              }
            }}
          >
            Add country (disabled)
          </Button>
        </div>
      )}
      {note && <p role="status" className="mt-2 text-sm">{note}</p>}
    </Card>
  );
}

export default function MarketsPage() {
  return (
    <Shell title="Markets">
      <Body />
    </Shell>
  );
}
