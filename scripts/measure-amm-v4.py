#!/usr/bin/env python3
"""Measure the on-chain AMM v4 facts cited in the AMM v4 docs, and save the evidence.

Samples recent mainnet transactions through the configured Solana RPC and writes, under
public/tino-changes/evidence/amm-v4-<UTC date>/:

- compute-units.csv   One row per AMM v4 or CPMM invocation: sample, signature, slot,
                      block time, program, calling program, instruction, account count,
                      and the compute units from the program's own "consumed" log line.
- redeploy-blocks.csv The same, for AMM v4 swaps in blocks just before and just after
                      the AMM v4 redeploy at slot 445763204 (2026-09-10).
- pool-fees.csv       The on-chain Fees struct of every AMM v4 pool among the
                      highest-TVL standard pools listed by api-v3.
- summary.json        Parameters, counts and medians.

The CU figure is the program's own consumption, including its inner token-program
calls. It is not the whole transaction, and it is not the compute-unit limit that a
priority fee is charged on.

Run: py scripts/measure-amm-v4.py [--txs 400] [--pages 5]

For an authenticated RPC, pass `--rpc-url` and `--rpc-token-prompt`. The prompt keeps
the token out of shell history and generated evidence. The script sends it as `x-token`.
"""

import argparse
import base64
import csv
import getpass
import hashlib
import http.client
import json
import re
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RPC = "https://api.mainnet-beta.solana.com"
API = "https://api-v3.raydium.io/pools/info/list?poolType=standard&poolSortField=liquidity&sortType=desc&pageSize=1000&page={page}"
AMM_V4 = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"  # see reference/program-addresses
CPMM = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"  # see reference/program-addresses
ROUTER = "routeUGWgWzqBWFcrCfv8tritsqukccJPu3q5GPP3xS"  # see reference/program-addresses
REDEPLOY_SLOT = 445763204
WATCH = {AMM_V4: "AMM v4", CPMM: "CPMM"}
CALLERS = {ROUTER: "Raydium AMM Routing", "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter v6"}
AMM_TAGS = {1: "Initialize2", 3: "Deposit", 4: "Withdraw", 6: "SetParams", 7: "WithdrawPnl",
            9: "SwapBaseIn (v1)", 11: "SwapBaseOut (v1)", 16: "SwapBaseInV2", 17: "SwapBaseOutV2",
            18: "WithdrawExcessLamports"}
CPMM_NAMES = ["swap_base_input", "swap_base_output", "deposit", "withdraw", "initialize",
              "initialize_v2", "collect_protocol_fee", "collect_fund_fee", "collect_creator_fee"]
CPMM_DISC = {hashlib.sha256(f"global:{n}".encode()).digest()[:8]: n for n in CPMM_NAMES}
DEFAULT_FEES = (5, 10000, 25, 10000, 12, 100, 25, 10000)
FEE_FIELDS = ["min_separate_numerator", "min_separate_denominator", "trade_fee_numerator",
              "trade_fee_denominator", "pnl_numerator", "pnl_denominator",
              "swap_fee_numerator", "swap_fee_denominator"]
