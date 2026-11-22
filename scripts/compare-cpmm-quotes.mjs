#!/usr/bin/env node
// Compare the SDK's CPMM swap quotes with the program's swap math, and save the evidence.
//
// The program side is a BigInt port of raydium-cp-swap at 3d69122: curve/calculator.rs
// (swap_base_input, swap_base_output), curve/fees.rs, curve/constant_product.rs, utils/math.rs
// (checked_ceil_div), and states/pool.rs (is_creator_fee_on_input, adjust_creator_fee_rate).
// The SDK side is the published package's CurveCalculator, fed two ways:
//   documented: the creator-fee side and rate the CPMM code demos compute;
//   computeSwapAmount: the side (`BothToken || OnlyTokenB`) and raw tier rate that
//                      raydium.cpmm.computeSwapAmount passes.
//
// Offline cases: every tier in public/tino-changes/evidence/cpmm-2026-11-21/amm-configs.csv, each
// creator-fee mode, the fee enabled and disabled, both directions, 40 cases each, for both swap
// types. Reserves (6–15 digits) and amounts (0.01%–10% of a reserve) come from a 64-bit LCG
// seeded with 42.
//
// With --rpc-url, it also quotes two live pools read-only through the SDK: the highest-TVL pool in
// public/tino-changes/evidence/cpmm-2026-11-21/pool-lp-supply.csv with the creator fee enabled and
// the highest-TVL one with it disabled, swapping 0.1% of the token A reserve for token B.
//
// Setup, once, in an empty directory outside the repo:
//   npm install @raydium-io/raydium-sdk-v2@0.2.85-alpha
// Run from the repo root:
//   node scripts/compare-cpmm-quotes.mjs --deps <that directory> [--rpc-url <url> --rpc-token-env NAME]
// The token is sent as `x-token` and never written to the evidence.
//
// Writes public/tino-changes/evidence/cpmm-quotes-<UTC date>/result.json.

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const arg = (name) => { const i = process.argv.indexOf(name); return i < 0 ? undefined : process.argv[i + 1]; };
if (!arg("--deps")) {
  console.error("usage: node scripts/compare-cpmm-quotes.mjs --deps <dir with node_modules> [--rpc-url <url> --rpc-token-env NAME]");
  process.exit(2);
}
const require = createRequire(join(resolve(arg("--deps")), "package.json"));
const sdk = require("@raydium-io/raydium-sdk-v2");
const BN = require("bn.js");
const { CurveCalculator, FeeOn } = sdk;

// ---- Program math (u128 semantics in BigInt) ----
const D = 1_000_000n;
const ceilDiv = (a, num, den) => (a * num + den - 1n) / den;          // fees.rs ceil_div
const floorDiv = (a, num, den) => (a * num) / den;                     // fees.rs floor_div
const tradingFee = (a, rate) => ceilDiv(a, rate, D);
const creatorFeeOf = (a, rate) => ceilDiv(a, rate, D);
const splitCreatorFee = (total, trade, creator) => floorDiv(total, creator, trade + creator);
const preFee = (post, rate) => (rate === 0n ? post : (post * D + (D - rate) - 1n) / (D - rate));
const checkedCeilDiv = (a, b) => (a % b === 0n ? a / b : a / b + 1n);  // utils/math.rs

function programBaseInput(amount, inV, outV, trade, creator, protocol, fund, onInput) {
  let creatorFee = 0n, tradeFee, less;
  if (onInput) {
    const total = tradingFee(amount, trade + creator);
    creatorFee = splitCreatorFee(total, trade, creator);
    tradeFee = total - creatorFee;
    less = amount - total;
  } else {
    tradeFee = tradingFee(amount, trade);
    less = amount - tradeFee;
  }
  if (less < 0n) return null;
  const swapped = (less * outV) / (inV + less);
  let output = swapped;
  if (!onInput) { creatorFee = creatorFeeOf(swapped, creator); output = swapped - creatorFee; }
  if (output < 0n) return null;
  return { inputAmount: amount, outputAmount: output, tradeFee, creatorFee,
           protocolFee: floorDiv(tradeFee, protocol, D), fundFee: floorDiv(tradeFee, fund, D) };
}

