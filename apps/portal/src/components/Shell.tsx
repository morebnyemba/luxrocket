"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { api, message, onStepUp } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { Me } from "@/lib/types";

import { Button, Input } from "./ui";

const MeContext = createContext<{ me: Me; reload: () => void } | null>(null);

export function useMe() {
  const ctx = useContext(MeContext);
  if (!ctx) throw new Error("useMe outside Shell");
  return ctx;
}

const NAV: { href: string; label: string; perm: string }[] = [
  { href: "/", label: "Overview", perm: "overview.read" },
  { href: "/bets", label: "Bets", perm: "reports.read" },
  { href: "/rounds", label: "Rounds", perm: "reports.read" },
  { href: "/reconciliation", label: "Reconciliation", perm: "reconciliation.read" },
  { href: "/integration", label: "Integration", perm: "integration.read" },
  { href: "/team", label: "Team & audit", perm: "users.manage" },
  { href: "/account", label: "Account", perm: "" },
];

export function Shell({ title, children }: { title: string; children: ReactNode }) {
  const { data: me, reload } = useResource<Me>("me");
  const path = usePathname();
  const router = useRouter();

  if (!me) {
    return <div className="p-8 text-sm text-[var(--text-muted)]">Loading…</div>;
  }
  const nav = NAV.filter((n) => !n.perm || me.permissions.includes(n.perm));
  const logout = async () => {
    await api.post("auth/logout").catch(() => undefined);
    router.replace("/login");
  };

  return (
    <MeContext.Provider value={{ me, reload }}>
      <div className="flex min-h-screen flex-col md:flex-row">
        <nav aria-label="Main" className="border-b border-[var(--border)] bg-[var(--surface)] p-4 md:w-56 md:border-r md:border-b-0">
          <div className="mb-4">
            <div className="text-sm font-semibold">LUX ROCKET</div>
            <div className="text-xs text-[var(--text-muted)]">{me.operator.name}</div>
          </div>
          <ul className="flex flex-wrap gap-1 md:flex-col">
            {nav.map((n) => {
              const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
              return (
                <li key={n.href}>
                  <Link
                    href={n.href}
                    aria-current={active ? "page" : undefined}
                    className={`block rounded-md px-2 py-1.5 text-sm ${active ? "bg-[var(--surface-2)] font-medium" : "text-[var(--text-muted)] hover:text-[var(--text)]"}`}
                  >
                    {n.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center justify-between gap-2 border-b border-[var(--border)] bg-[var(--surface)] px-4 py-3">
            <h1 className="text-lg font-semibold">{title}</h1>
            <div className="flex items-center gap-3 text-xs text-[var(--text-muted)]">
              <span className="hidden sm:inline">
                {me.email} · {me.role.replace("OP_", "").toLowerCase()} · {me.operator.status.toLowerCase()}
              </span>
              <Button variant="ghost" onClick={logout}>
                Sign out
              </Button>
            </div>
          </header>
          <main className="flex flex-col gap-4 p-4">{children}</main>
        </div>
      </div>
      <StepUpDialog onDone={reload} />
    </MeContext.Provider>
  );
}

/** Asks for a TOTP code when the API answers STEP_UP_REQUIRED, then retries the action. */
function StepUpDialog({ onDone }: { onDone: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const resolver = useRef<((ok: boolean) => void) | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    onStepUp(
      () =>
        new Promise<boolean>((resolve) => {
          resolver.current = resolve;
          setCode("");
          setError("");
          ref.current?.showModal();
        }),
    );
    return () => onStepUp(null);
  }, []);

  const finish = (ok: boolean) => {
    ref.current?.close();
    resolver.current?.(ok);
    resolver.current = null;
    if (ok) onDone();
  };

  return (
    <dialog
      ref={ref}
      aria-labelledby="stepup-title"
      onCancel={() => finish(false)}
      className="m-auto w-[min(92vw,380px)] rounded-lg border border-[var(--border)] bg-[var(--surface)] p-5 text-[var(--text)] backdrop:bg-black/40"
    >
      <form
        className="flex flex-col gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api.post("auth/mfa", { code });
            finish(true);
          } catch (err) {
            setError(message(err));
          }
        }}
      >
        <h2 id="stepup-title" className="text-base font-semibold">
          Confirm it&apos;s you
        </h2>
        <p className="text-sm text-[var(--text-muted)]">
          This action changes credentials, the wallet or team access. Enter the 6-digit code from your authenticator.
        </p>
        <Input
          autoFocus
          inputMode="numeric"
          autoComplete="one-time-code"
          aria-label="Authenticator code"
          pattern="[0-9]{6}"
          value={code}
          onChange={(e) => setCode(e.target.value)}
        />
        {error && (
          <p role="alert" className="text-sm">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => finish(false)}>
            Cancel
          </Button>
          <Button type="submit">Confirm</Button>
        </div>
      </form>
    </dialog>
  );
}
