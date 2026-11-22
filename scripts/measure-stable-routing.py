#!/usr/bin/env python3
"""Measure Stable AMM swap compute and AMM Routing per-hop compute, and save the evidence.

Samples recent successful mainnet transactions of two programs through the configured
Solana RPC and writes, under public/tino-changes/evidence/stable-routing-<UTC date>/:

- compute-units.csv  One row per invocation of a watched program (Stable AMM, AMM v4,
                     CPMM, CLMM, AMM Routing): sample, signature, slot, block time,
                     program, calling program, instruction, account count, the compute
                     units from the program's own "consumed" log line, the part of that
                     spent outside the programs it called, and, for the router, how many
                     pool hops it made.
- summary.json       Parameters, sample sizes, medians and 10th-90th percentiles.

The two samples are the most recent transactions that mention the Stable AMM program
("stable-program") and the AMM Routing program ("amm-routing-program").

A program's CU figure includes the programs it calls. The router's "own" figure is its
consumption minus that of the programs it called, so it covers its dispatch logic and
the cost of making each call. Neither is the whole transaction, and neither is the
compute-unit limit that a priority fee is charged on.

Stable AMM instruction tags 9 (SwapBaseIn) and 11 (SwapBaseOut) are confirmed by the
program's own "swap_base_in" / "swap_base_out" log lines. Other tags are recorded as
"tag N".

Run: py -I scripts/measure-stable-routing.py [--txs 400]

For an authenticated RPC, pass `--rpc-url` and `--rpc-token-prompt`. The prompt keeps
the token out of shell history and generated evidence. Where no prompt is possible, pass
`--rpc-token-env NAME` to read it from that environment variable instead. Either way the
script sends it as `x-token` and never writes it or the RPC URL to the evidence.
"""

import argparse
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
from datetime import datetime, timezone
from pathlib import Path

RPC = "https://api.mainnet-beta.solana.com"
STABLE = "5quBtoiQqxF9Jv6KYKctB59NT3gtJD2Y65kdnB1Uev3h"  # see reference/program-addresses
AMM_V4 = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"  # see reference/program-addresses
CPMM = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"  # see reference/program-addresses
CLMM = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"  # see reference/program-addresses
ROUTER = "routeUGWgWzqBWFcrCfv8tritsqukccJPu3q5GPP3xS"  # see reference/program-addresses
WATCH = {STABLE: "Stable AMM", AMM_V4: "AMM v4", CPMM: "CPMM", CLMM: "CLMM", ROUTER: "AMM Routing"}
POOLS = {STABLE, AMM_V4, CPMM, CLMM}
CALLERS = {ROUTER: "AMM Routing", "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter v6"}
STABLE_TAGS = {9: "SwapBaseIn", 11: "SwapBaseOut"}
AMM_TAGS = {9: "SwapBaseIn (v1)", 11: "SwapBaseOut (v1)", 16: "SwapBaseInV2", 17: "SwapBaseOutV2"}
ANCHOR = {
    CPMM: ["swap_base_input", "swap_base_output"],
    CLMM: ["swap", "swap_v2", "swap_router_base_in"],
}
DISC = {program: {hashlib.sha256(f"global:{name}".encode()).digest()[:8]: name for name in names}
        for program, names in ANCHOR.items()}
INVOKE = re.compile(r"^Program (\S+) invoke \[(\d+)\]$")
CONSUMED = re.compile(r"^Program (\S+) consumed (\d+) of \d+ compute units$")
ENDED = re.compile(r"^Program (\S+) (success|failed)")
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
    if program == STABLE:
        return STABLE_TAGS.get(raw[0], f"tag {raw[0]}")
    if program == AMM_V4:
        return AMM_TAGS.get(raw[0], f"tag {raw[0]}")
    if program in DISC:
        return DISC[program].get(raw[:8], "other")
    return f"tag {raw[0]}"


