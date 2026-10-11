"use client";

import { Button, Card, Field, Input, Mono, Notice, Status, Table, toneFor, useResource, message, when } from "@luxrocket/console-kit";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Shell, useMe } from "@/components/Shell";
import { api } from "@/lib/api";

type Approval = { id: string; action: string; status: string; requested_by: string; decided_by: string | null; reason: string; decision_note: string; created_at: string };
type Detail = {
  id: string;
  legal_name: string;
  status: string;
  real_money_enabled: boolean;
  stream: string;
  wallet_kind: string;
  wallet_base_url: string;
  wallet_conformance_passed_at: string | null;
  jurisdictions: string[];
  limits: { currency: string; min_stake: string; max_stake: string; max_win: string; round_exposure: string }[];
  credentials: { kid: string; status: string; created_at: string; last_used_at: string | null }[];
  portal_users: number;
  active_sessions: number;
  approvals: Approval[];
};

const EVIDENCE = [
  ["contract_ref", "Signed contract ref"],
  ["licence_ref", "Licence evidence ref"],
  ["certification_ref", "Ruleset certification ref"],
  ["security_signoff_ref", "Security review sign-off"],
] as const;

function Body() {
  const id = useSearchParams().get("id") ?? "";
  const { me } = useMe();
  const can = (p: string) => me.permissions.includes(p);
  const { data, error, reload } = useResource<Detail>(api, id ? `operators/${encodeURIComponent(id)}` : null);
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");

  if (error) return <Notice tone="critical">{error}</Notice>;
  if (!data) return <p className="text-sm text-[var(--text-muted)]">Loading…</p>;
  const act = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn();
      setNote(done);
      reload();
    } catch (err) {
      setNote(message(err));
    }
  };

  return (
    <>
      <Card title={data.legal_name}>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-[var(--text-muted)]">Id</dt><dd><Mono>{data.id}</Mono></dd>
          <dt className="text-[var(--text-muted)]">Status</dt><dd><Status tone={data.status === "SUSPENDED" ? "critical" : data.status === "LIVE" ? "good" : "neutral"}>{data.status}</Status></dd>
          <dt className="text-[var(--text-muted)]">Real money</dt><dd>{data.real_money_enabled ? "Enabled" : "Off"}</dd>
          <dt className="text-[var(--text-muted)]">Jurisdictions</dt><dd>{data.jurisdictions.join(", ")}</dd>
          <dt className="text-[var(--text-muted)]">Wallet</dt><dd>{data.wallet_kind} {data.wallet_base_url && <Mono>{data.wallet_base_url}</Mono>}</dd>
          <dt className="text-[var(--text-muted)]">Conformance</dt>
          <dd><Status tone={data.wallet_conformance_passed_at ? "good" : "warning"}>{data.wallet_conformance_passed_at ? `Passed ${when(data.wallet_conformance_passed_at)}` : "Not passed on current URL"}</Status></dd>
          <dt className="text-[var(--text-muted)]">Portal users / live sessions</dt><dd>{data.portal_users} / {data.active_sessions}</dd>
        </dl>
        <Table head={["Currency", "Min stake", "Max stake", "Max win", "Round exposure"]}>
          {data.limits.map((l) => (
            <tr key={l.currency} className="tabular"><td>{l.currency}</td><td>{l.min_stake}</td><td>{l.max_stake}</td><td>{l.max_win}</td><td>{l.round_exposure}</td></tr>
          ))}
        </Table>
      </Card>

      {can("operators.manage") && (
        <Card title="Lifecycle">
          <div className="flex flex-col gap-3">
            <Field label="Reason (required, audited)">
              <Input value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
            <div className="flex flex-wrap gap-2">
              {data.status !== "SUSPENDED" && data.status !== "TERMINATED" && (
                <Button variant="danger" onClick={() => act(() => api.post(`operators/${data.id}/suspend`, { reason }), "Suspended; sessions revoked.")}>
                  Suspend now
                </Button>
              )}
              {data.status === "ONBOARDING" && (
                <Button variant="ghost" onClick={() => act(() => api.post(`operators/${data.id}/promote`), "Moved to sandbox.")}>Move to sandbox</Button>
              )}
              {data.status === "SUSPENDED" && (
                <Button onClick={() => act(() => api.post(`operators/${data.id}/approvals`, { action: "REACTIVATE_OPERATOR", reason }), "Reactivation requested — another person must approve.")}>
                  Request reactivation
                </Button>
              )}
            </div>
          </div>
        </Card>
      )}

      {can("realmoney.request") && !data.real_money_enabled && (
        <Card title="Request real-money enablement (four-eyes)">
          <div className="grid gap-3 md:grid-cols-2">
            {EVIDENCE.map(([k, label]) => (
              <Field key={k} label={label}>
                <Input value={evidence[k] ?? ""} onChange={(e) => setEvidence({ ...evidence, [k]: e.target.value })} />
              </Field>
            ))}
          </div>
          <div className="mt-3">
            <Button
              onClick={() =>
                act(
                  () => api.post(`operators/${data.id}/approvals`, { action: "ENABLE_REAL_MONEY", reason: reason || "go-live", payload: evidence }),
                  "Requested — a different approver (owner, superadmin or risk) must approve.",
                )
              }
            >
              Request approval
            </Button>
          </div>
        </Card>
      )}

      <Card title="API credentials">
        <Table head={["Key id", "Status", "Created", "Last used", ""]} empty={!data.credentials.length}>
          {data.credentials.map((c) => (
            <tr key={c.kid}>
              <td><Mono>{c.kid}</Mono></td>
              <td><Status tone={toneFor(c.status)}>{c.status}</Status></td>
              <td className="text-xs">{when(c.created_at)}</td>
              <td className="text-xs">{when(c.last_used_at)}</td>
              <td>
                {can("credentials.manage") && c.status === "ACTIVE" && (
                  <Button variant="danger" onClick={() => act(() => api.post(`operators/${data.id}/credentials/${c.kid}/revoke`, { reason }), `Revoked ${c.kid}.`)}>
                    Revoke (compromise)
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </Table>
      </Card>

      <Card title="Approval history">
        <Table head={["Action", "Status", "Requested by", "Decided by", "Reason / note", "Created"]} empty={!data.approvals.length}>
          {data.approvals.map((a) => (
            <tr key={a.id}>
              <td>{a.action}</td>
              <td><Status tone={a.status === "APPROVED" ? "good" : a.status === "PENDING" ? "warning" : "neutral"}>{a.status}</Status></td>
              <td>{a.requested_by}</td>
              <td>{a.decided_by ?? "—"}</td>
              <td className="text-xs">{a.reason}{a.decision_note && ` / ${a.decision_note}`}</td>
              <td className="text-xs">{when(a.created_at)}</td>
            </tr>
          ))}
        </Table>
      </Card>
      {note && <Notice>{note}</Notice>}
    </>
  );
}

export default function OperatorDetailPage() {
  return (
    <Shell title="Operator">
      <Suspense>
        <Body />
      </Suspense>
    </Shell>
  );
}
