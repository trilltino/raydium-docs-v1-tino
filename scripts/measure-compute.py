#!/usr/bin/env python3
"""Measure per-instruction compute for AMM v4, CPMM and CLMM, and save the evidence.

Samples the most recent successful mainnet transactions of each program through the
configured Solana RPC and writes, under public/tino-changes/evidence/compute-<UTC date>/:

- compute-units.csv  One row per invocation of a watched program: sample, signature, slot,
                     block time, program, calling program, instruction, account count, the
                     compute units from the program's own "consumed" log line, and the part
                     of that spent outside the programs it called.
- summary.json       Parameters, time ranges, and per-instruction sample sizes, medians,
                     10th-90th percentiles and account counts.

A program's CU figure includes the programs it calls, such as the token program. It is not
the whole transaction, and it is not the compute-unit limit a priority fee is charged on.

Run: py -I scripts/measure-compute.py [--txs 1000] [--programs amm-v4,cpmm,clmm] [--before-time 2026-09-09T12:00:00Z]

For an authenticated RPC, pass `--rpc-url` with `--rpc-token-prompt`, or with
`--rpc-token-env NAME` where no prompt is possible. The script sends the token as `x-token`
and never writes it or the RPC URL to the evidence.
"""

import argparse
import base64
import csv
import getpass
import hashlib
import http.client
import json
import os
import re
import statistics
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

RPC = "https://api.mainnet-beta.solana.com"
AMM_V4 = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"  # see reference/program-addresses
CPMM = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"  # see reference/program-addresses
CLMM = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"  # see reference/program-addresses
STABLE = "5quBtoiQqxF9Jv6KYKctB59NT3gtJD2Y65kdnB1Uev3h"  # see reference/program-addresses
ROUTER = "routeUGWgWzqBWFcrCfv8tritsqukccJPu3q5GPP3xS"  # see reference/program-addresses
SAMPLES = {"amm-v4": AMM_V4, "cpmm": CPMM, "clmm": CLMM}
WATCH = {AMM_V4: "AMM v4", CPMM: "CPMM", CLMM: "CLMM", STABLE: "Stable AMM", ROUTER: "AMM Routing"}
CALLERS = {ROUTER: "AMM Routing", "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter v6"}
AMM_TAGS = {0: "Initialize", 1: "Initialize2", 3: "Deposit", 4: "Withdraw", 6: "SetParams", 7: "WithdrawPnl",
            9: "SwapBaseIn (v1)", 11: "SwapBaseOut (v1)", 14: "CreateConfigAccount", 15: "UpdateConfigAccount",
            16: "SwapBaseInV2", 17: "SwapBaseOutV2", 18: "WithdrawExcessLamports"}
STABLE_TAGS = {9: "SwapBaseIn", 11: "SwapBaseOut"}
ANCHOR = {
    CPMM: ["initialize", "initialize_v2", "initialize_with_permission", "deposit", "withdraw",
           "swap_base_input", "swap_base_output", "collect_protocol_fee", "collect_fund_fee",
           "collect_creator_fee", "collect_creator_fee_permissionless", "create_amm_config",
           "update_amm_config", "update_pool_status", "create_permission_pda", "close_permission_pda",
           "create_support_mint_associated", "close_support_mint_associated",
           "create_creator_fee_share", "close_creator_fee_share", "collect_excess_lamports"],
    CLMM: ["create_amm_config", "update_amm_config", "create_pool", "create_customizable_pool",
           "create_customizable_pool_v2", "update_pool_status", "create_operation_account",
           "update_operation_account", "transfer_reward_owner", "initialize_reward",
           "collect_remaining_rewards", "update_reward_infos", "set_reward_params",
           "collect_protocol_fee", "collect_fund_fee", "open_position", "open_position_v2",
           "open_position_with_token22_nft", "close_position", "increase_liquidity",
           "increase_liquidity_v2", "decrease_liquidity", "decrease_liquidity_v2", "swap", "swap_v2",
           "swap_router_base_in", "open_limit_order", "increase_limit_order", "decrease_limit_order",
           "settle_limit_order", "close_limit_order", "create_dynamic_fee_config",
           "update_dynamic_fee_config", "collect_excess_lamports"],
}
DISC = {program: {hashlib.sha256(f"global:{name}".encode()).digest()[:8]: name for name in names}
        for program, names in ANCHOR.items()}
