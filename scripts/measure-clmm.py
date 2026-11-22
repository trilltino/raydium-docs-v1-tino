#!/usr/bin/env python3
"""Read the on-chain CLMM facts cited in the CLMM docs, and save the evidence.

Reads mainnet through the configured Solana RPC and the Raydium API, and writes, under
public/tino-changes/evidence/clmm-<UTC date>/:

- amm-configs.csv          Every CLMM AmmConfig: index, rates, tick spacing, fee owners,
                           and whether the clmm-config API lists it.
- dynamic-fee-configs.csv  Every DynamicFeeConfig and its calibration.
- pools.csv                The CLMM pools among the highest-TVL concentrated pools listed
                           by api-v3: status bits, fee_on, seed_index, dynamic fee, active
                           reward slots, open_time, and the tick spacing against its config.
- summary.json             Parameters, counts and the figures the docs quote.

Layouts come from raydium-clmm at 6d7a0f82 (programs/amm/src/states). PoolState is
`#[repr(C, packed)]`, so field offsets are plain sums of field sizes.

Run: py -I scripts/measure-clmm.py [--pages 2]

For an authenticated RPC, pass `--rpc-url` with `--rpc-token-env NAME`. The token is sent
as `x-token` and never written to the evidence.
"""

import argparse
import base64
import csv
import hashlib
import json
import os
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

RPC = "https://api.mainnet-beta.solana.com"
CLMM = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"  # see reference/program-addresses
CONFIG_API = "https://api-v3.raydium.io/main/clmm-config"
POOL_API = "https://api-v3.raydium.io/pools/info/list?poolType=concentrated&poolSortField=liquidity&sortType=desc&pageSize=1000&page={page}"
HEADERS = {"content-type": "application/json", "user-agent": "docs-measurement/1.0"}
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
FEE_ON = {0: "FromInput", 1: "Token0Only", 2: "Token1Only"}
STATUS_BITS = ["OpenPositionOrIncreaseLiquidity", "DecreaseLiquidity", "CollectFee", "CollectReward", "Swap", "LimitOrder"]

# PoolState offsets (packed): 8 discriminator, bump, 7 pubkeys, decimals, spacing, liquidity, sqrt price,
# tick, paddings, fee growths, protocol fees, padding5, then status / fee_on / seed_index.
P_TICK_SPACING, P_STATUS, P_FEE_ON, P_SEED_INDEX = 235, 389, 390, 391
P_REWARDS, REWARD_LEN = 397, 169
P_OPEN_TIME, P_DYNAMIC = 1080, 1096
AMM_CONFIG_LEN, DYNAMIC_FEE_CONFIG_LEN, LIMIT_ORDER_LEN = 117, 88, 173


def post(payload):
    body = json.dumps(payload).encode()
    for attempt in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(RPC, data=body, headers=HEADERS), timeout=120) as resp:
                reply = json.load(resp)
            if "error" not in reply:
                return reply["result"]
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{payload['method']} kept failing")


def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"user-agent": HEADERS["user-agent"]}), timeout=90) as resp:
        return json.load(resp)


def b58encode(raw):
    number, text = int.from_bytes(raw, "big"), ""
    while number:
        number, rem = divmod(number, 58)
        text = ALPHABET[rem] + text
    return "1" * (len(raw) - len(raw.lstrip(b"\x00"))) + text


def accounts(name, size, data_slice=None):
    disc = b58encode(hashlib.sha256(f"account:{name}".encode()).digest()[:8])
    config = {"encoding": "base64", "filters": [{"dataSize": size}, {"memcmp": {"offset": 0, "bytes": disc}}]}
    if data_slice:
        config["dataSlice"] = data_slice
    return [(a["pubkey"], base64.b64decode(a["account"]["data"][0])) for a in post({"jsonrpc": "2.0", "id": 1, "method": "getProgramAccounts", "params": [CLMM, config]})]


def u(data, offset, size):
    return int.from_bytes(data[offset:offset + size], "little")


