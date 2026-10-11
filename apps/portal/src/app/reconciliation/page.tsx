"use client";

import { useState } from "react";

import { Shell } from "@/components/Shell";
import { Card, Field, Mono, Notice, Select, Status, Table, toneFor } from "@/components/ui";
import { when } from "@/lib/format";
import { useResource } from "@/lib/hooks";

type Item = {
  id: string;
  kind: string;
  severity: string;
  subject: string;
  detail: Record<string, unknown>;
  status: string;
  created_at: string;
  resolution_note: string;
};

function Body() {
  const [status, setStatus] = useState("OPEN");
  const { data, error } = useResource<{ discrepancies: Item[] }>(`discrepancies?status=${status}`);
  return (
    <Card
      title="Discrepancies"
      actions={
        <Field label="Status">
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="OPEN">Open</option>
            <option value="AUTO_RESOLVED">Auto-resolved</option>
            <option value="RESOLVED">Resolved</option>
          </Select>
        </Field>
      }
    >
      <p className="mb-3 text-sm text-[var(--text-muted)]">
        Reconciliation compares our wallet transactions with yours hourly, and our own books every 5 minutes. Platform
        staff resolve open items; corrections are new transactions, never edits.
      </p>
      {error && <Notice tone="critical">{error}</Notice>}
      {data && (
        <Table head={["Found", "Kind", "Severity", "Subject", "Detail", "Status"]} empty={!data.discrepancies.length}>
          {data.discrepancies.map((d) => (
            <tr key={d.id}>
              <td className="text-xs">{when(d.created_at)}</td>
              <td>{d.kind}</td>
              <td><Status tone={toneFor(d.severity)}>{d.severity}</Status></td>
              <td><Mono>{d.subject}</Mono></td>
              <td><Mono>{JSON.stringify(d.detail)}</Mono></td>
              <td>
                <Status tone={toneFor(d.status)}>{d.status}</Status>
                {d.resolution_note && <div className="text-xs text-[var(--text-muted)]">{d.resolution_note}</div>}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

export default function ReconciliationPage() {
  return (
    <Shell title="Reconciliation">
      <Body />
    </Shell>
  );
}
