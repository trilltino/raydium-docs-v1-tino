#!/usr/bin/env node
// Show which seed index the SDK's `createCustomizablePoolV2` picks, and save the evidence.
//
// The builder scans the pool PDAs for seed indexes 1 to 100 and uses the first free one. This
// script runs the real builder from the published SDK against a stubbed RPC that reports chosen
// indexes as taken, then decodes `seed_index` from the instruction it built. It covers no pools,
// a few pools, 99 pools, all 100 pools, and `forerunCreate`. No network is used; the mints and
// config are fixed placeholder keys, so the pool addresses are the same on every run.
//
// It also counts seed indexes in the mainnet sample in
// public/tino-changes/evidence/clmm-2026-11-22/pools.csv (the 2,000 highest-TVL CLMM pools).
//
// Setup, once, in an empty directory outside the repo:
//   npm install --ignore-scripts @raydium-io/raydium-sdk-v2@0.2.85-alpha
// Run from the repo root:
//   node scripts/check-clmm-seed-index.mjs --deps <that directory>
//
// Writes public/tino-changes/evidence/clmm-seed-index-<UTC date>/result.json.

import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const depsArg = process.argv.indexOf("--deps");
if (depsArg < 0 || !process.argv[depsArg + 1]) {
  console.error("usage: node scripts/check-clmm-seed-index.mjs --deps <dir with node_modules>");
  process.exit(2);
}
const DEPS = resolve(process.argv[depsArg + 1]);
const require = createRequire(join(DEPS, "package.json"));
const sdkVersion = require("@raydium-io/raydium-sdk-v2/package.json").version;
const { Raydium, TxVersion, CLMM_PROGRAM_ID, getPdaCustomizablePoolV2Id } = require("@raydium-io/raydium-sdk-v2");
const { PublicKey } = require("@solana/web3.js");
const { TOKEN_PROGRAM_ID } = require("@solana/spl-token");
const Decimal = require("decimal.js");

// The line that picks the index, read from the installed package's own source.
const sdkSourcePath = join(DEPS, "node_modules", "@raydium-io", "raydium-sdk-v2", "src", "raydium", "clmm", "clmm.ts");
const sdkSourceLines = readFileSync(sdkSourcePath, "utf8").split("\n");
const pickLine = sdkSourceLines.findIndex((line) => line.includes("const seedIndex = Math.max("));
if (pickLine < 0) throw new Error("seed-index selection line not found in the installed SDK source");

const key = (seed) => new PublicKey(Uint8Array.from({ length: 32 }, (_, i) => (seed * 31 + i * 7) % 256));
const programId = CLMM_PROGRAM_ID;
const ammConfigId = key(1);
const [mintA, mintB] = [key(2), key(3)].sort((a, b) => Buffer.compare(a.toBuffer(), b.toBuffer()));
const owner = key(4);
const token = (mint) => ({
  chainId: 101,
  address: mint.toBase58(),
  programId: TOKEN_PROGRAM_ID.toBase58(),
  logoURI: "",
  symbol: "T",
  name: "T",
  decimals: 6,
  tags: [],
  extensions: {},
});
const ammConfig = {
  id: ammConfigId,
  index: 0,
  protocolFeeRate: 120000,
  tradeFeeRate: 2500,
  tickSpacing: 60,
  fundFeeRate: 40000,
  fundOwner: "",
  description: "",
};
const pda = (index) => getPdaCustomizablePoolV2Id(programId, ammConfigId, mintA, mintB, index).publicKey.toBase58();
const discriminator = createHash("sha256").update("global:create_customizable_pool_v2").digest().subarray(0, 8);
// Instruction data: discriminator (8), sqrt_price_x64 u128 (16), collect_fee_on u8 (1), enable_dynamic_fee bool (1), seed_index u16.
const SEED_INDEX_OFFSET = 8 + 16 + 1 + 1;
const range = (from, to) => Array.from({ length: to - from + 1 }, (_, i) => from + i);

