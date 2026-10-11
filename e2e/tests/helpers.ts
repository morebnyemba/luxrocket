import { execFileSync } from "node:child_process";
import { createHmac } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, type Page } from "@playwright/test";

const backend = resolve(import.meta.dirname, "../../backend");
const repo = resolve(import.meta.dirname, "../..");
// `make stack` generates the stack's credentials in .demo/stack.env (git-ignored).
const stackEnvFile = resolve(repo, ".demo/stack.env");
const stackEnv: Record<string, string> = existsSync(stackEnvFile)
  ? Object.fromEntries(
      readFileSync(stackEnvFile, "utf8")
        .split("\n")
        .filter((l) => l.includes("="))
        .map((l) => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1)]),
    )
  : {};
// Explicitly exported variables win over the generated stack file.
const env = { ...stackEnv, ...process.env, DJANGO_DEBUG: "1" };
// `make stack` writes the demo operator key to .demo/; host-run dev setups use .demo-operator.key.
const keyFile =
  process.env.LR_DEMO_KEY ??
  [resolve(repo, ".demo/operator.key"), resolve(repo, ".demo-operator.key")].find((p) => existsSync(p)) ??
  "";

/** Acts as the operator backend: signed session request, returns the fragment launch URL. */
export function launchUrl(player: string): string {
  return execFileSync("uv", ["run", "python", "scripts/demo_operator.py", "--key", keyFile, "--player", player], {
    cwd: backend,
    env,
    encoding: "utf8",
  }).trim();
}

export function checkInvariants(): string {
  return execFileSync("uv", ["run", "python", "manage.py", "check_invariants"], { cwd: backend, env, encoding: "utf8" });
}

export const stage = (page: Page) => page.getByTestId("stage");
export const panel = (page: Page, i: number) => page.getByTestId(`panel-${i}`);

export async function waitForPhase(page: Page, phase: string, timeout = 200_000) {
  await expect(stage(page)).toHaveAttribute("data-phase", phase, { timeout });
}

/** Wait for a fresh betting window with at least `minMs` left. */
export async function waitForBettingOpen(page: Page) {
  if ((await stage(page).getAttribute("data-phase")) === "BETTING_OPEN") {
    await waitForPhase(page, "FLYING");
  }
  await waitForPhase(page, "BETTING_OPEN");
}

export const portalUrl = process.env.PORTAL_URL ?? "http://localhost:3002";

/** A disposable portal user for this run (the demo owner's state is left alone). */
export function createPortalUser(email: string, password: string, role = "OP_OWNER"): void {
  execFileSync(
    "uv",
    [
      "run", "python", "manage.py", "create_portal_user",
      "--operator", "Demo Sandbox Operator", "--email", email, "--role", role, "--password", password,
    ],
    { cwd: backend, env, encoding: "utf8" },
  );
}

/** RFC 6238 TOTP, as an authenticator app would compute it. */
export function totp(secretB32: string, offsetSteps = 0): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secretB32.replace(/=+$/, "")) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30_000) + offsetSteps));
  const mac = createHmac("sha1", key).update(counter).digest();
  const offset = mac[mac.length - 1]! & 0x0f;
  return String((mac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

export const adminUrl = process.env.ADMIN_URL ?? "http://localhost:3003";

/** A disposable platform staff member for this run (passkey enrolled in the browser). */
export function createPlatformStaff(email: string, password: string, role = "PLAT_SUPERADMIN"): void {
  execFileSync(
    "uv",
    ["run", "python", "manage.py", "create_platform_owner", "--email", email, "--role", role, "--password", password],
    { cwd: backend, env, encoding: "utf8" },
  );
}
