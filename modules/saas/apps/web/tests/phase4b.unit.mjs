/* Phase 4B unit tests: roles, menu, switcher target, old URLs, Many failures, CSS check. */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import Module from "node:module";
import { fileURLToPath } from "node:url";
import ts from "typescript";

function load(relative, stubs = {}) {
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
  mod.require = (id) => {
    if (id in stubs) return stubs[id];
    if (id.startsWith("./")) {
      return load(`../lib/${id.slice(2)}.ts`, stubs);
    }
    return realRequire(id);
  };
  mod._compile(compiled, filename);
  return mod.exports;
}

class ApiError extends Error {
  constructor(code, status) {
    super(code);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}
const role = load("../lib/org-role.ts");
const menu = load("../lib/menu.ts");
const sw = load("../lib/org-switch.ts");
const old = load("../lib/old-urls.ts");
const many = load("../lib/many.ts", {
  "./api": { api: async () => ({}), ApiError },
});
const { physicalCssLines } = await import("../scripts/check-logical-css.mjs");

test("stored roles map like the API and never escalate", () => {
  assert.equal(role.orgRoleFromStored("editor"), "agent");
  assert.equal(role.orgRoleFromStored("admin"), "admin");
  assert.equal(role.orgRoleFromStored("viewer"), "viewer");
  assert.equal(role.orgRoleFromStored(null), null);
});

test("summary roles: five roles, staff shown as admin, junk refused", () => {
  for (const r of ["owner", "admin", "manager", "agent", "viewer"]) {
    assert.equal(role.orgRoleFromSummary(r), r);
  }
  assert.equal(role.orgRoleFromSummary("platform_staff"), "admin");
  assert.equal(role.orgRoleFromSummary("root"), null);
  assert.equal(role.orgRoleFromSummary(undefined), null);
  assert.equal(role.orgRoleFromSummary("toString"), null);
});

test("role levels order owner > admin > manager > agent > viewer; null never passes", () => {
  assert.ok(role.orgRoleSatisfies("owner", "admin"));
  assert.ok(role.orgRoleSatisfies("manager", "agent"));
  assert.ok(!role.orgRoleSatisfies("manager", "admin"));
  assert.ok(!role.orgRoleSatisfies("agent", "manager"));
  assert.ok(!role.orgRoleSatisfies(null, "viewer"));
});

test("menu: staff entries only for staff; unshipped entries never shown", () => {
  const staff = menu.visibleMenu({ isStaff: true, role: null });
  assert.deepEqual(
    staff.map((x) => x.href),
    ["/platform/many"],
  );
  assert.deepEqual(
    menu.visibleMenu({ isStaff: false, role: "owner", tenantId: "t" }),
    [],
  );
  assert.ok(menu.MENU.every((e) => typeof e.shipped === "boolean"));
});

test("menu: client entries follow the role once they ship", () => {
  const shipped = [
    {
      group: "WhatsApp",
      label: "x",
      path: "/whatsapp/templates",
      minimumRole: "admin",
      shipped: true,
    },
  ];
  const original = [...menu.MENU];
  menu.MENU.splice(0, menu.MENU.length, ...shipped);
  try {
    const seen = (r) =>
      menu.visibleMenu({ isStaff: false, role: r, tenantId: "T" });
    assert.equal(seen("manager").length, 0);
    assert.equal(seen("admin")[0].href, "/app/T/whatsapp/templates");
    assert.equal(seen("owner").length, 1);
    assert.equal(menu.visibleMenu({ isStaff: false, role: "owner" }).length, 0);
  } finally {
    menu.MENU.splice(0, menu.MENU.length, ...original);
  }
});

const ID = "11111111-2222-3333-4444-555555555555";
test("switcher keeps the page, cuts before ids, falls back safely", () => {
  const base = {
    currentTenantId: "A",
    nextTenantId: "B",
    isStaff: false,
    archived: false,
  };
  assert.equal(
    sw.switchTarget({ ...base, pathname: "/app/A/settings/members" }),
    "/app/B/settings/members",
  );
  assert.equal(
    sw.switchTarget({ ...base, pathname: `/app/A/inbox/${ID}` }),
    "/app/B/inbox",
  );
  assert.equal(sw.switchTarget({ ...base, pathname: "/app/A" }), "/app/B");
  assert.equal(
    sw.switchTarget({ ...base, pathname: "/app", currentTenantId: undefined }),
    "/app/B",
  );
  assert.equal(
    sw.switchTarget({ ...base, pathname: "/platform/bots" }),
    "/app/B",
  );
  assert.equal(
    sw.switchTarget({ ...base, isStaff: true, pathname: "/app/A" }),
    "/app/B/bots",
  );
  assert.equal(
    sw.switchTarget({
      ...base,
      isStaff: true,
      archived: true,
      pathname: "/app/A/inbox",
    }),
    "/platform/clients/B",
  );
  // An organization id that merely starts like the current one is not "inside" it.
  assert.equal(
    sw.switchTarget({ ...base, pathname: "/app/AB/inbox" }),
    "/app/B",
  );
});

test("old URLs: every old Many page has a rule; moved targets are encoded", () => {
  const sources = old.OLD_URL_REDIRECTS.map((r) => r.source);
  for (const page of [
    "/overview",
    "/accounts",
    "/campaigns",
    "/conversations",
    "/facebook-campaigns",
    "/leads",
    "/logs",
    "/messages",
    "/whatsapp",
  ]) {
    assert.ok(sources.includes(page), page);
  }
  assert.equal(
    old.OLD_URL_REDIRECTS.find((r) => r.source === "/overview").destination,
    "/platform/many",
  );
  for (const r of old.OLD_URL_REDIRECTS) {
    assert.ok(
      r.destination.startsWith("/platform/") ||
        r.destination.startsWith("/moved?from=%2F"),
      r.destination,
    );
    assert.ok(
      !sources.includes(r.destination.split("?")[0]) ||
        r.destination.startsWith("/moved"),
    );
  }
  assert.ok(
    !sources.includes("/privacy") &&
      !sources.includes("/terms") &&
      !sources.includes("/login"),
  );
});

test("Many failures reduce to five kinds", () => {
  const k = many.manyFailureKind;
  assert.equal(k(new ApiError("X", 401)), "session");
  assert.equal(k(new ApiError("FORBIDDEN", 403)), "forbidden");
  assert.equal(k(new ApiError("NOT_FOUND", 404)), "not_available");
  assert.equal(k(new ApiError("MANY_UNAVAILABLE", 502)), "unavailable");
  assert.equal(k(new ApiError("X", 504)), "unavailable");
  assert.equal(k(new ApiError("X", 500)), "error");
  assert.equal(k(new Error("boom")), "error");
  assert.equal(k(null), "error");
  for (const text of Object.values(many.MANY_FAILURE_MESSAGE)) {
    assert.ok(!/\b\d{3}\b/.test(text), "no raw status code in user text");
  }
});

test("logical CSS check flags physical sides and honours the escape", () => {
  const bad = [
    ".a { margin-left: 1rem; }",
    ".a { padding-right: 1rem }",
    ".a { left: 0; }",
    ".a { text-align: right; }",
    ".a { float: left; }",
    ".a { border-top-left-radius: 4px; }",
    ".a { border-right: 1px solid red; }",
  ];
  for (const css of bad) assert.deepEqual(physicalCssLines(css), [1], css);
  const good = [
    ".a { margin-inline-start: 1rem; }",
    ".a { inset-inline-end: 0; text-align: start; }",
    ".a { border-start-start-radius: 4px; }",
    ".a { margin-left: 1rem; } /* physical-ok: chart axis */",
    "/* margin-left: 1rem */ .a { color: red; }",
    ".a { content: 'left'; }",
    ".overflow-left { color: red; }",
  ];
  for (const css of good) assert.deepEqual(physicalCssLines(css), [], css);
  assert.deepEqual(physicalCssLines("/*\nleft: 0;\n*/\n.a { right: 0 }"), [4]);
});

test("Many error bodies reduce to a plain message", () => {
  const m = many.manyMessage;
  assert.equal(
    m({ detail: "Template is not approved" }, 409),
    "Template is not approved",
  );
  assert.equal(
    m({ detail: { code: "opt_in_keyword_required" } }, 409),
    "opt in keyword required",
  );
  assert.equal(m({ detail: { message: "Nope", code: "x" } }, 409), "Nope");
  assert.equal(
    m({ detail: [{ msg: "field required" }, { msg: "too short" }] }, 422),
    "field required, too short",
  );
  assert.equal(
    m({ error: { code: "FORBIDDEN", message: "No access." } }, 403),
    "No access.",
  );
  assert.equal(
    m(null, 500),
    "The channel service had a problem. Try again later.",
  );
  assert.equal(m("<html>", 422), "Some fields need attention.");
  assert.ok(!/\b\d{3}\b/.test(m({}, 404)));
});

test("ManyError feeds the same failure kinds", () => {
  const E = many.ManyError;
  const k = many.manyFailureKind;
  assert.equal(k(new E(401, "x")), "session");
  assert.equal(k(new E(403, "x")), "forbidden");
  assert.equal(k(new E(404, "x")), "not_available");
  assert.equal(k(new E(502, "x", "MANY_UNAVAILABLE")), "unavailable");
  assert.equal(k(new E(409, "x")), "error");
});

test("Many proxy URLs: organization id encoded, leading slash dropped", () => {
  assert.equal(
    many.manyUrl({ kind: "staff" }, "/stats/overview"),
    "/api/v1/many/staff/stats/overview",
  );
  assert.equal(
    many.manyUrl({ kind: "org", tenantId: "a/b" }, "whatsapp/accounts?x=1"),
    "/api/v1/many/orgs/a%2Fb/whatsapp/accounts?x=1",
  );
});
