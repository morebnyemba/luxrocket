"use client";

import { Button, Field, Input, message } from "@luxrocket/console-kit";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { api } from "@/lib/api";
import { registerPasskey, verifyWithPasskey } from "@/lib/session";

export default function LoginPage() {
  const router = useRouter();
  const [step, setStep] = useState<"password" | "passkey" | "enroll">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [keyName, setKeyName] = useState("Security key");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };
  const done = (r: { must_change_password: boolean }) => router.replace(r.must_change_password ? "/account?first=1" : "/");

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div className="flex w-full max-w-sm flex-col gap-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6">
        <div>
          <h1 className="text-lg font-semibold">LUX ROCKET · Platform console</h1>
          <p className="text-sm text-[var(--text-muted)]">
            {step === "password" && "Staff sign-in. A security key is required."}
            {step === "passkey" && "Touch your security key to finish signing in."}
            {step === "enroll" && "First sign-in: register a security key. It will be required every time."}
          </p>
        </div>
        {step === "password" && (
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                const r = await api.post<{ next: "passkey" | "enroll" }>("auth/login", { email, password });
                setStep(r.next);
              });
            }}
          >
            <Field label="Email">
              <Input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label="Password">
              <Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <Button type="submit" disabled={busy}>
              Continue
            </Button>
          </form>
        )}
        {step === "passkey" && (
          <Button disabled={busy} onClick={() => run(async () => done(await verifyWithPasskey()))}>
            Use security key
          </Button>
        )}
        {step === "enroll" && (
          <>
            <Field label="Key name" hint="So you can tell your keys apart later">
              <Input value={keyName} onChange={(e) => setKeyName(e.target.value)} />
            </Field>
            <Button disabled={busy} onClick={() => run(async () => done(await registerPasskey(keyName)))}>
              Register security key
            </Button>
          </>
        )}
        {error && (
          <p role="alert" className="text-sm">
            {error}
          </p>
        )}
      </div>
    </main>
  );
}
