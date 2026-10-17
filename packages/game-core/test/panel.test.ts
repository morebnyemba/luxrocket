import { describe, expect, it } from "vitest";
import { initialPanel, panelReducer, type PanelEvent, type PanelState } from "../src/panel";

const run = (s: PanelState, ...events: PanelEvent[]) => events.reduce(panelReducer, s);
const p0 = () => initialPanel(0, 500n);

describe("panel state machine", () => {
  it("happy path: place, accept, launch, cash out, settle", () => {
    const s = run(
      p0(),
      { type: "PLACE", roundId: "r1", commandId: "c1" },
      { type: "BET_ACCEPTED", commandId: "c1", betId: "b1", stake: 500n },
      { type: "LAUNCHED", roundId: "r1" },
      { type: "CASHING_OUT", commandId: "c2" },
      { type: "CASHOUT_ACCEPTED", betId: "b1", cashout: 23_456, payout: 1172n },
      { type: "SETTLED", betId: "b1", kind: "CREDIT" },
    );
    expect(s).toMatchObject({ status: "CASHED_OUT", payout: 1172n, settled: true });
  });

  it("ignores results for a different command or bet", () => {
    const placing = run(p0(), { type: "PLACE", roundId: "r1", commandId: "c1" });
    expect(panelReducer(placing, { type: "BET_ACCEPTED", commandId: "other", betId: "x", stake: 1n })).toBe(placing);
  });

  it("a crash during cash-out request ends as lost", () => {
    const s = run(
      p0(),
      { type: "PLACE", roundId: "r1", commandId: "c1" },
      { type: "BET_ACCEPTED", commandId: "c1", betId: "b1", stake: 500n },
      { type: "LAUNCHED", roundId: "r1" },
      { type: "CASHING_OUT", commandId: "c2" },
      { type: "CASHOUT_REJECTED", betId: "b1", code: "ROUND_ENDED" },
    );
    expect(s.status).toBe("LOST");
  });

  it("uncertain debit shows refund pending, then refunded", () => {
    const s = run(
      p0(),
      { type: "PLACE", roundId: "r1", commandId: "c1" },
      { type: "BET_REJECTED", commandId: "c1", code: "UNCERTAIN", refund: "PENDING" },
    );
    expect(s.status).toBe("REFUND_PENDING");
  });

  it("queued bet survives until the next round opens", () => {
    let s = run(p0(), { type: "QUEUE" });
    s = panelReducer(s, { type: "ROUND_OPEN", roundId: "r2" });
    expect(s.status).toBe("QUEUED");
    expect(panelReducer(s, { type: "PLACE", roundId: "r2", commandId: "c" }).status).toBe("PLACING");
  });

  it("finished bets reset on the next round; live bets do not", () => {
    const lost = run(
      p0(),
      { type: "PLACE", roundId: "r1", commandId: "c1" },
      { type: "BET_ACCEPTED", commandId: "c1", betId: "b1", stake: 500n },
      { type: "LAUNCHED", roundId: "r1" },
      { type: "CRASHED", roundId: "r1" },
    );
    expect(lost.status).toBe("LOST");
    expect(panelReducer(lost, { type: "ROUND_OPEN", roundId: "r2" }).status).toBe("IDLE");
  });

  it("stake edits are blocked while a bet is live", () => {
    const placed = run(p0(), { type: "PLACE", roundId: "r1", commandId: "c1" });
    expect(panelReducer(placed, { type: "EDIT", stake: 9n }).stake).toBe(500n);
  });

  it("two panels evolve independently under any interleaving", () => {
    const events: [number, PanelEvent][] = [
      [0, { type: "PLACE", roundId: "r1", commandId: "a" }],
      [1, { type: "PLACE", roundId: "r1", commandId: "b" }],
      [1, { type: "BET_ACCEPTED", commandId: "b", betId: "B", stake: 300n }],
      [0, { type: "BET_ACCEPTED", commandId: "a", betId: "A", stake: 500n }],
      [0, { type: "LAUNCHED", roundId: "r1" }],
      [1, { type: "LAUNCHED", roundId: "r1" }],
      [0, { type: "CASHOUT_ACCEPTED", betId: "A", cashout: 20_000, payout: 1000n }],
      [1, { type: "CRASHED", roundId: "r1" }],
      [0, { type: "CRASHED", roundId: "r1" }],
    ];
    for (let seed = 0; seed < 50; seed++) {
      const shuffled = [...events].sort(() => (Math.sin(seed * 9301 + events.length) > 0 ? 1 : -1));
      const ordered = shuffled.sort((x, y) => events.indexOf(x) - events.indexOf(y));
      let panels = [initialPanel(0, 500n), initialPanel(1, 300n)];
      for (const [i, e] of ordered) panels = panels.map((p) => (p.index === i ? panelReducer(p, e) : p));
      expect(panels[0]!.status).toBe("CASHED_OUT");
      expect(panels[1]!.status).toBe("LOST");
    }
  });
});
