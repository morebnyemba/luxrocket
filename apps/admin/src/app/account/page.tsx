"use client";

import { Button, Card, Field, Input, Notice, Table, message, when } from "@luxrocket/console-kit";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Shell, useMe } from "@/components/Shell";
import { api } from "@/lib/api";
import { registerPasskey } from "@/lib/session";

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
            setNote("Password changed; your other sessions were signed out.");
            const first = me.must_change_password;
            reload();
            if (first) router.replace("/");
          } catch (err) {
            setNote(message(err));
          }
        }}
      >
        <Field label="Current password"><Input type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} /></Field>
        <Field label="New password" hint="At least 14 characters"><Input type="password" autoComplete="new-password" minLength={14} required value={next} onChange={(e) => setNext(e.target.value)} /></Field>
        <Button type="submit">Change password</Button>
      </form>
      {note && <p role="status" className="mt-2 text-sm">{note}</p>}
    </Card>
  );
}

function Keys() {
  const { me, reload } = useMe();
  const [name, setName] = useState("Backup key");
  const [note, setNote] = useState("");
  return (
    <Card title="Security keys">
      <p className="mb-3 text-sm text-[var(--text-muted)]">Register a second key and keep it somewhere safe: losing your only key means asking a superadmin to reset it.</p>
      <Table head={["Name", "Registered", "Last used"]} empty={!me.passkeys.length}>
        {me.passkeys.map((k) => (
          <tr key={k.id}>
            <td>{k.name}</td>
            <td className="text-xs">{when(k.created_at)}</td>
            <td className="text-xs">{when(k.last_used_at)}</td>
          </tr>
        ))}
      </Table>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Button
          variant="ghost"
          onClick={async () => {
            try {
              await registerPasskey(name);
              setNote("Key registered.");
              reload();
            } catch (err) {
              setNote(message(err));
            }
          }}
        >
          Add security key
        </Button>
      </div>
      {note && <p role="status" className="mt-2 text-sm">{note}</p>}
    </Card>
  );
}

export default function AccountPage() {
  return (
    <Shell title="Account">
      <Password />
      <Keys />
    </Shell>
  );
}
