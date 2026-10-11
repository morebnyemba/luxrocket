"use client";

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }) {
  const styles = {
    primary: "bg-[var(--accent)] text-[var(--accent-ink)] hover:brightness-105",
    ghost: "border border-[var(--border)] bg-[var(--surface)] hover:bg-[var(--surface-2)]",
    danger: "border border-[var(--critical)] text-[var(--text)] hover:bg-[var(--surface-2)]",
  }[variant];
  return (
    <button
      className={`inline-flex h-9 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium disabled:opacity-50 ${styles} ${className}`}
      {...props}
    />
  );
}

export function Card({ title, actions, children }: { title?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      {(title || actions) && (
        <header className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold">{title}</h2>}
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium">{label}</span>
      {children}
      {hint && <span className="text-xs text-[var(--text-muted)]">{hint}</span>}
    </label>
  );
}

const control =
  "h-9 rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 text-sm text-[var(--text)]";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${control} ${props.className ?? ""}`} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${control} ${props.className ?? ""}`} />;
}

type Tone = "good" | "warning" | "serious" | "critical" | "neutral";
const ICON: Record<Tone, string> = { good: "✓", warning: "!", serious: "▲", critical: "✕", neutral: "•" };

/** Status never relies on colour alone: icon + label, ink stays a text token. */
export function Status({ tone, children }: { tone: Tone; children: ReactNode }) {
  const color = tone === "neutral" ? "var(--text-muted)" : `var(--${tone})`;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium">
      <span
        aria-hidden
        className="inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] text-white"
        style={{ background: color }}
      >
        {ICON[tone]}
      </span>
      {children}
    </span>
  );
}

export function toneFor(status: string): Tone {
  if (["SUCCEEDED", "CONFIRMED", "DELIVERED", "ACTIVE", "CASHED_OUT", "COMPLETED", "OK"].includes(status)) return "good";
  if (["PENDING", "UNKNOWN", "DEBIT_UNKNOWN", "PENDING_DEBIT", "RUNNING", "SETTLING"].includes(status)) return "warning";
  if (["NEEDS_ATTENTION", "FAILED", "CRITICAL", "OPEN", "UNAVAILABLE"].includes(status)) return "critical";
  if (["REJECTED", "VOIDED", "EXCLUDED", "WARNING", "DISABLED", "REVOKED"].includes(status)) return "serious";
  return "neutral";
}

export function Notice({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <div role={tone === "critical" ? "alert" : "status"} className="rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-3 text-sm">
      <Status tone={tone}>{children}</Status>
    </div>
  );
}

export function Table({ head, children, empty }: { head: string[]; children: ReactNode; empty?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--text-muted)]">
            {head.map((h) => (
              <th key={h} scope="col" className="px-2 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="[&>tr]:border-b [&>tr]:border-[var(--border)] [&_td]:px-2 [&_td]:py-2">{children}</tbody>
      </table>
      {empty && <p className="p-4 text-center text-sm text-[var(--text-muted)]">Nothing here yet.</p>}
    </div>
  );
}

export function Mono({ children }: { children: ReactNode }) {
  return <code className="break-all font-mono text-xs">{children}</code>;
}