INVOKE = re.compile(r"^Program (\S+) invoke \[\d+\]$")
CONSUMED = re.compile(r"^Program (\S+) consumed (\d+) of \d+ compute units$")
ENDED = re.compile(r"^Program \S+ (success|failed)")
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
HEADERS = {"content-type": "application/json", "user-agent": "docs-measurement/1.0"}


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
    reply = post(RPC, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    return None if "error" in reply else reply["result"]


def get_json(url):
    req = urllib.request.Request(url, headers={"user-agent": HEADERS["user-agent"]})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.load(resp)


def b58decode(text):
    number = 0
    for char in text:
        number = number * 58 + ALPHABET.index(char)
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\x00" * (len(text) - len(text.lstrip("1"))) + raw


def label(program, data):
    raw = b58decode(data)
    if program == AMM_V4:
        return AMM_TAGS.get(raw[0], f"tag {raw[0]}") if raw else "empty"
    return CPMM_DISC.get(raw[:8], "other")


def invocations(tx):
    """Every AMM v4 / CPMM invocation in a transaction, paired with its CU log line."""
    meta, message = tx["meta"], tx["transaction"]["message"]
    logs = meta.get("logMessages") or []
    if any("Log truncated" in line for line in logs):
        return []
    loaded = meta.get("loadedAddresses") or {}
    keys = message["accountKeys"] + loaded.get("writable", []) + loaded.get("readonly", [])
    inner = {group["index"]: group["instructions"] for group in meta.get("innerInstructions") or []}
    found = []
    for index, top in enumerate(message["instructions"]):
        group = [dict(top, stackHeight=1)] + inner.get(index, [])
        for position, ix in enumerate(group):
            program = keys[ix["programIdIndex"]]
            if program not in WATCH:
                continue
            height = ix.get("stackHeight") or 1
            caller = "top-level"
            for back in range(position - 1, -1, -1):
                if height > 1 and (group[back].get("stackHeight") or 1) == height - 1:
                    caller = keys[group[back]["programIdIndex"]]
                    break
            found.append({"program": program, "caller": caller, "accounts": len(ix["accounts"]),
                          "instruction": label(program, ix["data"])})
    consumed = {program: [] for program in WATCH}
    stack = []
    for line in logs:
        if match := INVOKE.match(line):
            program = match.group(1)
            slot = None
            if program in WATCH:
                consumed[program].append(None)
                slot = len(consumed[program]) - 1
            stack.append((program, slot))
        elif (match := CONSUMED.match(line)) and stack and stack[-1][0] == match.group(1) and stack[-1][1] is not None:
            consumed[match.group(1)][stack[-1][1]] = int(match.group(2))
        elif ENDED.match(line) and stack:
            stack.pop()
    seen = {program: 0 for program in WATCH}
    for item in found:
        program = item["program"]
        values = consumed[program]
        if seen[program] >= len(values) or values[seen[program]] is None:
            return []
        item["cu"] = values[seen[program]]
        seen[program] += 1
    if any(seen[program] != len(consumed[program]) for program in WATCH):
        return []
    return found


def row(sample, signature, slot, block_time, item):
    return {"sample": sample, "signature": signature, "slot": slot,
            "block_time": datetime.fromtimestamp(block_time, timezone.utc).isoformat() if block_time else "",
            "program": WATCH[item["program"]], "caller": CALLERS.get(item["caller"], item["caller"]),
            "instruction": item["instruction"], "accounts": item["accounts"], "cu": item["cu"]}


def sample_address(sample, address, count):
    signatures, before = [], None
    while len(signatures) < count:
        page = rpc("getSignaturesForAddress", [address, {"limit": 1000, "before": before} if before else {"limit": 1000}])
        if not page:
            break
        signatures += [s["signature"] for s in page if s["err"] is None][: count - len(signatures)]
        before = page[-1]["signature"]
    rows = []
    for signature in signatures:
        time.sleep(0.12)
        tx = rpc("getTransaction", [signature, {"encoding": "json", "maxSupportedTransactionVersion": 1}])
        if tx and tx["meta"]["err"] is None:
            rows += [row(sample, signature, tx["slot"], tx.get("blockTime"), item) for item in invocations(tx)]
    print(f"{sample}: {len(signatures)} transactions, {len(rows)} invocations")
    return rows


def sample_blocks(phase, slots):
    rows = []
    for slot in slots:
        block = rpc("getBlock", [slot, {"encoding": "json", "maxSupportedTransactionVersion": 1,
                                         "transactionDetails": "full", "rewards": False}])
        if not block:
            continue
        for tx in block["transactions"]:
            if tx["meta"]["err"] is None:
                rows += [row(phase, tx["transaction"]["signatures"][0], slot, block.get("blockTime"), item)
                         for item in invocations(tx) if item["program"] == AMM_V4 and "Swap" in item["instruction"]]
        time.sleep(0.5)
    print(f"{phase}: {len(rows)} AMM v4 swaps")
    return rows


def pool_fees(pages):
    pools = []
    for page in range(1, pages + 1):
        data = get_json(API.format(page=page))["data"]
        pools += [(p["id"], p["tvl"], p["feeRate"]) for p in data["data"] if p["programId"] == AMM_V4]
        if not data["hasNextPage"]:
            break
    rows = []
    for start in range(0, len(pools), 100):
        chunk = pools[start:start + 100]
        result = rpc("getMultipleAccounts", [[p[0] for p in chunk],
                                             {"encoding": "base64", "dataSlice": {"offset": 128, "length": 64}}])
        for (pool_id, tvl, api_fee), account in zip(chunk, result["value"]):
            if not account:
                continue
            raw = base64.b64decode(account["data"][0])
            fees = [int.from_bytes(raw[i * 8:(i + 1) * 8], "little") for i in range(8)]
            rows.append({"pool": pool_id, "tvl_usd": round(tvl), "api_fee_rate": api_fee,
                         **dict(zip(FEE_FIELDS, fees)), "is_default": tuple(fees) == DEFAULT_FEES})
        time.sleep(0.2)
    print(f"pool fees: {len(rows)} AMM v4 pools")
    return rows


def median(values):
    return int(statistics.median(values)) if values else None


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    global RPC
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--txs", type=int, default=400, help="transactions per sample")
    parser.add_argument("--pages", type=int, default=5, help="api-v3 pages of 1,000 pools to scan")
    parser.add_argument("--rpc-url", default=RPC, help="Solana JSON-RPC endpoint")
    parser.add_argument("--rpc-label", default="Solana mainnet RPC",
                        help="provider label written to summary.json; do not include credentials")
    parser.add_argument("--rpc-token-prompt", action="store_true",
                        help="prompt for an x-token without storing it in shell history")
    args = parser.parse_args()
    RPC = args.rpc_url
    if args.rpc_token_prompt:
        HEADERS["x-token"] = getpass.getpass("RPC x-token: ")
    started = datetime.now(timezone.utc)

    units = (sample_address("amm-v4-program", AMM_V4, args.txs)
             + sample_address("amm-routing-program", ROUTER, args.txs)
             + sample_address("cpmm-program", CPMM, args.txs))
    blocks = (sample_blocks("before-redeploy", range(REDEPLOY_SLOT - 400, REDEPLOY_SLOT - 395))
              + sample_blocks("after-redeploy", range(REDEPLOY_SLOT + 400, REDEPLOY_SLOT + 405)))
    fees = pool_fees(args.pages)

    def cu(rows, sample, program, instruction, caller=None):
        return [r["cu"] for r in rows if r["sample"] == sample and r["program"] == program
                and r["instruction"] == instruction and (caller is None or r["caller"] == caller)]

    amm_swaps = [r for r in units if r["sample"] == "amm-v4-program" and r["program"] == "AMM v4" and "Swap" in r["instruction"]]
    router_hops = [r for r in units if r["sample"] == "amm-routing-program" and r["caller"] == "Raydium AMM Routing" and r["program"] == "AMM v4"]
    summary = {
        "generated_at": started.isoformat(),
        "rpc_provider": args.rpc_label,
        "transactions_per_sample": args.txs,
        "measure": "the program's own 'consumed' log line, including its inner calls; not the transaction total or the requested limit",
        "median_cu": {
            "amm_v4_SwapBaseInV2": median(cu(units, "amm-v4-program", "AMM v4", "SwapBaseInV2")),
            "amm_v4_SwapBaseIn_v1": median(cu(units, "amm-v4-program", "AMM v4", "SwapBaseIn (v1)")),
            "cpmm_swap_base_input": median(cu(units, "cpmm-program", "CPMM", "swap_base_input")),
            "amm_v4_swaps_before_redeploy": median([r["cu"] for r in blocks if r["sample"] == "before-redeploy"]),
            "amm_v4_swaps_after_redeploy": median([r["cu"] for r in blocks if r["sample"] == "after-redeploy"]),
        },
        "sample_sizes": {
            "amm_v4_SwapBaseInV2": len(cu(units, "amm-v4-program", "AMM v4", "SwapBaseInV2")),
            "amm_v4_SwapBaseIn_v1": len(cu(units, "amm-v4-program", "AMM v4", "SwapBaseIn (v1)")),
            "cpmm_swap_base_input": len(cu(units, "cpmm-program", "CPMM", "swap_base_input")),
        },
        "amm_v4_swaps_by_format": {
            "v1": sum("(v1)" in r["instruction"] for r in amm_swaps),
            "V2": sum("V2" in r["instruction"] for r in amm_swaps),
        },
        "router_amm_v4_hops": {
            "total": len(router_hops),
            "by_instruction": {name: sum(r["instruction"] == name for r in router_hops)
                               for name in sorted({r["instruction"] for r in router_hops})},
            "by_account_count": {str(n): sum(r["accounts"] == n for r in router_hops)
                                 for n in sorted({r["accounts"] for r in router_hops})},
        },
        "pool_fees": {"pools_read": len(fees), "non_default": sum(not r["is_default"] for r in fees),
                      "lowest_tvl_usd": min((r["tvl_usd"] for r in fees), default=None)},
    }

    out = Path(__file__).resolve().parent.parent / "public" / "tino-changes" / "evidence" / f"amm-v4-{started:%Y-%m-%d}"
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "compute-units.csv", units)
    write_csv(out / "redeploy-blocks.csv", blocks)
    write_csv(out / "pool-fees.csv", fees)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
