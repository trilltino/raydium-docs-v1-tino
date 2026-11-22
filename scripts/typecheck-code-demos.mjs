#!/usr/bin/env node
// Type-check every TypeScript block on the CPMM and CLMM code-demo pages against the pinned SDK,
// and save the evidence.
//
// Each block is compiled as its own module with `strict`. A block may use names an earlier block
// on the page defined, such as `raydium` or `poolInfo`. For each such name the block does not
// define itself, the harness prepends a declaration typed from the SDK (see CONTEXT below), so the
// block is checked against the SDK's real signatures rather than `any`. The one exception is the
// Anchor client `program` on the CLMM page, which has no SDK type and is declared `any`.
//
// Setup, once, in an empty directory outside the repo:
//   npm install @raydium-io/raydium-sdk-v2@0.2.85-alpha typescript@5.6.3 @types/node@20.17.6 @types/bn.js@5.1.6
// Run from the repo root:
//   node scripts/typecheck-code-demos.mjs --deps <that directory>
//
// Writes public/tino-changes/evidence/code-demo-typecheck-<UTC date>/result.json: compiler and
// SDK versions, compiler options, and for every block its page line, SHA-256, the prepended
// names, and any diagnostics mapped back to page lines. Exits 1 if any block fails.

import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const depsArg = process.argv.indexOf("--deps");
if (depsArg < 0 || !process.argv[depsArg + 1]) {
  console.error("usage: node scripts/typecheck-code-demos.mjs --deps <dir with node_modules>");
  process.exit(2);
}
const DEPS = resolve(process.argv[depsArg + 1]);
const require = createRequire(join(DEPS, "package.json"));
const ts = require("typescript");
const sdkVersion = require("@raydium-io/raydium-sdk-v2/package.json").version;

const R = 'import("@raydium-io/raydium-sdk-v2").Raydium';
const PK = 'import("@solana/web3.js").PublicKey';
const SHARED = {
  raydium: `declare const raydium: ${R};`,
  connection: 'declare const connection: import("@solana/web3.js").Connection;',
  owner: 'declare const owner: import("@solana/web3.js").Keypair;',
  POOL_ID: "declare const POOL_ID: string;",
  BN: 'import BN from "bn.js";',
  Decimal: 'import Decimal from "decimal.js";',
  PublicKey: 'import { PublicKey } from "@solana/web3.js";',
  TxVersion: 'import { TxVersion } from "@raydium-io/raydium-sdk-v2";',
};
const CPMM = {
  ...SHARED,
  FeeOn: 'import { FeeOn } from "@raydium-io/raydium-sdk-v2";',
  CurveCalculator: 'import { CurveCalculator } from "@raydium-io/raydium-sdk-v2";',
  extInfo: `declare const extInfo: Awaited<ReturnType<${R}["cpmm"]["createPool"]>>["extInfo"];`,
  poolInfo: `declare const poolInfo: Awaited<ReturnType<${R}["cpmm"]["getPoolInfoFromRpc"]>>["poolInfo"];`,
  poolKeys: `declare const poolKeys: Awaited<ReturnType<${R}["cpmm"]["getPoolInfoFromRpc"]>>["poolKeys"];`,
  rpcData: `declare const rpcData: Awaited<ReturnType<${R}["cpmm"]["getPoolInfoFromRpc"]>>["rpcData"];`,
  poolStatePda: `declare const poolStatePda: ${PK};`,
};
const CLMM = {
  ...SHARED,
  PoolUtils: 'import { PoolUtils } from "@raydium-io/raydium-sdk-v2";',
  SystemProgram: 'import { SystemProgram } from "@solana/web3.js";',
  poolInfo: `declare const poolInfo: Awaited<ReturnType<${R}["clmm"]["getPoolInfoFromRpc"]>>["poolInfo"];`,
  poolKeys: `declare const poolKeys: Awaited<ReturnType<${R}["clmm"]["getPoolInfoFromRpc"]>>["poolKeys"];`,
  positionAccount: `declare const positionAccount: Awaited<ReturnType<${R}["clmm"]["getOwnerPositionInfo"]>>[number];`,
  positionNftMint: `declare const positionNftMint: ${PK};`,
  mintA: `declare const mintA: Awaited<ReturnType<${R}["token"]["getTokenInfo"]>>;`,
  mintB: `declare const mintB: Awaited<ReturnType<${R}["token"]["getTokenInfo"]>>;`,
  // Block "Create a pool" builds it as { ...picked, id: new PublicKey(picked.id), fundOwner: "", description: "" }.
  ammConfig: `declare const ammConfig: Omit<Awaited<ReturnType<${R}["api"]["getClmmConfigs"]>>[number], "id"> & { id: ${PK}; fundOwner: string; description: string };`,
  initialPrice: 'declare const initialPrice: import("decimal.js").default;',
  // Built for createCustomizablePool in the block before; the next block passes it to the V2 builder.
  customizablePoolParams: `declare const customizablePoolParams: Parameters<${R}["clmm"]["createCustomizablePool"]>[0];`,
  limitOrder: `declare const limitOrder: ${PK};`,
  // Anchor client for the close-position example: no SDK type exists, so it is untyped.
  program: "declare const program: any;",
  nftOwner: `declare const nftOwner: ${PK};`,
  positionNftAccount: `declare const positionNftAccount: ${PK};`,
  personalPosition: `declare const personalPosition: ${PK};`,
  positionNftTokenProgram: `declare const positionNftTokenProgram: ${PK};`,
  poolId: `declare const poolId: ${PK};`,
};
const PAGES = [  // [page, shared names, compiler-option overrides]
  ["docs/en/products/cpmm/code-demos.mdx", CPMM, {}],
  ["docs/en/products/cpmm/fees.mdx", CPMM, {}],
  ["docs/en/products/clmm/code-demos.mdx", CLMM, {}],
  ["docs/en/products/clmm/fees.mdx", CLMM, {}],
  // A plain-JavaScript `swap.mjs`: it has no non-null assertions, so it is checked without `strict`.
  ["docs/en/quick-start/swap-from-cli.mdx", {}, { strict: false }],
];
const OPTIONS = {
  strict: true,
  noEmit: true,
  target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.ESNext,
  moduleResolution: ts.ModuleResolutionKind.Bundler,
  esModuleInterop: true,
  skipLibCheck: true,
  types: ["node"],
};

