/* Phase 4E: pure helpers of the identity screens. */
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
  const realRequire = mod.require.bind(mod);
  mod.require = (id) =>
    id.startsWith("./") ? load(`../lib/${id.slice(2)}.ts`) : realRequire(id);
  mod._compile(compiled, filename);
  return mod.exports;
}
const h = load("../lib/identity.ts");

test("who may invite which role", () => {
  assert.deepEqual(h.invitableRoles("owner"), [
    "admin",
    "manager",
    "agent",
    "viewer",
  ]);
  assert.deepEqual(h.invitableRoles("admin"), ["manager", "agent", "viewer"]);
  for (const r of ["manager", "agent", "viewer", null])
    assert.deepEqual(h.invitableRoles(r), []);
  assert.ok(!h.invitableRoles("admin").includes("owner"));
  assert.ok(!h.invitableRoles("admin").includes("admin"));
});

test("role labels", () => {
  assert.equal(h.roleLabel("manager"), "Manager");
  assert.equal(h.roleLabel("toString"), "toString");
  assert.equal(h.roleLabel("platform_staff"), "platform_staff");
});

test("password problems", () => {
  assert.match(h.passwordProblem("short", "short"), /at least 8/);
  assert.match(h.passwordProblem("longenough1", "different1"), /do not match/);
  assert.equal(h.passwordProblem("longenough1", "longenough1"), null);
});

test("codes: spaces removed, length checked", () => {
  assert.equal(h.cleanCode(" 123 456 "), "123456");
  assert.equal(h.cleanCode("12345"), null);
  assert.equal(h.cleanCode("a".repeat(33)), null);
  assert.equal(h.cleanCode("abcd-efgh-ijkl"), "abcd-efgh-ijkl");
});

test("device labels", () => {
  assert.equal(h.deviceLabel(null), "Unknown device");
  assert.equal(
    h.deviceLabel(
      "Mozilla/5.0 (Windows NT 10.0) AppleWebKit Chrome/120 Safari/537",
    ),
    "Chrome on Windows",
  );
  assert.equal(
    h.deviceLabel("Mozilla/5.0 (iPhone; CPU iPhone OS 17) Safari/604"),
    "Safari on iOS",
  );
  assert.equal(h.deviceLabel("curl/8"), "Browser");
});

test("an invitation link is shown only as a same-origin path", () => {
  assert.equal(
    h.inviteUrl("/accept-invite?token=abc", "https://app.example"),
    "https://app.example/accept-invite?token=abc",
  );
  assert.equal(h.inviteUrl(null, "https://app.example"), null);
  assert.equal(h.inviteUrl("//evil.example/x", "https://app.example"), null);
  assert.equal(
    h.inviteUrl("https://evil.example/x", "https://app.example"),
    null,
  );
});
