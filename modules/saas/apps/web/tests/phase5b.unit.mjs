/* Phase 5B unit tests: the words and paging rules of the people-across-channels view. */
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

const links = load("../lib/customer-links.ts");

test("every platform and state has plain words, and unknown values pass through", () => {
  assert.equal(links.platformLabel("whatsapp"), "WhatsApp");
  assert.equal(links.platformLabel("instagram"), "Instagram");
  assert.equal(links.platformLabel("facebook"), "Facebook");
  assert.equal(links.platformLabel("telegram"), "telegram");
  for (const state of ["linked", "many_only", "saas_only", "conflict"]) {
    assert.ok(links.stateLabel(state).length > 0);
    assert.ok(links.stateHelp(state).length > 0);
  }
  assert.equal(links.stateLabel("something_new"), "something_new");
  assert.equal(links.stateHelp("something_new"), "");
});

test("tones: linked is good, conflict needs attention, the rest are neutral", () => {
  assert.equal(links.stateTone("linked"), "success");
  assert.equal(links.stateTone("conflict"), "warning");
  assert.equal(links.stateTone("many_only"), "neutral");
  assert.equal(links.stateTone("saas_only"), "neutral");
});

test("the name is the contact's, else Many's username, else a plain fallback", () => {
  assert.equal(
    links.personName({ contact_name: "Dana", display_name: "dana_wa" }),
    "Dana",
  );
  assert.equal(
    links.personName({ contact_name: null, display_name: " عميل " }),
    "عميل",
  );
  assert.equal(
    links.personName({ contact_name: "  ", display_name: null }),
    "Unnamed",
  );
});

test("paging offsets stop at both ends", () => {
  assert.equal(links.nextOffset(0, 120), 50);
  assert.equal(links.nextOffset(100, 120), null);
  assert.equal(links.nextOffset(0, 50), null);
  assert.equal(links.previousOffset(0), null);
  assert.equal(links.previousOffset(50), 0);
  assert.equal(links.previousOffset(20), 0);
  assert.equal(links.previousOffset(100), 50);
});