function blocks(page) {
  const lines = readFileSync(join(REPO, page), "utf8").split(/\r?\n/);
  const found = [];
  for (let i = 0; i < lines.length; i++) {
    if (!/^```(ts|typescript)\b/.test(lines[i])) continue;
    const start = i + 2; // page line of the block's first code line (1-based)
    const body = [];
    for (i++; i < lines.length && !lines[i].startsWith("```"); i++) body.push(lines[i]);
    found.push({ start, text: body.join("\n") });
  }
  return found;
}

function declaredNames(text) {
  const names = new Set();
  const bind = (node) => {
    if (!node) return;
    if (ts.isIdentifier(node)) names.add(node.text);
    else if (ts.isObjectBindingPattern(node) || ts.isArrayBindingPattern(node))
      node.elements.forEach((e) => !ts.isOmittedExpression(e) && bind(e.name));
  };
  for (const s of ts.createSourceFile("b.ts", text, ts.ScriptTarget.ES2022, true).statements) {
    if (ts.isImportDeclaration(s) && s.importClause) {
      bind(s.importClause.name);
      const nb = s.importClause.namedBindings;
      if (nb && ts.isNamespaceImport(nb)) bind(nb.name);
      if (nb && ts.isNamedImports(nb)) nb.elements.forEach((e) => bind(e.name));
    } else if (ts.isVariableStatement(s)) s.declarationList.declarations.forEach((d) => bind(d.name));
    else if (s.name && (ts.isFunctionDeclaration(s) || ts.isClassDeclaration(s) || ts.isEnumDeclaration(s))) bind(s.name);
  }
  return names;
}

const work = join(DEPS, "typecheck-blocks");
rmSync(work, { recursive: true, force: true });
mkdirSync(work, { recursive: true });
const files = [];
for (const [page, context, overrides] of PAGES) {
  blocks(page).forEach((block, n) => {
    const declared = declaredNames(block.text);
    const prepended = Object.keys(context).filter((name) => !declared.has(name) && new RegExp(`\\b${name}\\b`).test(block.text));
    const preamble = prepended.map((name) => context[name]);
    const file = join(work, `${page.split("/").slice(-2).join("-").replace(".mdx", "")}-${n + 1}.ts`);
    writeFileSync(file, [...preamble, block.text, "export {};", ""].join("\n"));
    files.push({ page, block: n + 1, page_line: block.start, file, offset: preamble.length,
                 sha256: createHash("sha256").update(block.text).digest("hex"), prepended,
                 options: { ...OPTIONS, ...overrides } });
  });
}

const programs = new Map();  // one program per distinct set of compiler options
for (const f of files) {
  const key = JSON.stringify(f.options);
  if (!programs.has(key)) programs.set(key, files.filter((g) => JSON.stringify(g.options) === key));
}
const compiled = new Map();
for (const group of programs.values()) {
  const program = ts.createProgram(group.map((f) => f.file), group[0].options);
  for (const f of group) compiled.set(f.file, program);
}
const results = files.map(({ file, offset, options, ...entry }) => {
  const program = compiled.get(file);
  const source = program.getSourceFile(file);
  const diagnostics = [...program.getSyntacticDiagnostics(source), ...program.getSemanticDiagnostics(source)].map((d) => {
    const line = d.start === undefined ? null : source.getLineAndCharacterOfPosition(d.start).line - offset;
    return { page_line: line === null ? null : entry.page_line + line, code: d.code,
             message: ts.flattenDiagnosticMessageText(d.messageText, " ") };
  });
  return { ...entry, strict: options.strict, passed: diagnostics.length === 0, diagnostics };
});
rmSync(work, { recursive: true, force: true });

const stamp = new Date();
const out = join(REPO, "public", "tino-changes", "evidence", `code-demo-typecheck-${stamp.toISOString().slice(0, 10)}`);
mkdirSync(out, { recursive: true });
const summary = {
  generated_at: stamp.toISOString(),
  typescript: ts.version,
  sdk: `@raydium-io/raydium-sdk-v2@${sdkVersion}`,
  compiler_options: { strict: "true unless results[].strict is false", target: "ES2022", module: "ESNext", moduleResolution: "Bundler", esModuleInterop: true, skipLibCheck: true },
  untyped_names: ["program (CLMM close-position Anchor client)"],
  blocks: results.length,
  passed: results.filter((r) => r.passed).length,
  results,
};
writeFileSync(join(out, "result.json"), JSON.stringify(summary, null, 2) + "\n");
for (const r of results) {
  console.log(`${r.passed ? "PASS" : "FAIL"} ${r.page}:${r.page_line} (block ${r.block})`);
  for (const d of r.diagnostics) console.log(`     ${r.page}:${d.page_line} TS${d.code} ${d.message}`);
}
console.log(`${summary.passed}/${summary.blocks} blocks pass; wrote ${out}`);
process.exit(summary.passed === summary.blocks ? 0 : 1);
