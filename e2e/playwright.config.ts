import { defineConfig } from "@playwright/test";

// Runs against a live local stack (Postgres, Django API + workers, Phoenix, game dev server).
// See e2e/README.md. Rounds use the real multiplier curve, so tests allow long flights.
export default defineConfig({
  testDir: "./tests",
  timeout: 300_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    viewport: { width: 420, height: 860 },
    launchOptions: { args: ["--use-gl=swiftshader", "--enable-unsafe-swiftshader"] },
    trace: "retain-on-failure",
  },
});
