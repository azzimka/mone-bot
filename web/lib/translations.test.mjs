import test from "node:test";
import assert from "node:assert/strict";
import {
  russian,
  chartDayLabel,
  translate,
  normalizeLanguage,
  monthLabel,
  formatMoney,
  entryDescription,
} from "./translations.ts";
import { validateEntryAmount } from "./entry.ts";

test("only supported saved preferences are restored", () => {
  assert.equal(normalizeLanguage("ru"), "ru");
  for (const value of [null, "", "uz", "en", "RU"])
    assert.equal(normalizeLanguage(value), "uz");
});
test("Russian covers entry validation and parameterized messages", () => {
  for (const value of ["", "0", "-10", "1e3", "1.234", "10000000000000"]) {
    const { error } = validateEntryAmount(value);
    assert.ok(error);
    assert.ok(russian[error], error);
  }
  assert.equal(
    translate("ru", "{count} ta operatsiya", { count: 21 }),
    "Операций: 21",
  );
  assert.equal(
    translate("uz", "{count} ta operatsiya", { count: 2 }),
    "2 ta operatsiya",
  );
  assert.equal(
    translate("ru", "{name} operatsiyasini tahrirlash", { name: "Tushlik" }),
    "Редактировать операцию «Tushlik»",
  );
});
test("Russian uses local decimal separators and month names", () => {
  assert.equal(
    formatMoney("ru", "1234567.89").replace(/\s/g, " "),
    "1 234 567,89",
  );
  assert.match(monthLabel("ru", "2026-10"), /октябрь.*2026/);
  assert.equal(monthLabel("uz", "2026-10"), "Oktabr, 2026");
  assert.equal(chartDayLabel("uz", "2026-10", "18"), "18-oktabr");
  assert.equal(chartDayLabel("ru", "2026-10", "18"), "18 октября");
});
test("user notes stay untouched, while synthetic examples follow language", () => {
  assert.equal(entryDescription("ru", { description: "Tushlik" }), "Tushlik");
  assert.equal(
    entryDescription("ru", {
      description: "Tushlik",
      demoDescription: "Tushlik",
    }),
    "Обед",
  );
  assert.equal(
    entryDescription("ru", {
      description: "Mening izohim",
      demoDescription: "Tushlik",
    }),
    "Mening izohim",
  );
  assert.equal(
    translate("ru", "Unknown server message"),
    "Unknown server message",
  );
});
test("translations keep interpolation variables intact", () => {
  const variables = (text) =>
    [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
  for (const [key, value] of Object.entries(russian)) {
    assert.ok(value.trim(), key);
    assert.deepEqual(variables(key), variables(value), key);
  }
});
