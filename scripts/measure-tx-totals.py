#!/usr/bin/env python3
"""Measure whole-transaction compute around direct Raydium swaps, and save the evidence.

Reads a compute-units.csv written by scripts/measure-compute.py, takes the swaps that were
called directly (top-level, not through another program), fetches each transaction, and
writes transaction-totals.csv next to it:

- total_cu         the whole transaction's computeUnitsConsumed
- requested_limit  the SetComputeUnitLimit value, if the transaction set one
- compute_budget   how many Compute Budget instructions the transaction has
- unlogged_cu      total_cu minus the "consumed" lines of the top-level programs; only
                   filled when every other top-level program logs its own consumption, so
                   it is the cost of the Compute Budget instructions alone

It prints medians per swap type, and the unlogged cost per Compute Budget instruction.

Run: py -I scripts/measure-tx-totals.py public/tino-changes/evidence/compute-<date>/compute-units.csv [--per-type 80]

Use `--rpc-url` with `--rpc-token-env NAME` for an authenticated RPC. The token is sent as
`x-token` and never written to the evidence.
"""

import argparse
import csv
import json
import os
import re
import statistics
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RPC = "https://api.mainnet-beta.solana.com"
HEADERS = {"content-type": "application/json", "user-agent": "docs-measurement/1.0"}
COMPUTE_BUDGET = "ComputeBudget111111111111111111111111111111"
SWAPS = {("AMM v4", "SwapBaseInV2"), ("AMM v4", "SwapBaseIn (v1)"), ("CPMM", "swap_base_input"), ("CLMM", "swap_v2"), ("CLMM", "swap")}
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
INVOKE = re.compile(r"^Program (\S+) invoke \[(\d+)\]$")
CONSUMED = re.compile(r"^Program (\S+) consumed (\d+) of \d+ compute units$")
ENDED = re.compile(r"^Program (\S+) (success|failed)")


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for attempt in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(RPC, data=body, headers=HEADERS), timeout=90) as resp:
                reply = json.load(resp)
            if "error" not in reply:
                return reply["result"]
        except Exception:
            pass
        time.sleep(1.0 * (attempt + 1))
    return None


def b58decode(text):
    number = 0
    for char in text:
        number = number * 58 + ALPHABET.index(char)
    return number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""


def totals(signature):
    tx = rpc("getTransaction", [signature, {"encoding": "json", "maxSupportedTransactionVersion": 1}])
    if not tx:
        return None
    meta, message = tx["meta"], tx["transaction"]["message"]
    loaded = meta.get("loadedAddresses") or {}
    keys = message["accountKeys"] + loaded.get("writable", []) + loaded.get("readonly", [])
    programs = [keys[ix["programIdIndex"]] for ix in message["instructions"]]
    limit = None
    for ix, program in zip(message["instructions"], programs):
        raw = b58decode(ix["data"])
        if program == COMPUTE_BUDGET and raw[:1] == b"\x02":
            limit = int.from_bytes(raw[1:5], "little")
    depth, top, logged = 0, 0, 0
    for line in meta.get("logMessages") or []:
        if match := INVOKE.match(line):
            depth = int(match.group(2))
        elif (match := CONSUMED.match(line)) and depth == 1:
            top += int(match.group(2))
            logged += 1
        elif ENDED.match(line):
            depth -= 1
    budget = programs.count(COMPUTE_BUDGET)
    clean = budget and logged == len(programs) - budget
    return {"total_cu": meta["computeUnitsConsumed"], "requested_limit": limit if limit is not None else "",
            "compute_budget": budget, "unlogged_cu": meta["computeUnitsConsumed"] - top if clean else ""}


def main():
    global RPC
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv", help="compute-units.csv from scripts/measure-compute.py")
    parser.add_argument("--per-type", type=int, default=80, help="direct swaps to read per swap type")
    parser.add_argument("--rpc-url", default=RPC)
    parser.add_argument("--rpc-token-env", metavar="NAME")
    args = parser.parse_args()
    RPC = args.rpc_url
    if args.rpc_token_env:
        HEADERS["x-token"] = os.environ[args.rpc_token_env]

    picked, seen = defaultdict(list), set()
    with open(args.csv, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row["program"], row["instruction"])
            if key in SWAPS and row["caller"] == "top-level" and row["signature"] not in seen and len(picked[key]) < args.per_type:
                picked[key].append(row)
                seen.add(row["signature"])
    jobs = [(key, row) for key, rows in picked.items() for row in rows]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda job: totals(job[1]["signature"]), jobs))

    out_rows = []
    for (key, row), result in zip(jobs, results):
        if result:
            out_rows.append({"signature": row["signature"], "program": key[0], "instruction": key[1],
                             "program_cu": row["cu"], **result})
    out = Path(args.csv).with_name("transaction-totals.csv")
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(out_rows[0]))
        writer.writeheader()
        writer.writerows(out_rows)

    for key in sorted(picked):
        rows = [r for r in out_rows if (r["program"], r["instruction"]) == key]
        limits = [r["requested_limit"] for r in rows if r["requested_limit"] != ""]
        print(f"{key[0]} {key[1]}: n={len(rows)} program CU median {statistics.median(int(r['program_cu']) for r in rows):,.0f}"
              f" | whole transaction median {statistics.median(r['total_cu'] for r in rows):,.0f}"
              f" | requested limit median {statistics.median(limits):,.0f} ({len(limits)} set one)" if rows and limits else f"{key}: n={len(rows)}")
    per_ix = Counter(r["unlogged_cu"] / r["compute_budget"] for r in out_rows if r["unlogged_cu"] != "")
    print("unlogged CU per Compute Budget instruction:", dict(per_ix), f"({sum(per_ix.values())} transactions)")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
