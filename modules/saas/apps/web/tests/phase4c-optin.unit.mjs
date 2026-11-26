/* Phase 4C: helpers of the public opt-in page. */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import Module from "node:module";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const filename = fileURLToPath(new URL("../lib/opt-in.ts", import.meta.url));
const compiled = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;
const mod = new Module(filename);
mod.filename = filename;
mod.paths = Module._nodeModulePaths(path.dirname(filename));
mod._compile(compiled, filename);
const { cleanOptInPhone, safeChatUrl } = mod.exports;

test("phone numbers: typed separators are removed, anything else is refused", () => {
  assert.equal(cleanOptInPhone("+20 100 123-4567"), "+201001234567");
  assert.equal(cleanOptInPhone(" +1 (555) 123.4567 "), "+15551234567");
  assert.equal(cleanOptInPhone("01001234567"), null);
  assert.equal(cleanOptInPhone("+12345"), null);
  assert.equal(cleanOptInPhone("+" + "1".repeat(21)), null);
  assert.equal(cleanOptInPhone("+1555abc4567"), null);
  assert.equal(cleanOptInPhone(""), null);
});

test("only a https wa.me link is ever opened", () => {
  assert.equal(
    safeChatUrl("https://wa.me/201001234567?text=JOIN"),
    "https://wa.me/201001234567?text=JOIN",
  );
  for (const bad of [
    "http://wa.me/1",
    "https://evil.example/wa.me/1",
    "https://wa.me.evil.example/1",
    "javascript:alert(1)",
    "//wa.me/1",
    "",
    null,
    undefined,
    5,
  ]) {
    assert.equal(safeChatUrl(bad), null, String(bad));
  }
});
