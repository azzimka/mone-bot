import test from "node:test";
import assert from "node:assert/strict";
import {
  formatEntryAmount,
  validateEntryAmount,
  previousDay,
} from "./entry.ts";

test("UZS thousands and decimal comma retain exact cents", () => {
  assert.deepEqual(validateEntryAmount("25 000,50"), {
    value: "25000.50",
    error: "",
  });
  assert.equal(
    validateEntryAmount("1\u202f234\u00a0567.89").value,
    "1234567.89",
  );
  assert.equal(formatEntryAmount("25000,50"), "25 000,50");
});
test("editing preserves a decimal separator until typing is finished", () => {
  assert.equal(formatEntryAmount("25000,"), "25 000,");
  assert.equal(formatEntryAmount("25000.5"), "25 000.5");
  assert.ok(validateEntryAmount("25 000,").error);
});
test("values are never silently rounded, truncated or multiplied", () => {
  for (const value of [
    "1,000",
    "1.234",
    "1,234.56",
    "25k",
    "1e5",
    "-100",
    "NaN",
    "Infinity",
    "12+3",
  ]) {
    assert.ok(validateEntryAmount(value).error, value);
  }
  assert.equal(formatEntryAmount("25k"), "25k");
});
test("database bounds and sub-unit amounts remain exact", () => {
  assert.equal(
    validateEntryAmount("9 999 999 999 999,99").value,
    "9999999999999.99",
  );
  assert.ok(validateEntryAmount("10000000000000").error);
  assert.equal(validateEntryAmount("0,01").value, "0.01");
  assert.equal(validateEntryAmount("00012.50").value, "12.50");
  for (const value of ["", "0", "000", "0.00"])
    assert.ok(validateEntryAmount(value).error);
});
test("yesterday handles month, year and leap-day boundaries", () => {
  assert.equal(previousDay("2026-01-01"), "2025-12-31");
  assert.equal(previousDay("2024-03-01"), "2024-02-29");
  assert.equal(previousDay("2026-03-01"), "2026-02-28");
});
