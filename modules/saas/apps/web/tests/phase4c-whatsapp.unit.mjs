/* Phase 4C unit tests: the pure WhatsApp helpers in lib/whatsapp-types.ts. */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import Module from "node:module";
import { fileURLToPath } from "node:url";
import ts from "typescript";

function load(relative) {
  const filename = fileURLToPath(new URL(relative, import.meta.url));
  const compiled = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const mod = new Module(filename);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  mod._compile(compiled, filename);
  return mod.exports;
}

const wa = load("../lib/whatsapp-types.ts");

test("placeholders: unique, ascending, spaces allowed", () => {
  assert.deepEqual(
    wa.placeholderIndexes("Hi {{2}} and {{ 1 }} and {{2}}"),
    [1, 2],
  );
  assert.deepEqual(wa.placeholderIndexes("no variables"), []);
  assert.deepEqual(wa.placeholderIndexes("{{a}} {{}}"), []);
});

test("preview fills examples and keeps unfilled placeholders", () => {
  assert.equal(
    wa.renderPreview("Hello {{1}}, code {{2}}", { 1: "Sam" }),
    "Hello Sam, code {{2}}",
  );
});

test("template indexes read every component text", () => {
  const t = {
    components: [
      { type: "HEADER", text: "{{2}}" },
      { type: "BODY", text: "{{1}}" },
      { type: "FOOTER" },
    ],
  };
  assert.deepEqual(wa.templateIndexes(t), [1, 2]);
  assert.deepEqual(wa.templateIndexes(undefined), []);
});

test("template names are normalised for Meta", () => {
  assert.equal(
    wa.normalizeTemplateName("Seasonal Offer-1"),
    "seasonal_offer_1",
  );
});

test("keywords: trimmed, blanks dropped", () => {
  assert.deepEqual(wa.parseKeywords(" START, YES ,, "), ["START", "YES"]);
  assert.deepEqual(wa.parseKeywords(""), []);
});

test("example values come back by placeholder number (flat and nested)", () => {
  const flat = { type: "BODY", example: { body_text: ["Sam", "42"] } };
  const nested = { type: "BODY", example: { body_text: [["Sam", "42"]] } };
  assert.deepEqual(wa.exampleValues(flat, [1, 2]), { 1: "Sam", 2: "42" });
  assert.deepEqual(wa.exampleValues(nested, [1, 2]), { 1: "Sam", 2: "42" });
  assert.deepEqual(wa.exampleValues({ type: "BODY" }, [1]), {});
  assert.deepEqual(wa.exampleValues(undefined, [1]), {});
});

test("health freshness thresholds", () => {
  assert.equal(wa.healthFreshness(null), "Never checked");
  assert.equal(wa.healthFreshness(299), "Fresh");
  assert.equal(wa.healthFreshness(300), "A few minutes old");
  assert.equal(wa.healthFreshness(1800), "Stale");
});

test("the mapping is complete only when every number has a value or fallback", () => {
  assert.equal(wa.mappingComplete([], {}), true);
  assert.equal(wa.mappingComplete([1], {}), false);
  assert.equal(
    wa.mappingComplete([1], { 1: { source: "literal", value: "  " } }),
    false,
  );
  assert.equal(
    wa.mappingComplete([1], { 1: { source: "literal", value: "x" } }),
    true,
  );
  assert.equal(
    wa.mappingComplete([1], { 1: { source: "contact.display_name" } }),
    false,
  );
  assert.equal(
    wa.mappingComplete([1], {
      1: { source: "contact.display_name", fallback: "friend" },
    }),
    true,
  );
});

test("campaign final states stop the live refresh", () => {
  for (const s of ["completed", "cancelled", "failed"])
    assert.equal(wa.campaignIsFinal(s), true);
  for (const s of ["draft", "scheduled", "running", "paused"])
    assert.equal(wa.campaignIsFinal(s), false);
});

test("reason and status labels", () => {
  assert.equal(wa.reasonLabel("opted_out"), "Opted out");
  assert.equal(wa.reasonLabel("some_new_reason"), "Some New Reason");
  assert.equal(wa.statusLabel(null), "Unknown");
  assert.equal(wa.statusLabel("opted_in"), "Opted In");
  assert.equal(wa.statusTone("opted_out"), "danger");
  assert.equal(wa.statusTone("whatever"), "neutral");
  assert.equal(wa.formatDate(null), "Not available");
});
