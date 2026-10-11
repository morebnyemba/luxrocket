"use client";

import { Button, message, useResource } from "@luxrocket/console-kit";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { api } from "@/lib/api";
import { verifyWithPasskey, type Me } from "@/lib/session";

const MeContext = createContext<{ me: Me; reload: () => void } | null>(null);

export function useMe() {
  const ctx = useContext(MeContext);
  if (!ctx) throw new Error("useMe outside Shell");
  return ctx;
}

const NAV: { href: string; label: string; perm: string }[] = [
  { href: "/", label: "Overview", perm: "overview.read" },
  { href: "/operators", label: "Operators", perm: "operators.read" },
  { href: "/markets", label: "Markets", perm: "markets.read" },
  { href: "/games", label: "Games", perm: "games.read" },
  { href: "/approvals", label: "Approvals", perm: "" },
  { href: "/finance", label: "Finance", perm: "finance.read" },
  { href: "/rounds", label: "Rounds", perm: "overview.read" },
  { href: "/staff", label: "Staff", perm: "staff.manage" },
  { href: "/audit", label: "Audit", perm: "audit.read" },
  { href: "/account", label: "Account", perm: "" },
];

export function Shell({ title, children }: { title: string; children: ReactNode }) {
  const { data: me, reload } = useResource<Me>(api, "me");
  const path = usePathname();
  const router = useRouter();

  if (!me) return <div className="p-8 text-sm text-[var(--text-muted)]">Loading…</div>;
  const nav = NAV.filter((n) => !n.perm || me.permissions.includes(n.perm));

  return (
    <MeContext.Provider value={{ me, reload }}>
      <div className="flex min-h-screen flex-col md:flex-row">
        <nav aria-label="Main" className="border-b border-[var(--border)] bg-[var(--surface)] p-4 md:w-56 md:border-r md:border-b-0">
          <div className="mb-4">
            <div className="text-sm font-semibold">LUX ROCKET</div>
            <div className="text-xs text-[var(--text-muted)]">Platform console</div>
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
                {me.email} · {me.role.replace("PLAT_", "").toLowerCase()}
              </span>
              <Button
                variant="ghost"
                onClick={async () => {
                  await api.post("auth/logout").catch(() => undefined);
                  router.replace("/login");
                }}
              >
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

/** Privileged writes need a security-key touch within the last few minutes. */
function StepUpDialog({ onDone }: { onDone: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const resolver = useRef<((ok: boolean) => void) | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.onStepUp(
      () =>
        new Promise<boolean>((resolve) => {
          resolver.current = resolve;
          setError("");
          ref.current?.showModal();
        }),
    );
    return () => api.onStepUp(null);
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
      className="m-auto w-[min(92vw,400px)] rounded-lg border border-[var(--border)] bg-[var(--surface)] p-5 text-[var(--text)] backdrop:bg-black/40"
    >
      <div className="flex flex-col gap-3">
        <h2 id="stepup-title" className="text-base font-semibold">
          Confirm with your security key
        </h2>
        <p className="text-sm text-[var(--text-muted)]">
          This is a privileged action. Touch your security key (or use your device&apos;s passkey) to continue.
        </p>
        {error && (
          <p role="alert" className="text-sm">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => finish(false)}>
            Cancel
          </Button>
          <Button
            onClick={async () => {
              try {
                await verifyWithPasskey();
                finish(true);
              } catch (err) {
                setError(message(err));
              }
            }}
          >
            Use security key
          </Button>
        </div>
      </div>
    </dialog>
  );
}