# Where each swap's pool and mints sit in its account list (from the programs' account structs).
POOL_AT = {(CPMM, "swap_base_input"): 3, (CPMM, "swap_base_output"): 3, (CLMM, "swap_v2"): 2, (CLMM, "swap"): 2,
           (AMM_V4, "SwapBaseInV2"): 1, (AMM_V4, "SwapBaseOutV2"): 1, (AMM_V4, "SwapBaseIn (v1)"): 1, (AMM_V4, "SwapBaseOut (v1)"): 1}
MINTS_AT = {(CPMM, "swap_base_input"): (10, 11), (CPMM, "swap_base_output"): (10, 11), (CLMM, "swap_v2"): (11, 12)}
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
INVOKE = re.compile(r"^Program (\S+) invoke \[(\d+)\]$")
CONSUMED = re.compile(r"^Program (\S+) consumed (\d+) of \d+ compute units$")
ENDED = re.compile(r"^Program (\S+) (success|failed)")
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
HEADERS = {"content-type": "application/json", "user-agent": "docs-measurement/1.0"}
WORKERS = 4


def post(url, payload):
    body = json.dumps(payload).encode()
    for attempt in range(10):
        try:
            req = urllib.request.Request(url, data=body, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as err:
            if err.code == 429 or err.code >= 500:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, http.client.IncompleteRead, ConnectionError):
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("request kept failing")