async function scenario(name, takenIndexes, forerunCreate, expected) {
  const taken = new Set(takenIndexes.map(pda));
  const rpc = { calls: 0, keys: 0 };
  const existing = { data: Buffer.alloc(0), executable: false, lamports: 1, owner: programId, rentEpoch: 0 };
  const connection = {
    rpcEndpoint: "http://stub.invalid",
    commitment: "confirmed",
    getMultipleAccountsInfo: async (keys) => {
      rpc.calls += 1;
      rpc.keys += keys.length;
      return keys.map((k) => (taken.has(k.toBase58()) ? existing : null));
    },
    getAccountInfo: async () => null,
    getLatestBlockhash: async () => ({ blockhash: PublicKey.default.toBase58(), lastValidBlockHeight: 1 }),
  };
  const raydium = await Raydium.load({
    connection,
    owner,
    cluster: "mainnet",
    disableLoadToken: true,
    disableFeatureCheck: true,
  });
  const { transaction, extInfo } = await raydium.clmm.createCustomizablePoolV2({
    programId,
    mint1: token(mintA),
    mint2: token(mintB),
    ammConfig,
    initialPrice: new Decimal(1),
    txVersion: TxVersion.LEGACY,
    forerunCreate,
  });
  const ix = transaction.instructions.find((i) => i.programId.equals(programId));
  if (!ix || !ix.data.subarray(0, 8).equals(discriminator)) throw new Error("no create_customizable_pool_v2 instruction");
  const seedIndex = ix.data.readUInt16LE(SEED_INDEX_OFFSET);
  const poolId = extInfo.address.poolId.toBase58();
  return {
    name,
    forerunCreate: !!forerunCreate,
    takenSeedIndexes: takenIndexes.length ? `${takenIndexes[0]}-${takenIndexes.at(-1)}` : "none",
    rpcCalls: rpc.calls,
    accountsQueried: rpc.keys,
    seedIndexInInstruction: seedIndex,
    poolId,
    poolIdMatchesPdaForThatIndex: poolId === pda(seedIndex),
    targetsExistingPool: taken.has(poolId),
    expected,
  };
}

function mainnetSample() {
  const file = join(REPO, "public", "tino-changes", "evidence", "clmm-2026-11-22", "pools.csv");
  const [header, ...rows] = readFileSync(file, "utf8").trim().split(/\r?\n/);
  const column = header.split(",").indexOf("seed_index");
  const bySeedIndex = {};
  for (const row of rows) {
    const value = Number(row.split(",")[column]);
    bySeedIndex[value] = (bySeedIndex[value] ?? 0) + 1;
  }
  const nonzero = Object.keys(bySeedIndex).map(Number).filter((n) => n > 0);
  return {
    source: "public/tino-changes/evidence/clmm-2026-11-22/pools.csv (2,000 highest-TVL CLMM pools listed by api-v3)",
    pools: rows.length,
    poolsWithNonzeroSeedIndex: nonzero.reduce((sum, n) => sum + bySeedIndex[n], 0),
    poolsBySeedIndex: bySeedIndex,
    highestSeedIndex: Math.max(0, ...nonzero),
  };
}

const scenarios = [
  await scenario("no seed-indexed pools", [], false, "index 1"),
  await scenario("indexes 1-3 taken", range(1, 3), false, "index 4"),
  await scenario("indexes 1-99 taken", range(1, 99), false, "index 100"),
  await scenario("indexes 1-100 taken", range(1, 100), false, "an error, or an index above 100 (the program accepts 1-65535)"),
  await scenario("forerunCreate with index 1 taken", [1], true, "a caller-chosen index; the builder takes none"),
];

const stamp = new Date();
const summary = {
  generated: stamp.toISOString(),
  sdk: `@raydium-io/raydium-sdk-v2@${sdkVersion}`,
  node: process.version,
  sdkSelectionLine: { file: "src/raydium/clmm/clmm.ts", line: pickLine + 1, text: sdkSourceLines[pickLine].trim() },
  program: "raydium-clmm create_customizable_pool_v2 requires only seed_index > 0 (require_gt!(seed_index, 0)) and inits pool_state at the seed_index PDA",
  method: "Real createCustomizablePoolV2 from the installed package; stubbed connection whose getMultipleAccountsInfo reports the listed indexes as existing accounts; seed_index decoded from the built instruction data.",
  scenarios,
  mainnetSample: mainnetSample(),
};

const out = join(REPO, "public", "tino-changes", "evidence", `clmm-seed-index-${stamp.toISOString().slice(0, 10)}`);
mkdirSync(out, { recursive: true });
writeFileSync(join(out, "result.json"), JSON.stringify(summary, null, 2) + "\n");

for (const s of scenarios) {
  console.log(
    `${s.name.padEnd(34)} seed_index=${String(s.seedIndexInInstruction).padStart(3)}  ` +
      `${s.targetsExistingPool ? "targets an existing pool" : "free"}  (rpc calls ${s.rpcCalls}, accounts ${s.accountsQueried})`,
  );
}
console.log(`SDK line ${summary.sdkSelectionLine.line}: ${summary.sdkSelectionLine.text}`);
console.log(`Wrote ${join(out, "result.json")}`);
