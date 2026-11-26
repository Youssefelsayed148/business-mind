/* Phase 4C unit tests: the /accounts return target and the keyword parser. */
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

const { accountsReturnTarget, accountsLoginTarget } = load(
  "../lib/accounts-return.ts",
);
const { parseKeywords } = load("../lib/many-facebook/types.ts");

test("platform staff go to the staff Instagram accounts page, query kept", () => {
  assert.equal(
    accountsReturnTarget({
      isStaff: true,
      tenantIds: ["a", "b"],
      search: "?connected=true",
    }),
    "/platform/instagram/accounts?connected=true",
  );
});

test("staff wins even with exactly one organization", () => {
  assert.equal(
    accountsReturnTarget({ isStaff: true, tenantIds: ["a"], search: "" }),
    "/platform/instagram/accounts",
  );
});

test("one organization goes to its channels page with the whole query", () => {
  assert.equal(
    accountsReturnTarget({
      isStaff: false,
      tenantIds: ["t-1"],
      search: "?error=oauth_failed&reconnected=true",
    }),
    "/app/t-1/channels?error=oauth_failed&reconnected=true",
  );
});

test("the same organization listed twice still counts as one", () => {
  assert.equal(
    accountsReturnTarget({
      isStaff: false,
      tenantIds: ["t-1", "t-1"],
      search: "",
    }),
    "/app/t-1/channels",
  );
});

test("several or no organizations go to the organization list", () => {
  assert.equal(
    accountsReturnTarget({
      isStaff: false,
      tenantIds: ["a", "b"],
      search: "?connected=true",
    }),
    "/app?connected=true",
  );
  assert.equal(
    accountsReturnTarget({ isStaff: false, tenantIds: [], search: "" }),
    "/app",
  );
});

test("a search without a question mark, or a bare one, is normalised", () => {
  assert.equal(
    accountsReturnTarget({ isStaff: false, tenantIds: ["a"], search: "x=1" }),
    "/app/a/channels?x=1",
  );
  assert.equal(
    accountsReturnTarget({ isStaff: false, tenantIds: ["a"], search: "?" }),
    "/app/a/channels",
  );
});

test("an organization id is encoded into the path", () => {
  assert.equal(
    accountsReturnTarget({ isStaff: false, tenantIds: ["a/b"], search: "" }),
    "/app/a%2Fb/channels",
  );
});

test("signed out: sign in, then back to /accounts with its query", () => {
  assert.equal(
    accountsLoginTarget("?connected=true"),
    `/login?next=${encodeURIComponent("/accounts?connected=true")}`,
  );
  assert.equal(
    accountsLoginTarget(""),
    `/login?next=${encodeURIComponent("/accounts")}`,
  );
});

test("keywords: split on commas, trim, lower-case, drop empties", () => {
  assert.deepEqual(parseKeywords(" Promo, DISCOUNT ,, price "), [
    "promo",
    "discount",
    "price",
  ]);
  assert.deepEqual(parseKeywords(""), []);
  assert.deepEqual(parseKeywords(" , "), []);
});
