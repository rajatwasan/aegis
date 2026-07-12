import { describe, expect, it } from "vitest";
import {
  countdown,
  formatAmount,
  operationName,
  relativeTime,
  truncateMiddle,
} from "./format";

describe("truncateMiddle", () => {
  it("truncates long hex values", () => {
    expect(truncateMiddle("0x1234567890abcdef1234567890abcdef12345678")).toBe(
      "0x1234...5678",
    );
  });
  it("leaves short values alone", () => {
    expect(truncateMiddle("0xabc")).toBe("0xabc");
  });
});

describe("formatAmount", () => {
  it("groups thousands", () => {
    expect(formatAmount(1234567)).toBe("1,234,567");
  });
});

describe("relativeTime", () => {
  const now = Date.parse("2026-07-12T12:00:00Z");
  it("renders seconds, minutes, hours", () => {
    expect(relativeTime("2026-07-12T11:59:30Z", now)).toBe("30s ago");
    expect(relativeTime("2026-07-12T11:30:00Z", now)).toBe("30m ago");
    expect(relativeTime("2026-07-12T09:00:00Z", now)).toBe("3h ago");
  });
  it("clamps the future to just now", () => {
    expect(relativeTime("2026-07-12T12:00:30Z", now)).toBe("just now");
  });
});

describe("countdown", () => {
  const now = Date.parse("2026-07-12T12:00:00Z");
  it("renders m:ss under an hour", () => {
    expect(countdown(now / 1000 + 90, now)).toBe("1:30");
  });
  it("renders h:mm:ss above an hour", () => {
    expect(countdown(now / 1000 + 3661, now)).toBe("1:01:01");
  });
  it("reports expiry", () => {
    expect(countdown(now / 1000 - 1, now)).toBe("expired");
  });
});

describe("operationName", () => {
  it("maps the on-chain discriminators", () => {
    expect(operationName(1)).toBe("transfer");
    expect(operationName(4)).toBe("freeze");
    expect(operationName(9)).toBe("op 9");
  });
});
