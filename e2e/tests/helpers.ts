import { execFileSync } from "node:child_process";
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
const env = { ...process.env, ...stackEnv, DJANGO_DEBUG: "1" };
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