function programBaseOutput(amount, inV, outV, trade, creator, protocol, fund, onInput) {
  let creatorFee = 0n, actualOut = amount;
  if (!onInput) { actualOut = preFee(amount, creator); creatorFee = actualOut - amount; }
  if (actualOut >= outV) return null;
  const swapped = checkedCeilDiv(inV * actualOut, outV - actualOut);
  let input, tradeFee;
  if (onInput) {
    input = preFee(swapped, trade + creator);
    const total = input - swapped;
    creatorFee = splitCreatorFee(total, trade, creator);
    tradeFee = total - creatorFee;
  } else {
    input = preFee(swapped, trade);
    tradeFee = input - swapped;
  }
  return { inputAmount: input, outputAmount: amount, tradeFee, creatorFee,
           protocolFee: floorDiv(tradeFee, protocol, D), fundFee: floorDiv(tradeFee, fund, D) };
}

// states/pool.rs: BothToken always; OnlyToken0 when token0 (mint A) is the input; OnlyToken1 when token1 is.
const programOnInput = (feeOn, baseIn) =>
  feeOn === FeeOn.BothToken || (feeOn === FeeOn.OnlyTokenA && baseIn) || (feeOn === FeeOn.OnlyTokenB && !baseIn);
// The code demos' expression, written exactly as on the page.
const documentedOnInput = (feeOn, baseIn) =>
  feeOn === FeeOn.BothToken || (feeOn === FeeOn.OnlyTokenA && baseIn) || (feeOn === FeeOn.OnlyTokenB && !baseIn);
const computeSwapAmountOnInput = (feeOn) => feeOn === FeeOn.BothToken || feeOn === FeeOn.OnlyTokenB;

const FIELDS = ["inputAmount", "outputAmount", "tradeFee", "creatorFee", "protocolFee", "fundFee"];
const big = (bn) => BigInt(bn.toString());
const sdkQuote = (baseInput, amount, inV, outV, cfg, creatorRate, onInput) => {
  const fn = baseInput ? CurveCalculator.swapBaseInput : CurveCalculator.swapBaseOutput;
  const r = fn(new BN(amount.toString()), new BN(inV.toString()), new BN(outV.toString()), new BN(cfg.trade.toString()),
               new BN(creatorRate.toString()), new BN(cfg.protocol.toString()), new BN(cfg.fund.toString()), onInput);
  return Object.fromEntries(FIELDS.map((f) => [f, big(r[f])]));
};

// ---- Seeded generator ----
let state = 42n;
const next = () => (state = (state * 6364136223846793005n + 1442695040888963407n) & ((1n << 64n) - 1n)) >> 11n;
const below = (n) => next() % n;
const reserve = () => { const d = 6n + below(10n); return 10n ** (d - 1n) + below(9n * 10n ** (d - 1n)); }; // 6–15 digits
const share = (v) => { const a = (v * (100n + below(99_901n))) / 1_000_000n; return a > 0n ? a : 1n; };  // 0.01%–10% of v

// ---- Offline comparison ----
const tiers = readFileSync(join(REPO, "public/tino-changes/evidence/cpmm-2026-11-21/amm-configs.csv"), "utf8")
  .trim().split(/\r?\n/).slice(1).map((line) => line.split(","))
  .map((c) => ({ index: Number(c[0]), trade: BigInt(c[4]), protocol: BigInt(c[5]), fund: BigInt(c[6]), creator: BigInt(c[10]) }));
const MODES = [["BothToken", FeeOn.BothToken], ["OnlyTokenA", FeeOn.OnlyTokenA], ["OnlyTokenB", FeeOn.OnlyTokenB]];
const CASES = 40;
const empty = () => ({ cases: 0, quote_equal: 0, all_fields_equal: 0, sdk_lower: 0, sdk_higher: 0, sdk_fee_one_unit_higher_when_lower: 0, examples: [] });
const offline = {};
const bucket = (swap, logic, key) => {
  offline[swap] ??= {};
  offline[swap][logic] ??= {};
  return (offline[swap][logic][key] ??= empty());
};
let sideAgreements = 0, sideChecks = 0, documentedFeeWhenDisabled = 0;

