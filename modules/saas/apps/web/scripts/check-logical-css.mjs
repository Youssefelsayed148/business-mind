#!/usr/bin/env node
/**
 * Fails on physical left/right CSS (Phase 4B, docs/PHASE-4-PLAN.md 12.5).
 *
 * The dashboard must work in both text directions, so stylesheets use logical properties
 * (margin-inline-start, inset-inline-end, text-align: start). A line that really needs a
 * physical side (for example a chart that must not mirror) carries a comment starting with physical-ok and a reason.
 *
 * Usage: node scripts/check-logical-css.mjs [directory ...]   (default: app)
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PROPERTY =
  /(^|[;{\s])(left|right|float|clear|(margin|padding|scroll-margin|scroll-padding)-(left|right)|border-(left|right)(-(width|style|color))?|border-(top|bottom)-(left|right)-radius)\s*:/i;
const VALUE = /(text-align|float|clear)\s*:\s*(left|right)\b/i;
const ESCAPE = /physical-ok\s*:/i;

/** Pure: the 1-based line numbers in `css` that use a physical side without an escape. */
export function physicalCssLines(css) {
  const found = [];
  let inComment = false;
  css.split("\n").forEach((line, index) => {
    if (ESCAPE.test(line)) return;
    let code = line;
    if (inComment) {
      const end = code.indexOf("*/");
      if (end === -1) return;
      code = code.slice(end + 2);
      inComment = false;
    }
    code = code.replace(/\/\*.*?\*\//g, "");
    const open = code.indexOf("/*");
    if (open !== -1) {
      code = code.slice(0, open);
      inComment = true;
    }
    if (PROPERTY.test(code) || VALUE.test(code)) found.push(index + 1);
  });
  return found;
}

function cssFiles(directory) {
  const out = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) out.push(...cssFiles(full));
    else if (entry.name.endsWith(".css")) out.push(full);
  }
  return out;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const roots = process.argv.slice(2);
  const failures = [];
  for (const root of roots.length ? roots : ["app"]) {
    for (const file of cssFiles(root)) {
      for (const line of physicalCssLines(fs.readFileSync(file, "utf8"))) {
        failures.push(`${file}:${line}`);
      }
    }
  }
  if (failures.length) {
    console.error(
      "Physical left/right CSS found (use logical properties, or mark the line with a physical-ok comment):",
    );
    for (const failure of failures) console.error(`  ${failure}`);
    process.exit(1);
  }
  console.log("Logical CSS check: OK");
}
