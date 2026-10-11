"use client";

import { useState } from "react";

import { Shell, useMe } from "@/components/Shell";
import { Button, Card, Field, Input, Mono, Notice, Status, Table, toneFor } from "@/components/ui";
import { api, message } from "@/lib/api";
import { when } from "@/lib/format";
import { useResource } from "@/lib/hooks";

type Wallet = {
  wallet_kind: string;
  base_url: string;
  debit_timeout_ms: number;
  debit_timeout_max_ms: number;
  platform_keys: { kid: string; alg: string; public_key: string }[];
};
type Credential = { kid: string; algorithm: string; status: string; created_at: string; last_used_at: string | null };
type Endpoint = { id: string; url: string; enabled: boolean; created_at: string };
type Delivery = {
  id: string;
  event_id: string;
  type: string;
  status: string;
  attempts: number;
  last_status_code: number | null;
  last_error: string;
  created_at: string;
};
type Conformance = { passed: boolean; checks: { name: string; passed: boolean; required: boolean; detail: string }[] };

const b64url = (buf: ArrayBuffer) =>
  btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/x-pem-file" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  URL.revokeObjectURL(url);
}

function WalletCard() {
  const { me } = useMe();
  const canManage = me.permissions.includes("wallet.manage");
  const { data, error, reload } = useResource<Wallet>("wallet");
  const [url, setUrl] = useState<string | null>(null);
  const [timeout, setTimeoutMs] = useState<string | null>(null);
  const [player, setPlayer] = useState("conformance-test");
  const [note, setNote] = useState("");
  const [report, setReport] = useState<Conformance | null>(null);
  const [busy, setBusy] = useState(false);

  if (error) return <Notice tone="critical">{error}</Notice>;
  if (!data) return null;
  const save = async () => {
    try {
      await api.put("wallet", {
        base_url: url ?? data.base_url,
        debit_timeout_ms: Number(timeout ?? data.debit_timeout_ms),
      });
      setNote("Saved. New sessions use this wallet; existing sessions keep theirs.");
      reload();
    } catch (err) {
      setNote(message(err));
    }
  };
  const run = async () => {
    setBusy(true);
    setReport(null);
    try {
      setReport(await api.post<Conformance>("wallet/conformance", { player_id: player }));
    } catch (err) {
      setNote(message(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Wallet endpoint (LUX Seamless Wallet v1)">
      <div className="flex flex-col gap-3">
        <p className="text-sm">
          Current: <Status tone={data.wallet_kind === "SEAMLESS_V1" ? "good" : "neutral"}>{data.wallet_kind}</Status>
        </p>
        <div className="grid gap-3 md:grid-cols-[1fr_200px_auto] md:items-end">
          <Field label="Base URL" hint="We call {base}/debit, /credit, /rollback, /balance, /transactions/lookup. Empty = simulated sandbox wallet.">
            <Input disabled={!canManage} value={url ?? data.base_url} onChange={(e) => setUrl(e.target.value)} placeholder="https://wallet.example.com/lux" />
          </Field>
          <Field label="Debit timeout (ms)" hint={`100–${data.debit_timeout_max_ms}`}>
            <Input
              disabled={!canManage}
              type="number"
              min={100}
              max={data.debit_timeout_max_ms}
              value={timeout ?? String(data.debit_timeout_ms)}
              onChange={(e) => setTimeoutMs(e.target.value)}
            />
          </Field>
          {canManage && <Button onClick={save}>Save</Button>}
        </div>
        {canManage && data.wallet_kind === "SEAMLESS_V1" && (
          <div className="flex flex-wrap items-end gap-3 border-t border-[var(--border)] pt-3">
            <Field label="Conformance test player" hint="Use a dedicated test account: the suite moves small amounts.">
              <Input value={player} onChange={(e) => setPlayer(e.target.value)} />
            </Field>
            <Button variant="ghost" onClick={run} disabled={busy}>
              {busy ? "Running…" : "Run conformance suite"}
            </Button>
          </div>
        )}
        {note && <p role="status" className="text-sm">{note}</p>}
        {report && (
          <div>
            <p className="mb-2 text-sm">
              <Status tone={report.passed ? "good" : "critical"}>{report.passed ? "Conformant" : "Not conformant"}</Status>
            </p>
            <ul className="flex flex-col gap-1 text-sm">
              {report.checks.map((c) => (
                <li key={c.name}>
                  <Status tone={c.passed ? "good" : c.required ? "critical" : "warning"}>{c.name}</Status>
                  {c.detail && <span className="ml-6 block text-xs text-[var(--text-muted)]">{c.detail}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="border-t border-[var(--border)] pt-3 text-sm">
          <p className="mb-1 font-medium">Platform signing keys</p>
          <p className="mb-2 text-xs text-[var(--text-muted)]">
            Verify our LR1 signatures on wallet calls and webhooks. Also at /.well-known/luxrocket-keys.json.
          </p>
          {data.platform_keys.map((k) => (
            <p key={k.kid}>
              <Mono>{k.kid}</Mono> · {k.alg} · <Mono>{k.public_key}</Mono>
            </p>
          ))}
        </div>
      </div>
    </Card>
  );
}

function CredentialsCard() {
  const { me } = useMe();
  const canManage = me.permissions.includes("credentials.manage");
  const { data, reload } = useResource<{ credentials: Credential[] }>("credentials");
  const [pub, setPub] = useState("");
  const [note, setNote] = useState("");

  const upload = async (publicKey: string) => {
    const created = await api.post<Credential>("credentials", { public_key: publicKey });
    reload();
    return created;
  };
  const generate = async () => {
    try {
      const pair = (await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"])) as CryptoKeyPair;
      const raw = await crypto.subtle.exportKey("raw", pair.publicKey);
      const created = await upload(b64url(raw));
      const pkcs8 = await crypto.subtle.exportKey("pkcs8", pair.privateKey);
      const pem = `-----BEGIN PRIVATE KEY-----\n${btoa(String.fromCharCode(...new Uint8Array(pkcs8)))}\n-----END PRIVATE KEY-----\n`;
      download(`${created.kid}.pem`, pem);
      setNote(`Key ${created.kid} created. The private key was downloaded once and never left this browser before that.`);
    } catch (err) {
      setNote(err instanceof Error && err.name === "NotSupportedError" ? "This browser cannot generate Ed25519 keys; upload a public key instead." : message(err));
    }
  };

  return (
    <Card title="API credentials (Ed25519)">
      <p className="mb-3 text-sm text-[var(--text-muted)]">
        We store only public keys. At most two active keys, for rotation; add the new key before revoking the old one.
      </p>
      {data && (
        <Table head={["Key id", "Status", "Created", "Last used", ""]} empty={!data.credentials.length}>
          {data.credentials.map((c) => (
            <tr key={c.kid}>
              <td><Mono>{c.kid}</Mono></td>
              <td><Status tone={toneFor(c.status)}>{c.status}</Status></td>
              <td className="text-xs">{when(c.created_at)}</td>
              <td className="text-xs">{when(c.last_used_at)}</td>
              <td>
                {canManage && c.status === "ACTIVE" && (
                  <Button
                    variant="danger"
                    onClick={async () => {
                      try {
                        await api.post(`credentials/${encodeURIComponent(c.kid)}/revoke`);
                        setNote(`Revoked ${c.kid}.`);
                        reload();
                      } catch (err) {
                        setNote(message(err));
                      }
                    }}
                  >
                    Revoke
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </Table>
      )}
      {canManage && (
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <Field label="Public key (base64url, raw 32 bytes)">
            <Input value={pub} onChange={(e) => setPub(e.target.value)} className="w-80" />
          </Field>
          <Button
            variant="ghost"
            onClick={async () => {
              try {
                const c = await upload(pub.trim());
                setPub("");
                setNote(`Key ${c.kid} added.`);
              } catch (err) {
                setNote(message(err));
              }
            }}
          >
            Add public key
          </Button>
          <Button onClick={generate}>Generate key pair in browser</Button>
        </div>
      )}
      {note && <p role="status" className="mt-2 text-sm">{note}</p>}
    </Card>
  );
}

function WebhooksCard() {
  const { me } = useMe();
  const canManage = me.permissions.includes("webhooks.manage");
  const endpoints = useResource<{ webhooks: Endpoint[] }>("webhooks");
  const deliveries = useResource<{ deliveries: Delivery[] }>("webhook-deliveries");
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");

  const act = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn();
      setNote(done);
      endpoints.reload();
      deliveries.reload();
    } catch (err) {
      setNote(message(err));
    }
  };

  return (
    <Card title="Webhooks">
      <p className="mb-3 text-sm text-[var(--text-muted)]">
        bet.settled, round.settled, transaction.needs_attention, reconciliation.discrepancy — LR1-signed, at-least-once;
        dedupe on event_id.
      </p>
      {endpoints.data && (
        <Table head={["URL", "Status", ""]} empty={!endpoints.data.webhooks.length}>
          {endpoints.data.webhooks.map((e) => (
            <tr key={e.id}>
              <td><Mono>{e.url}</Mono></td>
              <td><Status tone={e.enabled ? "good" : "neutral"}>{e.enabled ? "Enabled" : "Disabled"}</Status></td>
              <td>
                {canManage && e.enabled && (
                  <Button variant="ghost" onClick={() => act(() => api.post(`webhooks/${e.id}/disable`), "Disabled.")}>
                    Disable
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </Table>
      )}
      {canManage && (
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <Field label="Endpoint URL (https)">
            <Input value={url} onChange={(e) => setUrl(e.target.value)} className="w-80" />
          </Field>
          <Button onClick={() => act(() => api.post("webhooks", { url }), "Endpoint enabled.")}>Add endpoint</Button>
        </div>
      )}
      {note && <p role="status" className="mt-2 text-sm">{note}</p>}
      <h3 className="mt-4 mb-2 text-sm font-semibold">Recent deliveries</h3>
      {deliveries.data && (
        <Table head={["Event", "Type", "Status", "Attempts", "Last result", "Created", ""]} empty={!deliveries.data.deliveries.length}>
          {deliveries.data.deliveries.map((d) => (
            <tr key={d.id}>
              <td><Mono>{d.event_id}</Mono></td>
              <td>{d.type}</td>
              <td><Status tone={toneFor(d.status)}>{d.status}</Status></td>
              <td className="tabular">{d.attempts}</td>
              <td className="text-xs">{d.last_status_code ?? d.last_error ?? "—"}</td>
              <td className="text-xs">{when(d.created_at)}</td>
              <td>
                {canManage && d.status !== "PENDING" && (
                  <Button variant="ghost" onClick={() => act(() => api.post(`webhook-deliveries/${d.id}/replay`), "Queued for redelivery.")}>
                    Replay
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

export default function IntegrationPage() {
  return (
    <Shell title="Integration">
      <WalletCard />
      <CredentialsCard />
      <WebhooksCard />
    </Shell>
  );
}
