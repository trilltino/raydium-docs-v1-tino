#!/usr/bin/env python3
"""Compare the Raydium API's CLMM dynamic-fee configs with the on-chain accounts, and save the evidence.

`/main/clmm-dynamic-config` lists each DynamicFeeConfig with its calibration. This script reads
every DynamicFeeConfig account from mainnet (layout from raydium-clmm at 6d7a0f82, via
`measure-clmm.py`), fetches the API in the same run, and compares the five calibration fields
for each address.

Writes, under public/tino-changes/evidence/clmm-dynamic-config-<UTC date>/:

- api-response.json  The API response, byte for byte.
- comparison.csv     One row per config and field: on-chain value, API value, match.
- summary.json       Counts, the slot the run completed near, and the mismatches.

Run: py -I scripts/check-clmm-dynamic-config-api.py --rpc-url <url> --rpc-token-env NAME
The token is sent as `x-token` and never written to the evidence.
"""

import argparse
import csv
import importlib.util
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "https://api-v3.raydium.io/main/clmm-dynamic-config"
FIELDS = [  # (on-chain name, offset, size, API name)
    ("filter_period", 10, 2, "filterPeriod"),
    ("decay_period", 12, 2, "decayPeriod"),
    ("reduction_factor", 14, 2, "reductionFactor"),
    ("dynamic_fee_control", 16, 4, "dynamicFeeControl"),
    ("max_volatility_accumulator", 20, 4, "maxVolatilityAccumulator"),
]

# Reuse the RPC helpers and layout constants of the CLMM measurement script.
_spec = importlib.util.spec_from_file_location("measure_clmm", HERE / "measure-clmm.py")
clmm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(clmm)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rpc-url", default=clmm.RPC)
    parser.add_argument("--rpc-token-env", metavar="NAME")
    args = parser.parse_args()
    clmm.RPC = args.rpc_url
    if args.rpc_token_env:
        clmm.HEADERS["x-token"] = os.environ[args.rpc_token_env]
    started = datetime.now(timezone.utc)

    on_chain = {k: d for k, d in clmm.accounts("DynamicFeeConfig", clmm.DYNAMIC_FEE_CONFIG_LEN)}
    with urllib.request.urlopen(urllib.request.Request(API, headers={"user-agent": clmm.HEADERS["user-agent"]}), timeout=90) as resp:
        api_raw = resp.read()
    slot = clmm.post({"jsonrpc": "2.0", "id": 1, "method": "getSlot", "params": [{"commitment": "confirmed"}]})
    api = {c["id"]: c for c in json.loads(api_raw)["data"]}

    rows, mismatches = [], []
    for address in sorted(set(on_chain) | set(api), key=lambda a: clmm.u(on_chain[a], 8, 2) if a in on_chain else 99):
        data, listed = on_chain.get(address), api.get(address)
        index = clmm.u(data, 8, 2) if data else listed.get("index")
        for name, offset, size, api_name in FIELDS:
            chain_value = clmm.u(data, offset, size) if data else None
            api_value = listed.get(api_name) if listed else None
            match = chain_value == api_value
            rows.append({"index": index, "address": address, "field": name, "on_chain": chain_value, "api": api_value, "match": match})
            if not match:
                mismatches.append(f"index {index} {name}: on-chain {chain_value}, API {api_value}")

    out = HERE.parent / "public" / "tino-changes" / "evidence" / f"clmm-dynamic-config-{started:%Y-%m-%d}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "api-response.json").write_bytes(api_raw)
    with open(out / "comparison.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = {"generated_at": started.isoformat(), "completed_near_slot": slot, "api": API,
               "on_chain_configs": len(on_chain), "api_configs": len(api),
               "fields_compared": len(rows), "fields_matching": sum(r["match"] for r in rows), "mismatches": mismatches}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