def rpc(method, params):
    # A JSON-RPC error is usually a provider's rate limit; back off and retry before giving up.
    for attempt in range(6):
        reply = post(RPC, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if "error" not in reply:
            return reply["result"]
        time.sleep(1.0 * (attempt + 1))
    return None


def b58decode(text):
    number = 0
    for char in text:
        number = number * 58 + ALPHABET.index(char)
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\x00" * (len(text) - len(text.lstrip("1"))) + raw


def label(program, data):
    raw = b58decode(data)
    if not raw:
        return "empty"
    if program == AMM_V4:
        return AMM_TAGS.get(raw[0], f"tag {raw[0]}")
    if program == STABLE:
        return STABLE_TAGS.get(raw[0], f"tag {raw[0]}")
    if program in DISC:
        return DISC[program].get(raw[:8], "other")
    return f"tag {raw[0]}"


def invocations(tx, sampled):
    """Every watched invocation in a transaction, with its CU and its callees' CU, and a skip reason."""
    meta, message = tx["meta"], tx["transaction"]["message"]
    logs = meta.get("logMessages") or []
    loaded = meta.get("loadedAddresses") or {}
    keys = message["accountKeys"] + loaded.get("writable", []) + loaded.get("readonly", [])
    inner = {group["index"]: group["instructions"] for group in meta.get("innerInstructions") or []}
    flat = []
    for index, top in enumerate(message["instructions"]):
        for ix in [dict(top, stackHeight=1)] + inner.get(index, []):
            flat.append({"program": keys[ix["programIdIndex"]], "accounts": len(ix["accounts"]), "data": ix["data"],
                         "keys": [keys[i] for i in ix["accounts"]]})
    if all(f["program"] != sampled for f in flat):
        return [], "program listed but not called"
    if any("Log truncated" in line for line in logs):
        return [], "logs truncated"
    # Pair each instruction with its "invoke" log line; both lists are in execution order.
    nodes, stack = [], []
    for line in logs:
        if match := INVOKE.match(line):
            node = {"program": match.group(1), "cu": None, "callee_cu": 0, "parent": stack[-1] if stack else None}
            nodes.append(node)
            stack.append(node)
        elif (match := CONSUMED.match(line)) and stack and stack[-1]["program"] == match.group(1):
            stack[-1]["cu"] = int(match.group(2))
        elif (match := ENDED.match(line)) and stack and stack[-1]["program"] == match.group(1):
            node = stack.pop()
            if node["parent"] is not None:
                node["parent"]["callee_cu"] += node["cu"] or 0
    if len(nodes) != len(flat) or any(n["program"] != f["program"] for n, f in zip(nodes, flat)):
        return [], "logs do not match instructions"
    found = []
    for node, ix in zip(nodes, flat):
        if node["program"] not in WATCH or node["cu"] is None:
            continue
        name = label(node["program"], ix["data"])
        at = lambda i: ix["keys"][i] if i is not None and i < len(ix["keys"]) else ""
        mints = MINTS_AT.get((node["program"], name), (None, None))
        found.append({"program": node["program"],
                      "caller": node["parent"]["program"] if node["parent"] else "top-level",
                      "accounts": ix["accounts"], "instruction": name,
                      "cu": node["cu"], "own_cu": node["cu"] - node["callee_cu"],
                      "pool": at(POOL_AT.get((node["program"], name))), "mint_in": at(mints[0]), "mint_out": at(mints[1])})
    return found, None if found else "no CU line for the program"


def signature_at(when):
    """A transaction signature from the first block at or after `when`, found by bisecting slots."""
    def block_time(slot):
        for probe in range(slot, slot + 50):  # skip slots that produced no block
            value = rpc("getBlockTime", [probe])
            if value is not None:
                return probe, value
        raise RuntimeError(f"no block near slot {slot}")
    target = int(when.timestamp())
    high = rpc("getSlot", [])
    step = int((datetime.now(timezone.utc) - when).total_seconds() / 0.4)
    low = max(0, high - step)
    while low > 0 and block_time(low)[1] >= target:  # slot times vary; widen until low is before the target
        low = max(0, low - step)
    while high - low > 1:
        middle = (low + high) // 2
        if block_time(middle)[1] < target:
            low = middle
        else:
            high = middle
    slot, found = block_time(high)
    block = rpc("getBlock", [slot, {"transactionDetails": "signatures", "rewards": False, "maxSupportedTransactionVersion": 1}])
    return slot, found, block["signatures"][0]


def mint_kinds(mints):
    """SPL Token, Token-2022, or Token-2022 with a TransferFeeConfig extension, for each mint."""
    kinds, mints = {}, sorted(m for m in mints if m)
    for start in range(0, len(mints), 100):
        chunk = mints[start:start + 100]
        for mint, account in zip(chunk, rpc("getMultipleAccounts", [chunk, {"encoding": "base64"}])["value"]):
            if not account:
                continue
            if account["owner"] == TOKEN:
                kinds[mint] = "SPL Token"
                continue
            data, offset, fee = base64.b64decode(account["data"][0]), 166, False
            while offset + 4 <= len(data):  # Token-2022 extensions: u16 type, u16 length, value
                kind, length = int.from_bytes(data[offset:offset + 2], "little"), int.from_bytes(data[offset + 2:offset + 4], "little")
                fee |= kind == 1  # TransferFeeConfig
                offset += 4 + length
            kinds[mint] = "Token-2022 with transfer fee" if fee else "Token-2022"
    return kinds


def sample_address(sample, address, count, before=None, program=None):
    signatures = []
    while len(signatures) < count:
        page = rpc("getSignaturesForAddress", [address, {"limit": 1000, "before": before} if before else {"limit": 1000}])
        if not page:
            break
        signatures += [s["signature"] for s in page if s["err"] is None][: count - len(signatures)]
        before = page[-1]["signature"]
    def fetch(signature):
        return signature, rpc("getTransaction", [signature, {"encoding": "json", "maxSupportedTransactionVersion": 1}])

    rows, skipped = [], Counter()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        fetched = list(pool.map(fetch, signatures))
    for signature, tx in fetched:
        if not tx:
            skipped["RPC returned no transaction"] += 1
            continue
        found, reason = invocations(tx, program or address)
        if reason:
            skipped[reason] += 1
        block_time = tx.get("blockTime")
        for item in found:
            rows.append({"sample": sample, "signature": signature, "slot": tx["slot"],
                         "block_time": datetime.fromtimestamp(block_time, timezone.utc).isoformat() if block_time else "",
                         "program": WATCH[item["program"]], "caller": CALLERS.get(item["caller"], item["caller"]),
                         "instruction": item["instruction"], "accounts": item["accounts"],
                         "cu": item["cu"], "own_cu": item["own_cu"],
                         "pool": item["pool"], "mint_in": item["mint_in"], "mint_out": item["mint_out"]})
    print(f"{sample}: {len(signatures)} transactions, {sum(skipped.values())} skipped, {len(rows)} invocations")
    return rows, len(signatures), dict(skipped.most_common())


def stats(values):
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {"n": len(ordered), "median": int(statistics.median(ordered)),
            "p10": ordered[int(len(ordered) * 0.1)], "p90": ordered[min(int(len(ordered) * 0.9), len(ordered) - 1)],
            "min": ordered[0], "max": ordered[-1]}


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    global RPC, WORKERS
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--txs", type=int, default=1000, help="transactions per program")
    parser.add_argument("--programs", default="amm-v4,cpmm,clmm", help="comma-separated: " + ",".join(SAMPLES))
    parser.add_argument("--rpc-url", default=RPC, help="Solana JSON-RPC endpoint")
    parser.add_argument("--rpc-label", default="Solana public mainnet RPC",
                        help="provider label written to summary.json; do not include credentials")
    parser.add_argument("--rpc-token-prompt", action="store_true",
                        help="prompt for an x-token without storing it in shell history")
    parser.add_argument("--rpc-token-env", metavar="NAME",
                        help="read the x-token from this environment variable, for non-interactive runs")
    parser.add_argument("--workers", type=int, default=WORKERS, help="parallel getTransaction requests")
    parser.add_argument("--label", default="", help="suffix for the evidence folder name, e.g. same-pools")
    parser.add_argument("--pools", default="",
                        help="also sample these pools' own transactions: comma-separated program:address, "
                             "e.g. cpmm:<pool address>")
    parser.add_argument("--before-time", metavar="ISO-8601",
                        help="sample the transactions just before this UTC time instead of the latest ones, "
                             "e.g. 2026-09-09T12:00:00Z; needs an RPC with full history")
    args = parser.parse_args()
    WORKERS = args.workers
    RPC = args.rpc_url
    if args.rpc_token_prompt:
        HEADERS["x-token"] = getpass.getpass("RPC x-token: ")
    elif args.rpc_token_env:
        HEADERS["x-token"] = os.environ[args.rpc_token_env]
    started = datetime.now(timezone.utc)

    sampled_at, anchor = started, None
    if args.before_time:
        sampled_at = datetime.fromisoformat(args.before_time.replace("Z", "+00:00"))
        anchor_slot, anchor_time, anchor = signature_at(sampled_at)
        print(f"sampling before slot {anchor_slot}, block time {datetime.fromtimestamp(anchor_time, timezone.utc).isoformat()}")

    rows, samples = [], {}
    for name in filter(None, args.programs.split(",")):
        found, count, skipped = sample_address(name, SAMPLES[name], args.txs, before=anchor)
        rows += found
        samples[name] = {"transactions": count, "skipped": skipped, "program": SAMPLES[name]}
    for spec in filter(None, args.pools.split(",")):
        kind, address = spec.split(":")
        name = f"pool-{kind}-{address}"
        found, count, skipped = sample_address(name, address, args.txs, before=anchor, program=SAMPLES[kind])
        rows += found
        samples[name] = {"transactions": count, "skipped": skipped, "program": SAMPLES[kind], "pool": address}

    kinds = mint_kinds({r["mint_in"] for r in rows} | {r["mint_out"] for r in rows})
    for r in rows:
        if r["mint_in"] or r["mint_out"]:
            found_kinds = {kinds.get(r["mint_in"], "unknown"), kinds.get(r["mint_out"], "unknown")}
            r["token_kind"] = next((k for k in ("Token-2022 with transfer fee", "Token-2022", "unknown") if k in found_kinds), "SPL Token")
        else:
            # AMM v4 and CLMM `swap` accept only SPL Token mints, so they pass no mint accounts.
            r["token_kind"] = "SPL Token" if r["pool"] else ""

    summary = {
        "generated_at": started.isoformat(),
        "sampled_before": sampled_at.isoformat() if args.before_time else None,
        "rpc_provider": args.rpc_label,
        "slot": rpc("getSlot", []),
        "token_kind_note": "mint state read when the script ran, not at the time of each transaction",
        "measure": "each program's own 'consumed' log line, including the programs it calls; "
                   "own_cu subtracts the callees. Not the transaction total or the requested limit.",
        "samples": {},
    }
    for name, meta in samples.items():
        program = WATCH[meta.pop("program")]
        mine = [r for r in rows if r["sample"] == name and r["program"] == program]
        times = sorted(r["block_time"] for r in rows if r["sample"] == name and r["block_time"])
        summary["samples"][name] = {
            **meta,
            "block_time_range": [times[0], times[-1]] if times else None,
            "instructions": {
                ins: {**stats([r["cu"] for r in mine if r["instruction"] == ins]),
                      "accounts": dict(sorted(Counter(r["accounts"] for r in mine if r["instruction"] == ins).items())),
                      "callers": dict(Counter(r["caller"] for r in mine if r["instruction"] == ins).most_common(5)),
                      "by_token_kind": {kind: stats([r["cu"] for r in mine if r["instruction"] == ins and r["token_kind"] == kind])
                                        for kind in sorted({r["token_kind"] for r in mine if r["instruction"] == ins and r["token_kind"]})},
                      "top_pools": {pool: stats([r["cu"] for r in mine if r["instruction"] == ins and r["pool"] == pool])
                                    for pool, _ in Counter(r["pool"] for r in mine if r["instruction"] == ins and r["pool"]).most_common(5)}}
                for ins in sorted({r["instruction"] for r in mine}, key=lambda i: -sum(r["instruction"] == i for r in mine))
            },
        }

    out = Path(__file__).resolve().parent.parent / "public" / "tino-changes" / "evidence" / (f"compute-{sampled_at:%Y-%m-%d}" + (f"-{args.label}" if args.label else ""))
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "compute-units.csv", rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
