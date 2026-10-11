import { expect, test } from "@playwright/test";
import { checkInvariants, launchUrl, panel, stage, waitForBettingOpen, waitForPhase } from "./helpers";

test("two players share one authoritative round; each panel settles independently", async ({ browser }) => {
  const a = await (await browser.newContext()).newPage();
  const b = await (await browser.newContext()).newPage();
  await a.goto(launchUrl(`e2e-a-${Date.now()}`));
  await b.goto(launchUrl(`e2e-b-${Date.now()}`));
  await expect(panel(a, 0)).toBeVisible();
  await expect(panel(b, 0)).toBeVisible();
  // The fragment token is removed from the address bar immediately (FR-004).
  expect(a.url()).not.toContain("lt_");

  await waitForBettingOpen(a);

  // Player A: panel 0 auto cash-out at 1.01x, panel 1 manual. Player B: panel 0 manual.
  await panel(a, 0).getByRole("checkbox").check();
  const autoInput = panel(a, 0).getByLabel("Auto cash-out multiplier");
  await autoInput.fill("1.01");
  await autoInput.blur();
  await panel(a, 0).getByTestId("bet").click();
  await panel(a, 1).getByTestId("bet").click();
  await panel(b, 0).getByTestId("bet").click();

  await expect(panel(a, 0)).toHaveAttribute("data-status", /PLACED|ACTIVE/);
  await expect(panel(a, 1)).toHaveAttribute("data-status", /PLACED|ACTIVE/);
  await expect(panel(b, 0)).toHaveAttribute("data-status", /PLACED|ACTIVE/);
  const round = await stage(a).getAttribute("data-round");
  expect(await stage(b).getAttribute("data-round")).toBe(round);

  // Manual cash-out on A's panel 1 as soon as the flight starts.
  await waitForPhase(a, "FLYING", 30_000);
  await expect(panel(a, 1)).toHaveAttribute("data-status", /ACTIVE|LOST/);
  if ((await panel(a, 1).getAttribute("data-status")) === "ACTIVE") {
    await panel(a, 1).getByTestId("cashout").click();
  }

  await waitForPhase(a, "CRASHED");
  await waitForPhase(b, "CRASHED", 10_000);
  const crashA = Number(await stage(a).getAttribute("data-crash"));
  const crashB = Number(await stage(b).getAttribute("data-crash"));
  expect(crashA).toBe(crashB); // same authoritative outcome for everyone
  expect(crashA).toBeGreaterThanOrEqual(10_000);

  // Panel 0 auto 1.01x: wins iff the rocket reached 1.01x.
  await expect(panel(a, 0)).toHaveAttribute("data-status", crashA >= 10_100 ? "CASHED_OUT" : "LOST");
  if (crashA >= 10_100) await expect(panel(a, 0)).toContainText("credited", { timeout: 15_000 });
  // Panel 1 settled independently of panel 0.
  await expect(panel(a, 1)).toHaveAttribute("data-status", /CASHED_OUT|LOST/);
  // B never cashed out: lost (unless instant crash refunded nothing — still LOST).
  await expect(panel(b, 0)).toHaveAttribute("data-status", "LOST");

  expect(checkInvariants()).not.toContain("FAIL");
});

test("a launch token works exactly once", async ({ browser }) => {
  const url = launchUrl(`e2e-replay-${Date.now()}`);
  const first = await (await browser.newContext()).newPage();
  await first.goto(url);
  await expect(panel(first, 0)).toBeVisible();
  const second = await (await browser.newContext()).newPage();
  await second.goto(url);
  await expect(second.getByTestId("ended")).toBeVisible();
});

test("operator embed: postMessage handshake launches the game without a token in any URL", async ({ page }) => {
  await page.goto("http://localhost:8000/demo/operator?player=e2e-embed");
  const frame = page.frameLocator("iframe");
  await expect(frame.getByTestId("panel-0")).toBeVisible();
  const events = await page.evaluate(() => (window as unknown as { __events: string[] }).__events);
  expect(events).toContain("LR_READY");
  expect(events).toContain("LR_SESSION_STARTED");
  for (const f of page.frames()) expect(f.url()).not.toContain("lt_");
});

test("a dropped connection shows a banner, then recovers with a fresh single-use ticket", async ({ page }) => {
  // Proxy the game's WebSocket so the test can sever it like a network failure would.
  const sockets: { close: () => Promise<void> }[] = [];
  const tickets: string[] = [];
  await page.routeWebSocket(/\/socket\/websocket/, (ws) => {
    tickets.push(new URL(ws.url()).searchParams.get("ticket") ?? "");
    ws.connectToServer();
    sockets.push(ws);
  });
  await page.goto(launchUrl(`e2e-net-${Date.now()}`));
  await expect(panel(page, 0)).toBeVisible();
  await expect.poll(() => sockets.length).toBeGreaterThan(0);

  await sockets[sockets.length - 1]!.close();
  await expect(page.getByTestId("reconnecting")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("reconnecting")).toBeHidden({ timeout: 30_000 });
  // Each connection used a different ticket (tickets are single-use).
  expect(new Set(tickets).size).toBe(tickets.length);
  expect(tickets.length).toBeGreaterThanOrEqual(2);
  await expect(stage(page)).toHaveAttribute("data-phase", /BETTING_OPEN|BETTING_CLOSED|FLYING|CRASHED/);
});