def invocations(tx):
    """Every invocation in a transaction, in execution order, with its CU and its callees' CU."""
    meta, message = tx["meta"], tx["transaction"]["message"]
    logs = meta.get("logMessages") or []
    if any("Log truncated" in line for line in logs):
        return []
    loaded = meta.get("loadedAddresses") or {}
    keys = message["accountKeys"] + loaded.get("writable", []) + loaded.get("readonly", [])
    inner = {group["index"]: group["instructions"] for group in meta.get("innerInstructions") or []}
    flat = []
    for index, top in enumerate(message["instructions"]):
        for ix in [dict(top, stackHeight=1)] + inner.get(index, []):
            flat.append({"program": keys[ix["programIdIndex"]], "height": ix.get("stackHeight") or 1,
                         "accounts": len(ix["accounts"]), "data": ix["data"]})
    # Pair each instruction with its "invoke" log line; the two lists are in the same order.
    nodes, stack = [], []
    for line in logs:
        if match := INVOKE.match(line):
            node = {"program": match.group(1), "cu": None, "callee_cu": 0, "hops": 0, "parent": stack[-1] if stack else None}
            nodes.append(node)
            stack.append(node)
        elif (match := CONSUMED.match(line)) and stack and stack[-1]["program"] == match.group(1):
            stack[-1]["cu"] = int(match.group(2))
        elif (match := ENDED.match(line)) and stack and stack[-1]["program"] == match.group(1):
            node = stack.pop()
            if node["parent"] is not None:
                node["parent"]["callee_cu"] += node["cu"] or 0
                node["parent"]["hops"] += node["program"] in POOLS
    if len(nodes) != len(flat) or any(n["program"] != f["program"] for n, f in zip(nodes, flat)):
        return []
    found = []
    for node, ix in zip(nodes, flat):
        if node["program"] not in WATCH or node["cu"] is None:
            continue
        caller = node["parent"]["program"] if node["parent"] else "top-level"
        found.append({"program": node["program"], "caller": caller, "accounts": ix["accounts"],
                      "instruction": label(node["program"], ix["data"]), "cu": node["cu"],
                      "own_cu": node["cu"] - node["callee_cu"], "pool_hops": node["hops"]})
    return found


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
        if not tx or tx["meta"]["err"] is not None:
            continue
        block_time = tx.get("blockTime")
        for item in invocations(tx):
            rows.append({"sample": sample, "signature": signature, "slot": tx["slot"],
                         "block_time": datetime.fromtimestamp(block_time, timezone.utc).isoformat() if block_time else "",
                         "program": WATCH[item["program"]], "caller": CALLERS.get(item["caller"], item["caller"]),
                         "instruction": item["instruction"], "accounts": item["accounts"], "cu": item["cu"],
                         "own_cu": item["own_cu"], "pool_hops": item["pool_hops"]})
    print(f"{sample}: {len(signatures)} transactions, {len(rows)} invocations")
    return rows


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
    global RPC
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--txs", type=int, default=400, help="transactions per sample")
    parser.add_argument("--rpc-url", default=RPC, help="Solana JSON-RPC endpoint")
    parser.add_argument("--rpc-label", default="Solana public mainnet RPC",
                        help="provider label written to summary.json; do not include credentials")
    parser.add_argument("--rpc-token-prompt", action="store_true",
                        help="prompt for an x-token without storing it in shell history")
    parser.add_argument("--rpc-token-env", metavar="NAME",
                        help="read the x-token from this environment variable, for non-interactive runs")
    args = parser.parse_args()
    RPC = args.rpc_url
    if args.rpc_token_prompt:
        HEADERS["x-token"] = getpass.getpass("RPC x-token: ")
    elif args.rpc_token_env:
        HEADERS["x-token"] = os.environ[args.rpc_token_env]
    started = datetime.now(timezone.utc)

    rows = sample_address("stable-program", STABLE, args.txs) + sample_address("amm-routing-program", ROUTER, args.txs)
    stable = [r for r in rows if r["sample"] == "stable-program" and r["program"] == "Stable AMM"]
    hops = [r for r in rows if r["sample"] == "amm-routing-program" and r["caller"] == "AMM Routing"]
    routers = [r for r in rows if r["sample"] == "amm-routing-program" and r["program"] == "AMM Routing" and r["pool_hops"] > 0]
    def time_range(sample):
        times = sorted({r["block_time"] for r in rows if r["sample"] == sample and r["block_time"]})
        return [times[0], times[-1]] if times else None

    summary = {
        "generated_at": started.isoformat(),
        "rpc_provider": args.rpc_label,
        "slot": rpc("getSlot", []),
        "transactions_per_sample": args.txs,
        "block_time_range": {sample: time_range(sample) for sample in ("stable-program", "amm-routing-program")},
        "measure": "each program's own 'consumed' log line, including the programs it calls; "
                   "own_cu subtracts the callees. Not the transaction total or the requested limit.",
        "stable_amm": {
            "instructions_seen": {name: sum(r["instruction"] == name for r in stable)
                                  for name in sorted({r["instruction"] for r in stable})},
            "SwapBaseIn": stats([r["cu"] for r in stable if r["instruction"] == "SwapBaseIn"]),
            "SwapBaseOut": stats([r["cu"] for r in stable if r["instruction"] == "SwapBaseOut"]),
            "SwapBaseIn_by_accounts": {str(n): stats([r["cu"] for r in stable if r["instruction"] == "SwapBaseIn" and r["accounts"] == n])
                                       for n in sorted({r["accounts"] for r in stable if r["instruction"] == "SwapBaseIn"})},
            "swaps_by_caller": {name: sum(r["caller"] == name for r in stable if r["instruction"].startswith("Swap"))
                                for name in sorted({r["caller"] for r in stable if r["instruction"].startswith("Swap")})},
        },
        "router_hops": {f"{program} {name}": stats([r["cu"] for r in hops if r["program"] == program and r["instruction"] == name])
                        for program, name in sorted({(r["program"], r["instruction"]) for r in hops})},
        "router_own_cu": {
            "all": stats([r["own_cu"] for r in routers]),
            "by_pool_hops": {str(n): stats([r["own_cu"] for r in routers if r["pool_hops"] == n])
                             for n in sorted({r["pool_hops"] for r in routers})},
        },
        "router_total_cu_by_pool_hops": {str(n): stats([r["cu"] for r in routers if r["pool_hops"] == n])
                                         for n in sorted({r["pool_hops"] for r in routers})},
    }

    out = Path(__file__).resolve().parent.parent / "public" / "tino-changes" / "evidence" / f"stable-routing-{started:%Y-%m-%d}"
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "compute-units.csv", rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