for (const baseInput of [true, false]) {
  const swap = baseInput ? "swap_base_input" : "swap_base_output";
  for (const cfg of tiers) for (const [modeName, feeOn] of MODES) for (const enabled of [true, false]) for (const baseIn of [true, false]) {
    for (let n = 0; n < CASES; n++) {
      const reserveA = reserve(), reserveB = reserve();
      const [inV, outV] = baseIn ? [reserveA, reserveB] : [reserveB, reserveA];
      const amount = baseInput ? share(inV) : share(outV);
      const pOn = programOnInput(feeOn, baseIn), pRate = enabled ? cfg.creator : 0n;   // adjust_creator_fee_rate
      const program = (baseInput ? programBaseInput : programBaseOutput)(amount, inV, outV, cfg.trade, pRate, cfg.protocol, cfg.fund, pOn);
      if (!program) { n--; continue; }
      const dOn = documentedOnInput(feeOn, baseIn), dRate = enabled ? cfg.creator : 0n;
      sideChecks++; if (dOn === pOn) sideAgreements++;
      const logics = {
        documented: [dOn, dRate],
        computeSwapAmount: [computeSwapAmountOnInput(feeOn), cfg.creator],
      };
      for (const [logic, [on, rate]] of Object.entries(logics)) {
        const q = sdkQuote(baseInput, amount, inV, outV, cfg, rate, on);
        if (logic === "documented" && !enabled && q.creatorFee !== 0n) documentedFeeWhenDisabled++;
        const key = !enabled ? "creator_fee_disabled" : pOn ? "creator_fee_on_input" : "creator_fee_on_output";
        const keys = [key, `${modeName}_${baseIn ? "A_to_B" : "B_to_A"}_${enabled ? "enabled" : "disabled"}`];
        for (const k of keys) {
          const b = bucket(swap, logic, k);
          b.cases++;
          const quoted = baseInput ? q.outputAmount : q.inputAmount, actual = baseInput ? program.outputAmount : program.inputAmount;
          if (quoted === actual) b.quote_equal++;
          if (FIELDS.every((f) => q[f] === program[f])) b.all_fields_equal++;
          // "lower" means worse for the trader: less output, or more input required.
          const worse = baseInput ? quoted < actual : quoted > actual, better = baseInput ? quoted > actual : quoted < actual;
          if (worse) {
            b.sdk_lower++;
            if (q.tradeFee + q.creatorFee === program.tradeFee + program.creatorFee + 1n) b.sdk_fee_one_unit_higher_when_lower++;
          }
          if (better) b.sdk_higher++;
          if ((worse || better) && b.examples.length < 3 && k === key)
            b.examples.push({ tier: cfg.index, mode: modeName, baseIn, amount: `${amount}`, inV: `${inV}`, outV: `${outV}`,
                              program: `${actual}`, sdk: `${quoted}` });
        }
      }
    }
  }
}