def main():
    global RPC
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pages", type=int, default=2, help="api-v3 pages of 1,000 concentrated pools to scan")
    parser.add_argument("--rpc-url", default=RPC)
    parser.add_argument("--rpc-label", default="Solana public mainnet RPC")
    parser.add_argument("--rpc-token-env", metavar="NAME")
    args = parser.parse_args()
    RPC = args.rpc_url
    if args.rpc_token_env:
        HEADERS["x-token"] = os.environ[args.rpc_token_env]
    started = datetime.now(timezone.utc)

    api = {c["id"]: c for c in get_json(CONFIG_API)["data"]}
    configs = sorted(({"index": u(d, 9, 2), "address": k, "in_clmm_config_api": k in api,
                       "trade_fee_rate": u(d, 47, 4), "protocol_fee_rate": u(d, 43, 4), "fund_fee_rate": u(d, 53, 4),
                       "tick_spacing": u(d, 51, 2), "owner": b58encode(d[11:43]), "fund_owner": b58encode(d[61:93])}
                      for k, d in accounts("AmmConfig", AMM_CONFIG_LEN)), key=lambda c: c["index"])
    by_config = {c["address"]: c for c in configs}
    dynamic = sorted(({"index": u(d, 8, 2), "address": k, "filter_period": u(d, 10, 2), "decay_period": u(d, 12, 2),
                       "reduction_factor": u(d, 14, 2), "dynamic_fee_control": u(d, 16, 4), "max_volatility_accumulator": u(d, 20, 4)}
                      for k, d in accounts("DynamicFeeConfig", DYNAMIC_FEE_CONFIG_LEN)), key=lambda c: c["index"])
    limit_orders = accounts("LimitOrderState", LIMIT_ORDER_LEN, {"offset": 0, "length": 0})

    listed = []
    for page in range(1, args.pages + 1):
        listed += [p for p in get_json(POOL_API.format(page=page))["data"]["data"] if p["programId"] == CLMM]
    pools = []
    for start in range(0, len(listed), 100):
        chunk = listed[start:start + 100]
        values = post({"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts", "params": [[p["id"] for p in chunk], {"encoding": "base64"}]})["value"]
        for meta, account in zip(chunk, values):
            if not account:
                continue
            d = base64.b64decode(account["data"][0])
            config = by_config.get(b58encode(d[9:41]), {})
            status = d[P_STATUS]
            pools.append({
                "pool": meta["id"], "tvl_usd": round(meta.get("tvl") or 0), "config_index": config.get("index", ""),
                "tick_spacing": u(d, P_TICK_SPACING, 2), "config_tick_spacing": config.get("tick_spacing", ""),
                "status": status, "disabled": "|".join(b for i, b in enumerate(STATUS_BITS) if status >> i & 1),
                "fee_on": FEE_ON.get(d[P_FEE_ON], d[P_FEE_ON]), "seed_index": u(d, P_SEED_INDEX, 2),
                "dynamic_fee": u(d, P_DYNAMIC, 2) != 0 or u(d, P_DYNAMIC + 6, 4) != 0,
                "active_reward_slots": sum(d[P_REWARDS + i * REWARD_LEN] != 0 for i in range(3)),
                "open_time": u(d, P_OPEN_TIME, 8),
            })
        time.sleep(0.2)

    summary = {
        "generated_at": started.isoformat(),
        "rpc_provider": args.rpc_label,
        "slot": post({"jsonrpc": "2.0", "id": 1, "method": "getSlot", "params": []}),
        "amm_configs": {"on_chain": len(configs), "listed_by_clmm_config_api": sum(c["in_clmm_config_api"] for c in configs),
                        "unlisted_indexes": [c["index"] for c in configs if not c["in_clmm_config_api"]],
                        "tiers": [(c["index"], c["trade_fee_rate"], c["tick_spacing"], c["protocol_fee_rate"], c["fund_fee_rate"]) for c in configs],
                        "owners": dict(Counter(c["owner"] for c in configs)), "fund_owners": dict(Counter(c["fund_owner"] for c in configs))},
        "dynamic_fee_configs": len(dynamic),
        "limit_order_accounts": len(limit_orders),
        "pools": {"read": len(pools), "lowest_tvl_usd": min((p["tvl_usd"] for p in pools), default=None),
                  "fee_on": dict(Counter(p["fee_on"] for p in pools)),
                  "seed_index_nonzero": sum(p["seed_index"] != 0 for p in pools),
                  "dynamic_fee": sum(p["dynamic_fee"] for p in pools),
                  "status_nonzero": dict(Counter(p["disabled"] for p in pools if p["status"])),
                  "active_reward_slots": dict(Counter(p["active_reward_slots"] for p in pools)),
                  "open_time_nonzero": sum(p["open_time"] != 0 for p in pools),
                  "spacing_differs_from_config": sum(p["tick_spacing"] != p["config_tick_spacing"] for p in pools),
                  "by_config_index": dict(sorted(Counter(p["config_index"] for p in pools).items(), key=lambda kv: str(kv[0])))},
    }
    out = Path(__file__).resolve().parent.parent / "public" / "tino-changes" / "evidence" / f"clmm-{started:%Y-%m-%d}"
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("amm-configs.csv", configs), ("dynamic-fee-configs.csv", dynamic), ("pools.csv", pools)):
        if rows:
            with (out / name).open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
