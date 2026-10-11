"use client";

import { Button, Card, Field, Input, Mono, Notice, Status, Table, toneFor, useResource, message } from "@luxrocket/console-kit";
import Link from "next/link";
import { useState } from "react";

import { Shell, useMe } from "@/components/Shell";
import { api } from "@/lib/api";

type Op = { id: string; legal_name: string; status: string; real_money_enabled: boolean; stream: string; wallet_kind: string };

function Onboard({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [owner, setOwner] = useState("");
  const [countries, setCountries] = useState("ZW");
  const [ccy, setCcy] = useState("USD");
  const [limits, setLimits] = useState({ min: "10", max: "10000", win: "1000000", exposure: "50000000" });
  const [note, setNote] = useState("");
  const [created, setCreated] = useState<{ id: string; owner: string; password: string } | null>(null);

  return (
    <Card title="Onboard an operator">
      <form
        className="grid gap-3 md:grid-cols-3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            const r = await api.post<Op & { owner_temporary_password: string }>("operators", {
              legal_name: name,
              owner_email: owner,
              jurisdictions: countries.split(",").map((c) => c.trim()).filter(Boolean),
              currencies: [
                { currency: ccy, min_stake: limits.min, max_stake: limits.max, max_win: limits.win, round_exposure: limits.exposure },
              ],
            });
            setCreated({ id: r.id, owner, password: r.owner_temporary_password });
            setNote("");
            onDone();
          } catch (err) {
            setNote(message(err));
          }
        }}
      >
        <Field label="Legal name"><Input required value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Portal owner email"><Input type="email" required value={owner} onChange={(e) => setOwner(e.target.value)} /></Field>
        <Field label="Jurisdictions" hint="ISO codes, comma-separated; markets must be open"><Input value={countries} onChange={(e) => setCountries(e.target.value)} /></Field>
        <Field label="Currency"><Input value={ccy} maxLength={3} onChange={(e) => setCcy(e.target.value.toUpperCase())} /></Field>
        <Field label="Min / max stake (minor units)">
          <div className="flex gap-2">
            <Input aria-label="Min stake" value={limits.min} onChange={(e) => setLimits({ ...limits, min: e.target.value })} className="w-24" />
            <Input aria-label="Max stake" value={limits.max} onChange={(e) => setLimits({ ...limits, max: e.target.value })} className="w-28" />
          </div>
        </Field>
        <Field label="Max win / round exposure">
          <div className="flex gap-2">
            <Input aria-label="Max win" value={limits.win} onChange={(e) => setLimits({ ...limits, win: e.target.value })} className="w-28" />
            <Input aria-label="Round exposure" value={limits.exposure} onChange={(e) => setLimits({ ...limits, exposure: e.target.value })} className="w-32" />
          </div>
        </Field>
        <div className="md:col-span-3">
          <Button type="submit">Create in sandbox</Button>
        </div>
      </form>
      {note && <p role="status" className="mt-2 text-sm">{note}</p>}
      {created && (
        <div className="mt-3">
          <Notice tone="warning">
            Created <Link className="underline" href={`/operators/detail?id=${created.id}`}>{created.id}</Link>. Portal owner{" "}
            {created.owner}, temporary password <Mono>{created.password}</Mono> — shown once; send it out of band.
          </Notice>
        </div>
      )}
    </Card>
  );
}

function Body() {
  const { me } = useMe();
  const { data, error, reload } = useResource<{ operators: Op[] }>(api, "operators");
  return (
    <>
      <Card title="Operators">
        {error && <Notice tone="critical">{error}</Notice>}
        {data && (
          <Table head={["Operator", "Id", "Status", "Real money", "Wallet", "Stream"]} empty={!data.operators.length}>
            {data.operators.map((o) => (
              <tr key={o.id}>
                <td><Link className="underline" href={`/operators/detail?id=${o.id}`}>{o.legal_name}</Link></td>
                <td><Mono>{o.id}</Mono></td>
                <td><Status tone={o.status === "LIVE" ? "good" : o.status === "SUSPENDED" ? "critical" : "neutral"}>{o.status}</Status></td>
                <td><Status tone={o.real_money_enabled ? "good" : "neutral"}>{o.real_money_enabled ? "Enabled" : "Off"}</Status></td>
                <td><Status tone={toneFor(o.wallet_kind === "SEAMLESS_V1" ? "OK" : "")}>{o.wallet_kind}</Status></td>
                <td>{o.stream}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      {me.permissions.includes("operators.manage") && <Onboard onDone={reload} />}
    </>
  );
}

export default function OperatorsPage() {
  return (
    <Shell title="Operators">
      <Body />
    </Shell>
  );
}
