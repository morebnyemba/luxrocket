"use client";

import { Button, Card, Field, Input, Mono, Notice, Select, Status, Table, toneFor, useResource, message } from "@luxrocket/console-kit";
import { useState } from "react";

import { Shell, useMe } from "@/components/Shell";
import { api } from "@/lib/api";

type Staff = { id: string; email: string; role: string; status: string; passkeys: number };
const ROLES = ["PLAT_SUPERADMIN", "PLAT_OPS", "PLAT_FINANCE", "PLAT_RISK", "PLAT_SUPPORT", "PLAT_GAME_RELEASE", "PLAT_AUDITOR"];

function Body() {
  const { me } = useMe();
  const { data, error, reload } = useResource<{ staff: Staff[] }>(api, "staff");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("PLAT_SUPPORT");
  const [note, setNote] = useState("");
  const [temp, setTemp] = useState<{ email: string; password: string } | null>(null);
  const roles = me.role === "PLAT_OWNER" ? ROLES : ROLES.filter((r) => r !== "PLAT_SUPERADMIN");
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
    <Card title="Platform staff">
      {error && <Notice tone="critical">{error}</Notice>}
      {data && (
        <Table head={["Email", "Role", "Status", "Passkeys", ""]} empty={!data.staff.length}>
          {data.staff.map((s) => {
            const editable = s.email !== me.email && s.role !== "PLAT_OWNER" && (me.role === "PLAT_OWNER" || s.role !== "PLAT_SUPERADMIN");
            return (
              <tr key={s.id}>
                <td>{s.email}{s.email === me.email && " (you)"}</td>
                <td>
                  {editable ? (
                    <Select aria-label={`Role for ${s.email}`} value={s.role} onChange={(e) => act(() => api.patch(`staff/${s.id}`, { role: e.target.value }), "Role updated.")}>
                      {roles.map((r) => <option key={r}>{r}</option>)}
                    </Select>
                  ) : (
                    s.role
                  )}
                </td>
                <td><Status tone={toneFor(s.status)}>{s.status}</Status></td>
                <td><Status tone={s.passkeys ? "good" : "warning"}>{s.passkeys ? `${s.passkeys} key(s)` : "Not enrolled"}</Status></td>
                <td className="flex flex-wrap gap-2">
                  {editable && (
                    <Button variant="ghost" onClick={() => act(() => api.patch(`staff/${s.id}`, { status: s.status === "ACTIVE" ? "DISABLED" : "ACTIVE" }), "Updated; sessions ended if disabled.")}>
                      {s.status === "ACTIVE" ? "Disable" : "Enable"}
                    </Button>
                  )}
                  {editable && s.passkeys > 0 && (
                    <Button variant="danger" onClick={() => act(() => api.post(`staff/${s.id}/reset-passkeys`), "Keys removed; they must enrol again at next sign-in.")}>
                      Reset keys
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
            const r = await api.post<Staff & { temporary_password: string }>("staff", { email, role });
            setTemp({ email: r.email, password: r.temporary_password });
            setEmail("");
            reload();
          } catch (err) {
            setNote(message(err));
          }
        }}
      >
        <Field label="Email"><Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Role">
          <Select value={role} onChange={(e) => setRole(e.target.value)}>{roles.map((r) => <option key={r}>{r}</option>)}</Select>
        </Field>
        <Button type="submit">Add staff member</Button>
      </form>
      {temp && (
        <div className="mt-3">
          <Notice tone="warning">
            Temporary password for {temp.email}: <Mono>{temp.password}</Mono> — shown once. They register a security key at first sign-in.
          </Notice>
        </div>
      )}
      {note && <p role="status" className="mt-2 text-sm">{note}</p>}
    </Card>
  );
}

export default function StaffPage() {
  return (
    <Shell title="Staff">
      <Body />
    </Shell>
  );
}
