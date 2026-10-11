"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Button, Field, Input } from "@/components/ui";
import { api, message } from "@/lib/api";

type LoginResult = { mfa_required: boolean; must_change_password: boolean };

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [step, setStep] = useState<"password" | "mfa">(params.get("step") === "mfa" ? "mfa" : "password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (step === "password") {
        const r = await api.post<LoginResult>("auth/login", { email, password });
        if (r.mfa_required) {
          setStep("mfa");
          return;
        }
        router.replace(r.must_change_password ? "/account?first=1" : "/");
      } else {
        await api.post("auth/mfa", { code });
        router.replace("/");
      }
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex w-full max-w-sm flex-col gap-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6">
      <div>
        <h1 className="text-lg font-semibold">LUX ROCKET · Operator portal</h1>
        <p className="text-sm text-[var(--text-muted)]">
          {step === "password" ? "Sign in with your staff account." : "Enter the code from your authenticator app."}
        </p>
      </div>
      {step === "password" ? (
        <>
          <Field label="Email">
            <Input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Password">
            <Input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
        </>
      ) : (
        <Field label="Authenticator code">
          <Input
            autoFocus
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]{6}"
            required
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        </Field>
      )}
      {error && (
        <p role="alert" className="text-sm">
          {error}
        </p>
      )}
      <Button type="submit" disabled={busy}>
        {step === "password" ? "Sign in" : "Verify"}
      </Button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <Suspense>
        <LoginForm />
      </Suspense>
    </main>
  );
}
