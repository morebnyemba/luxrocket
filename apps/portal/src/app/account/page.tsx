"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Shell, useMe } from "@/components/Shell";
import { Button, Card, Field, Input, Mono, Notice, Status, Table } from "@/components/ui";
import { api, message } from "@/lib/api";
import { when } from "@/lib/format";
import { useResource } from "@/lib/hooks";

type Session = { id: string; current: boolean; created_at: string; last_seen_at: string; ip: string | null; user_agent: string };

function Password() {
  const { me, reload } = useMe();
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [note, setNote] = useState("");
  return (
    <Card title="Password">
      {me.must_change_password && <Notice tone="warning">Choose a new password to continue.</Notice>}
      <form
        className="mt-3 flex flex-wrap items-end gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api.post("me/password", { current, new: next });
            setCurrent("");
            setNext("");
            setNote("Password changed. Your other sessions were signed out.");
            const first = me.must_change_password;
            reload();
            if (first) router.replace("/");
          } catch (err) {
            setNote(message(err));
          }
        }}
      >
        <Field label="Current password">
          <Input type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
        </Field>
        <Field label="New password" hint="At least 12 characters">
          <Input type="password" autoComplete="new-password" minLength={12} required value={next} onChange={(e) => setNext(e.target.value)} />
        </Field>
        <Button type="submit">Change password</Button>
      </form>
      {note && <p role="status" className="mt-2 text-sm">{note}</p>}
    </Card>
  );
}

function TwoFactor() {
  const { me, reload } = useMe();
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [note, setNote] = useState("");
  if (me.mfa_enabled) {
    return (
      <Card title="Two-factor authentication">
        <Status tone="good">Enabled (authenticator app)</Status>
      </Card>
    );
  }
  return (
    <Card title="Two-factor authentication">
      <p className="mb-3 text-sm text-[var(--text-muted)]">
        Required for managing credentials, the wallet endpoint and team access.
      </p>
      {!setup ? (
        <Button
          onClick={async () => {
            try {
              setSetup(await api.post("me/mfa/setup"));
            } catch (err) {
              setNote(message(err));
            }
          }}
        >
          Set up authenticator
        </Button>
      ) : (
        <form
          className="flex flex-col gap-3"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await api.post("me/mfa/enable", { code });
              setSetup(null);
              reload();
            } catch (err) {
              setNote(message(err));
            }
          }}
        >
          <p className="text-sm">
            Add this key to your authenticator app (shown once). Key: <Mono>{setup.secret}</Mono>
          </p>
          <p className="text-xs text-[var(--text-muted)]">
            Or open: <a className="underline" href={setup.uri}>{setup.uri.split("?")[0]}</a>
          </p>
          <Field label="6-digit code">
            <Input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" required value={code} onChange={(e) => setCode(e.target.value)} className="w-40" />
          </Field>
          <div>
            <Button type="submit">Enable</Button>
          </div>
        </form>
      )}
      {note && <p role="status" className="mt-2 text-sm">{note}</p>}
    </Card>
  );
}

function Sessions() {
  const { data, reload } = useResource<{ sessions: Session[] }>("me/sessions");
  return (
    <Card title="Active sessions">
      {data && (
        <Table head={["Started", "Last seen", "IP", "Browser", ""]} empty={!data.sessions.length}>
          {data.sessions.map((s) => (
            <tr key={s.id}>
              <td className="text-xs">{when(s.created_at)}</td>
              <td className="text-xs">{when(s.last_seen_at)}</td>
              <td>{s.ip ?? "—"}</td>
              <td className="max-w-xs truncate text-xs" title={s.user_agent}>{s.user_agent}</td>
              <td>
                {s.current ? (
                  <Status tone="good">This session</Status>
                ) : (
                  <Button variant="ghost" onClick={async () => { await api.post(`me/sessions/${s.id}/revoke`); reload(); }}>
                    Sign out
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

export default function AccountPage() {
  return (
    <Shell title="Account">
      <Password />
      <TwoFactor />
      <Sessions />
    </Shell>
  );
}
