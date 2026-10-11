import { expect, test } from "@playwright/test";

import { createPortalUser, portalUrl, totp } from "./helpers";

// Operator portal (doc 13) end to end through the real static build or dev server + API.
test.use({ baseURL: portalUrl, viewport: { width: 1280, height: 900 } });

test("owner signs in, enrols 2FA, creates a key in the browser and sees it audited", async ({ page }) => {
  const email = `e2e-${Date.now()}@luxrocket.local`;
  const password = "e2e-portal-passphrase";
  createPortalUser(email, password);

  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText("Wallet health")).toBeVisible();

  // Credential management requires 2FA: the API says so and the UI explains it.
  await page.getByRole("link", { name: "Integration" }).click();
  await expect(page.getByText("Platform signing keys")).toBeVisible();
  await page.getByRole("button", { name: "Generate key pair in browser" }).click();
  await expect(page.getByText("Set up two-factor authentication")).toBeVisible();

  // Enrol an authenticator.
  await page.getByRole("link", { name: "Account" }).click();
  await page.getByRole("button", { name: "Set up authenticator" }).click();
  const secret = (await page.locator("code").first().textContent())!.trim();
  await page.getByLabel("6-digit code").fill(totp(secret));
  await page.getByRole("button", { name: "Enable" }).click();
  await expect(page.getByText("Enabled (authenticator app)")).toBeVisible();

  // Generate an Ed25519 pair in the browser: only the public half is uploaded.
  await page.getByRole("link", { name: "Integration" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Generate key pair in browser" }).click();
  const pem = await download;
  expect(pem.suggestedFilename()).toMatch(/^k_.*\.pem$/);
  await expect(page.getByText(/created\. The private key was downloaded once/)).toBeVisible();

  // The action is in the tenant's hash-chained audit history.
  await page.getByRole("link", { name: "Team & audit" }).click();
  await expect(page.getByRole("cell", { name: "credential.created" }).first()).toBeVisible();
  await expect(page.getByRole("cell", { name: "auth.mfa_enabled" }).first()).toBeVisible();

  // Signing in again now asks for the second factor (a fresh code: codes are single-use).
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByLabel("Authenticator code").fill(totp(secret, 1));
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
});

test("the portal is never framed and the API is not reachable cross-site", async ({ page, request }) => {
  const res = await request.get(`${portalUrl}/login`);
  if (portalUrl.endsWith(":3002")) {
    // nginx (static build) sets the console headers; `next dev` does not.
    expect(res.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
    expect(res.headers()["x-frame-options"]).toBe("DENY");
  }
  const forged = await request.post(`${portalUrl}/api/portal/v1/auth/login`, {
    data: { email: "x@y.z", password: "x" },
    headers: { Origin: "https://evil.example", "X-LR-Portal": "1" },
  });
  expect(forged.status()).toBe(403);
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
});
