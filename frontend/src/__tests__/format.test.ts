import { describe, expect, it } from "vitest";

import { formatDateTime, formatNullable, formatNumber } from "../lib/format";

describe("formatNullable", () => {
  it("returns a placeholder for nullish values", () => {
    expect(formatNullable(null)).toBe("—");
    expect(formatNullable(undefined)).toBe("—");
    expect(formatNullable("")).toBe("—");
  });
});

describe("formatDateTime", () => {
  it("formats ISO strings into local readable text", () => {
    expect(formatDateTime("2026-05-26T12:34:56")).toContain("2026");
  });
});

describe("formatNumber", () => {
  it("formats numbers with locale separators", () => {
    expect(formatNumber(12000)).toMatch(/12,?000/);
  });
});
