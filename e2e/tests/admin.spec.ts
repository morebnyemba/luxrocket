import { expect, test, type Browser, type Page } from "@playwright/test";

import { adminUrl, createPlatformStaff } from "./helpers";

// Platform console (doc 12): passkey-only staff sign-in and four-eyes approvals, end to end.
// Each person gets their own browser context with a CDP virtual authenticator (a "security key").

async function staffPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ baseURL: adminUrl, viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: {
      protocol: "ctap2",
      transport: "usb",
      hasResidentKey: false,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  });
  return page;
}

async function signInAndEnrol(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("First sign-in: register a security key")).toBeVisible();
  await page.getByRole("button", { name: "Register security key" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

test("onboard, suspend and reactivate an operator with two different people", async ({ browser }) => {
  const run = Date.now();
  const password = "e2e-console-passphrase";
  const alice = `alice-${run}@luxrocket.local`;
  const bob = `bob-${run}@luxrocket.local`;
  createPlatformStaff(alice, password);
  createPlatformStaff(bob, password);

  // Alice: passkey enrolment, then onboard a fresh sandbox operator.
  const a = await staffPage(browser);
  await signInAndEnrol(a, alice, password);
  await a.getByRole("link", { name: "Operators" }).click();
  const name = `E2E Casino ${run}`;
  await a.getByLabel("Legal name").fill(name);
  await a.getByLabel("Portal owner email").fill(`owner-${run}@casino.test`);
  await a.getByRole("button", { name: "Create in sandbox" }).click();
  await expect(a.getByText(/temporary password/)).toBeVisible();
  await a.getByRole("link", { name: /^op_/ }).click();
  await expect(a.getByRole("heading", { name: name, exact: true })).toBeVisible();

  // Suspend is immediate; reactivation is a request.
  await a.getByLabel("Reason (required, audited)").fill("e2e: credential rotation drill");
  await a.getByRole("button", { name: "Suspend now" }).click();
  await expect(a.getByText("Suspended; sessions revoked.")).toBeVisible();
  await a.getByRole("button", { name: "Request reactivation" }).click();
  await expect(a.getByText(/another person must approve/)).toBeVisible();

  // Alice cannot approve her own request.
  await a.getByRole("link", { name: "Approvals" }).click();
  const mine = a.getByRole("row", { name: new RegExp(name) });
  await expect(mine.getByText("Your request — someone else must decide.")).toBeVisible();
  await expect(mine.getByRole("button", { name: "Approve" })).toHaveCount(0);

  // Bob, on his own key, approves with a note; the change executes atomically.
  const b = await staffPage(browser);
  await signInAndEnrol(b, bob, password);
  await b.getByRole("link", { name: "Approvals" }).click();
  const row = b.getByRole("row", { name: new RegExp(name) });
  await row.getByLabel("Decision note").fill("rotation verified with the operator");
  await row.getByRole("button", { name: "Approve" }).click();
  await expect(b.getByText("Request approved and executed.")).toBeVisible();

  // Both actions are in the hash-chained audit log, and the chain verifies.
  await b.getByRole("link", { name: "Audit" }).click();
  await expect(b.getByText(/Intact: \d+ events/)).toBeVisible();
  await expect(b.getByRole("cell", { name: "approval.approved" }).first()).toBeVisible();

  // Signing in again needs the security key, not just the password.
  await a.getByRole("button", { name: "Sign out" }).click();
  await a.getByLabel("Email").fill(alice);
  await a.getByLabel("Password").fill(password);
  await a.getByRole("button", { name: "Continue" }).click();
  await a.getByRole("button", { name: "Use security key" }).click();
  await expect(a.getByRole("heading", { name: "Overview" })).toBeVisible();
});

test("the console is never framed and rejects cross-site writes", async ({ request }) => {
  const res = await request.get(`${adminUrl}/login`);
  if (adminUrl.endsWith(":3003")) {
    expect(res.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
  }
  const forged = await request.post(`${adminUrl}/api/admin/v1/auth/login`, {
    data: { email: "x@y.z", password: "x" },
    headers: { Origin: "https://evil.example", "X-LR-Portal": "1" },
  });
  expect(forged.status()).toBe(403);
});
