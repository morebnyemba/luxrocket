"use client";

import { useState } from "react";

import { Shell, useMe } from "@/components/Shell";
import { Button, Card, Field, Input, Mono, Notice, Select, Status, Table, toneFor } from "@/components/ui";
import { api, message } from "@/lib/api";
import { when } from "@/lib/format";
import { useResource } from "@/lib/hooks";

type User = { id: string; email: string; role: string; status: string; mfa_enabled: boolean; created_at: string };
type Event = { seq: number; at: string; actor: string; action: string; target: string; data: Record<string, unknown>; ip: string | null; hash: string };

const ROLES = ["OP_OWNER", "OP_ADMIN", "OP_DEVELOPER", "OP_FINANCE", "OP_SUPPORT", "OP_VIEWER"];

function Users() {
  const { me } = useMe();
  const { data, error, reload } = useResource<{ users: User[] }>("users");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("OP_VIEWER");
  const [note, setNote] = useState("");
  const [temp, setTemp] = useState<{ email: string; password: string } | null>(null);
  const roles = me.role === "OP_OWNER" ? ROLES : ROLES.filter((r) => r !== "OP_OWNER");

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
    <Card title="Users">
      {error && <Notice tone="critical">{error}</Notice>}
      {data && (
        <Table head={["Email", "Role", "Status", "2FA", ""]} empty={!data.users.length}>
          {data.users.map((u) => {
            const self = u.email === me.email;
            const editable = !self && (me.role === "OP_OWNER" || u.role !== "OP_OWNER");
            return (
              <tr key={u.id}>
                <td>{u.email}{self && " (you)"}</td>
                <td>
                  {editable ? (
                    <Select
                      aria-label={`Role for ${u.email}`}
                      value={u.role}
                      onChange={(e) => act(() => api.patch(`users/${u.id}`, { role: e.target.value }), "Role updated.")}
                    >
                      {roles.map((r) => (
                        <option key={r} value={r}>{r}</option>
                      ))}
                    </Select>
                  ) : (
                    u.role
                  )}
                </td>
                <td><Status tone={toneFor(u.status)}>{u.status}</Status></td>
                <td><Status tone={u.mfa_enabled ? "good" : "warning"}>{u.mfa_enabled ? "On" : "Off"}</Status></td>
                <td className="flex flex-wrap gap-2">
                  {editable && (
                    <Button
                      variant="ghost"
                      onClick={() =>
                        act(
                          () => api.patch(`users/${u.id}`, { status: u.status === "ACTIVE" ? "DISABLED" : "ACTIVE" }),
                          u.status === "ACTIVE" ? "Disabled; their sessions were ended." : "Re-enabled.",
                        )
                      }
                    >
                      {u.status === "ACTIVE" ? "Disable" : "Enable"}
                    </Button>
                  )}
                  {editable && u.mfa_enabled && (
                    <Button variant="danger" onClick={() => act(() => api.post(`users/${u.id}/reset-mfa`), "2FA reset; they must enrol again.")}>
                      Reset 2FA
                    </Button>
                  )}
                </td>
              </tr>
            );
          })}
        </Table>
      )}
      <form
        className="mt-4 flex flex-wrap items-end gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            const r = await api.post<User & { temporary_password: string }>("users", { email, role });
            setTemp({ email: r.email, password: r.temporary_password });
            setEmail("");
            reload();
          } catch (err) {
            setNote(message(err));
          }
        }}
      >
        <Field label="Email">
          <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Role">
          <Select value={role} onChange={(e) => setRole(e.target.value)}>
            {roles.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </Select>
        </Field>
        <Button type="submit">Add user</Button>
      </form>
      {temp && (
        <Notice tone="warning">
          Temporary password for {temp.email}: <Mono>{temp.password}</Mono> — shown once. They must change it at first sign-in.
        </Notice>
      )}
      {note && <p role="status" className="mt-2 text-sm">{note}</p>}
    </Card>
  );
}

function Audit() {
  const [before, setBefore] = useState<string | null>(null);
  const { data, error } = useResource<{ events: Event[]; next: string | null }>(before ? `audit?before=${before}` : "audit");
  return (
    <Card title="Audit history" actions={data?.next ? <Button variant="ghost" onClick={() => setBefore(data.next)}>Older</Button> : null}>
      <p className="mb-3 text-xs text-[var(--text-muted)]">
        Append-only and hash-chained: each event&apos;s hash covers the previous one, so edits are detectable.
      </p>
      {error && <Notice tone="critical">{error}</Notice>}
      {data && (
        <Table head={["#", "When", "Who", "Action", "Target", "Details", "Hash"]} empty={!data.events.length}>
          {data.events.map((e) => (
            <tr key={e.seq}>
              <td className="tabular">{e.seq}</td>
              <td className="text-xs">{when(e.at)}</td>
              <td>{e.actor}</td>
              <td>{e.action}</td>
              <td><Mono>{e.target}</Mono></td>
              <td><Mono>{Object.keys(e.data).length ? JSON.stringify(e.data) : ""}</Mono></td>
              <td><Mono>{e.hash.slice(0, 12)}…</Mono></td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

export default function TeamPage() {
  return (
    <Shell title="Team & audit">
      <Users />
      <Audit />
    </Shell>
  );
}
