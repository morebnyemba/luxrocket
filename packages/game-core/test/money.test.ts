import { describe, expect, it } from "vitest";
import { ServerClock, formatMoney, parseMoney, toDecimalString } from "../src/index";

describe("money", () => {
  it("formats and parses minor units exactly", () => {
    expect(formatMoney(123456789n, 2, "USD")).toBe("1,234,567.89 USD");
    expect(formatMoney("5", 2, "USD")).toBe("0.05 USD");
    expect(parseMoney("12.5", 2)).toBe(1250n);
    expect(parseMoney("0.07", 2)).toBe(7n);
    expect(parseMoney("1.234", 2)).toBeNull();
    expect(parseMoney("abc", 2)).toBeNull();
    expect(toDecimalString(1250n, 2)).toBe("12.50");
  });
});

describe("server clock", () => {
  it("uses the median offset of ping samples", () => {
    let t = 1_000;
    const clock = new ServerClock(() => t);
    clock.sample(1_000, 1_100, 5_050); // offset 4000
    clock.sample(2_000, 2_400, 6_200); // offset 4000
    clock.sample(3_000, 3_020, 9_999); // outlier
    expect(clock.offset).toBe(4_000);
    t = 10_000;
    expect(clock.now()).toBe(14_000);
  });
});
