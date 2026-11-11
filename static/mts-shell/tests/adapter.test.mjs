import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import * as adapter from "../adapter.mjs";
import { cabinetTarget } from "../../cabinet-links.mjs";
const { SEED_AGENTS, QA_SEED, STORAGE_KEY, escapeHTML, safeSource } = adapter;
const here = dirname(fileURLToPath(import.meta.url));
const read = (...parts) => readFileSync(join(here, "..", ...parts), "utf8");

test("P2-02: public demo data is a fixed sample, not an editable repository", () => {
  assert.equal(SEED_AGENTS[0].id, "mts-support");
  assert.equal(SEED_AGENTS[0].qa, QA_SEED);
  // The mock cabinet's repository, session cache and canned-answer fallback are gone.
  for (const removed of ["createRepository", "cleanAgent", "SEED_SESSIONS", "demoAnswer"])
    assert.equal(adapter[removed], undefined, removed + " must not come back");
});

test("P2-02: concept page never touches browser storage", () => {
  for (const file of ["adapter.mjs", "app.mjs", "local-voice.mjs"]) {
    const text = read(file).replace(/^\s*\/\/.*$/gm, ""); // comments may mention the key
    assert.doesNotMatch(text, /localStorage|sessionStorage|\.setItem\(|\.removeItem\(/, file);
  }
});

test("P2-02: old draft key stays readable by the real cabinet importer", () => {
  assert.equal(STORAGE_KEY, "callwise-mts-shell-v1");
  const product = readFileSync(join(here, "..", "..", "product.js"), "utf8");
  assert.ok(product.includes("'" + STORAGE_KEY + "'"), "product.js must read the same key");
  assert.doesNotMatch(product, /localStorage\.(setItem|removeItem|clear)/);
});

test("P2-02: concept markup has no second cabinet", () => {
  const html = read("index.html");
  for (const gone of ['id="cabinet"', "cabinetContent", "cabinet-shell", "data-action=\"profile\"", "agentCount"])
    assert.ok(!html.includes(gone), gone + " must be removed from the concept page");
  const app = read("app.mjs");
  for (const gone of ["renderWizard", "startWizard", "agentsPage", "detailPage", "qaModal", "api.saveAgent", "in-cabinet"])
    assert.ok(!app.includes(gone), gone + " must be removed from app.mjs");
});

test("P2-02: old #cabinet bookmarks still open the real workspace", () => {
  const routes = {
    "#cabinet/agents": "/#assistant",
    "#cabinet/agent/any-id": "/#assistant",
    "#cabinet/overview": "/#overview",
    "#cabinet/knowledge": "/#knowledge",
    "#cabinet/history": "/#applications",
    "#cabinet/settings": "/#channels",
    "#cabinet": "/#overview",
  };
  for (const [hash, target] of Object.entries(routes)) assert.equal(cabinetTarget(hash), target, hash);
  assert.equal(cabinetTarget("#home/demo"), null);
});

test("unsafe links and markup are neutralised", () => {
  assert.equal(safeSource("javascript:alert(1)"), "");
  assert.equal(safeSource("https://evil.example"), "");
  assert.equal(safeSource("https://www.mts.by/help/"), "https://www.mts.by/help/");
  assert.equal(escapeHTML('<img onerror="alert(1)">'), "&lt;img onerror=&quot;alert(1)&quot;&gt;");
});