// ---- Optional read-only mainnet quotes ----
let mainnet = null;
if (arg("--rpc-url")) {
  const { Connection } = require("@solana/web3.js");
  const token = arg("--rpc-token-env") ? process.env[arg("--rpc-token-env")] : undefined;
  const connection = new Connection(arg("--rpc-url"), { commitment: "confirmed", httpHeaders: token ? { "x-token": token } : undefined });
  const raydium = await sdk.Raydium.load({ connection, cluster: "mainnet", disableFeatureCheck: true, disableLoadToken: true });
  const pools = readFileSync(join(REPO, "public/tino-changes/evidence/cpmm-2026-11-21/pool-lp-supply.csv"), "utf8")
    .trim().split(/\r?\n/).slice(1).map((l) => l.split(",")).map((c) => ({ id: c[0], tvl: Number(c[1]), status: Number(c[2]), enabled: c[6] === "True" }))
    .sort((a, b) => b.tvl - a.tvl);
  const picks = [pools.find((p) => p.enabled && p.status === 0), pools.find((p) => !p.enabled && p.status === 0)];
  mainnet = { slot: await connection.getSlot("confirmed"), pools: [] };
  for (const pick of picks) {
    const { rpcData } = await raydium.cpmm.getPoolInfoFromRpc(pick.id);
    const cfg = { trade: big(rpcData.configInfo.tradeFeeRate), protocol: big(rpcData.configInfo.protocolFeeRate), fund: big(rpcData.configInfo.fundFeeRate), creator: big(rpcData.configInfo.creatorFeeRate) };
    const inV = big(rpcData.baseReserve), outV = big(rpcData.quoteReserve), amount = inV / 1000n;  // token A -> token B
    const program = programBaseInput(amount, inV, outV, cfg.trade, rpcData.enableCreatorFee ? cfg.creator : 0n, cfg.protocol, cfg.fund, programOnInput(rpcData.feeOn, true));
    const documented = sdkQuote(true, amount, inV, outV, cfg, rpcData.enableCreatorFee ? cfg.creator : 0n, documentedOnInput(rpcData.feeOn, true));
    const compute = sdkQuote(true, amount, inV, outV, cfg, cfg.creator, computeSwapAmountOnInput(rpcData.feeOn));
    mainnet.pools.push({
      pool: pick.id, fee_on: Object.keys(FeeOn).find((k) => FeeOn[k] === rpcData.feeOn), enable_creator_fee: rpcData.enableCreatorFee,
      amount_in_token_a: `${amount}`,
      program_output: `${program.outputAmount}`, program_creator_fee: `${program.creatorFee}`,
      documented_output: `${documented.outputAmount}`, documented_creator_fee: `${documented.creatorFee}`,
      compute_swap_amount_output: `${compute.outputAmount}`, compute_swap_amount_creator_fee: `${compute.creatorFee}`,
      compute_swap_amount_shortfall: `${program.outputAmount - compute.outputAmount}`,
    });
  }
}

const stamp = new Date();
const out = join(REPO, "public", "tino-changes", "evidence", `cpmm-quotes-${stamp.toISOString().slice(0, 10)}`);
mkdirSync(out, { recursive: true });
const summary = {
  generated_at: stamp.toISOString(),
  sdk: `@raydium-io/raydium-sdk-v2@${require("@raydium-io/raydium-sdk-v2/package.json").version}`,
  program: "raydium-io/raydium-cp-swap@3d69122790e97cd6aff24e8ba95940793773f58c",
  generator: { lcg: "x = x * 6364136223846793005 + 1442695040888963407 mod 2^64, output x >> 11", seed: 42, cases_per_combination: CASES,
               reserves: "uniform within a random digit count of 6 to 15",
               amounts: "uniform 0.01% to 10% of the input reserve (exact input) or output reserve (exact output), at least 1" },
  tiers: tiers.length,
  documented_side_matches_program: `${sideAgreements} of ${sideChecks}`,
  documented_creator_fee_when_disabled: documentedFeeWhenDisabled,
  offline,
  mainnet,
};
writeFileSync(join(out, "result.json"), JSON.stringify(summary, null, 2) + "\n");
for (const [swap, logics] of Object.entries(offline)) for (const [logic, keys] of Object.entries(logics))
  for (const k of ["creator_fee_disabled", "creator_fee_on_input", "creator_fee_on_output"]) {
    const b = keys[k];
    console.log(`${swap} ${logic} ${k}: ${b.quote_equal}/${b.cases} equal, ${b.sdk_lower} worse (${b.sdk_fee_one_unit_higher_when_lower} by a one-unit-higher fee), ${b.sdk_higher} better`);
  }
for (const k of ["OnlyTokenA_A_to_B_enabled", "OnlyTokenB_A_to_B_enabled"]) {
  const b = offline.swap_base_input.computeSwapAmount[k];
  console.log(`swap_base_input computeSwapAmount ${k}: ${b.quote_equal}/${b.cases} equal`);
}
console.log("documented side matches program:", summary.documented_side_matches_program, "; documented fee when disabled:", documentedFeeWhenDisabled);
if (mainnet) console.log(JSON.stringify(mainnet, null, 2));
console.log(`wrote ${out}`);
