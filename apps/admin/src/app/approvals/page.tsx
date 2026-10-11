"use client";

import { Button, Card, Input, Mono, Notice, Select, Status, Table, useResource, message, when } from "@luxrocket/console-kit";
import { useState } from "react";

import { Shell, useMe } from "@/components/Shell";
import { api } from "@/lib/api";

type Approval = {
  id: string;
  action: string;
  subject: string;
  operator: string | null;
  operator_name: string | null;
  payload: Record<string, string>;
  reason: string;
  requested_by: string;
  status: string;
  decided_by: string | null;
  decision_note: string;
  created_at: string;
};

function Decide({ a, mine, onDone }: { a: Approval; mine: boolean; onDone: (m: string) => void }) {
  const [note, setNote] = useState("");
  const go = async (decision: string) => {
    try {
      await api.post(`approvals/${a.id}/${decision}`, { note });
      onDone(`Request ${decision === "approve" ? "approved and executed" : decision + "ed"}.`);
    } catch (err) {
      onDone(message(err));
    }
  };
  if (mine) {
    return (
      <div className="flex flex-col gap-1">
        <span className="text-xs text-[var(--text-muted)]">Your request — someone else must decide.</span>
        <Button variant="ghost" onClick={() => go("cancel")}>Cancel request</Button>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Input aria-label="Decision note" placeholder="note (required)" value={note} onChange={(e) => setNote(e.target.value)} />
      <Button onClick={() => go("approve")}>Approve</Button>
      <Button variant="danger" onClick={() => go("reject")}>Reject</Button>
    </div>
  );
}

function Body() {
  const { me } = useMe();
  const [status, setStatus] = useState("PENDING");
  const { data, error, reload } = useResource<{ approvals: Approval[] }>(api, `approvals?status=${status}`);
  const [note, setNote] = useState("");
  return (
    <Card
      title="Four-eyes approvals"
      actions={
        <Select aria-label="Status filter" value={status} onChange={(e) => setStatus(e.target.value)}>
          {["PENDING", "APPROVED", "REJECTED", "CANCELLED"].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </Select>
      }
    >
      <p className="mb-3 text-sm text-[var(--text-muted)]">
        The requester can never decide their own request. Approving re-checks every precondition and executes the change atomically.
      </p>
      {error && <Notice tone="critical">{error}</Notice>}
      {data && (
        <Table head={["Requested", "Action", "Subject", "Evidence / reason", "By", "Status", "Decision"]} empty={!data.approvals.length}>
          {data.approvals.map((a) => (
            <tr key={a.id}>
              <td className="text-xs">{when(a.created_at)}</td>
              <td>{a.action}</td>
              <td>{a.operator_name ?? a.subject}{a.operator && <div><Mono>{a.operator}</Mono></div>}</td>
              <td className="text-xs">
                {a.reason}
                {Object.entries(a.payload).map(([k, v]) => (
                  <div key={k}>{k}: <Mono>{v}</Mono></div>
                ))}
              </td>
              <td>{a.requested_by}</td>
              <td><Status tone={a.status === "APPROVED" ? "good" : a.status === "PENDING" ? "warning" : "neutral"}>{a.status}</Status></td>
              <td>
                {a.status === "PENDING" ? (
                  <Decide a={a} mine={a.requested_by === me.email} onDone={(m) => { setNote(m); reload(); }} />
                ) : (
                  <span className="text-xs">{a.decided_by} {a.decision_note && `· ${a.decision_note}`}</span>
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

export default function ApprovalsPage() {
  return (
    <Shell title="Approvals">
      <Body />
    </Shell>
  );
}
