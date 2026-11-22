#!/usr/bin/env python3
"""Read the on-chain CPMM facts cited in the CPMM docs, and save the evidence.

Reads mainnet through the configured Solana RPC and the Raydium API, and writes, under
public/tino-changes/evidence/cpmm-<UTC date>/:

- amm-configs.csv         Every CPMM AmmConfig account: index, rates, create-pool fee,
                          fee owners, and whether the cpmm-config API lists it.
- creator-fee-shares.csv  Every CreatorFeeShare account: creator, config and share rate.
- pool-lp-supply.csv      The CPMM pools among the highest-TVL standard pools listed by
                          api-v3: PoolState.lp_supply against the LP mint's supply, and the
                          pool's status and creator-fee settings.
- summary.json            Parameters, counts and the figures the docs quote.

Compute-unit figures for CPMM swaps come from scripts/measure-amm-v4.py, which samples
CPMM transactions alongside AMM v4.

Run: py -I scripts/measure-cpmm.py [--pages 2]

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
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RPC = "https://api.mainnet-beta.solana.com"
CONFIG_API = "https://api-v3.raydium.io/main/cpmm-config"
POOL_API = "https://api-v3.raydium.io/pools/info/list?poolType=standard&poolSortField=liquidity&sortType=desc&pageSize=1000&page={page}"
CPMM = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"  # see reference/program-addresses
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
HEADERS = {"content-type": "application/json", "user-agent": "docs-measurement/1.0"}
FEE_ON = {0: "BothToken", 1: "OnlyToken0", 2: "OnlyToken1"}

# PoolState layout (programs/cp-swap/src/states/pool.rs): 8-byte discriminator, ten pubkeys,
# then auth_bump, status, three decimals bytes, seven u64s, creator_fee_on, enable_creator_fee.
POOL_STATUS = 8 + 10 * 32 + 1
POOL_LP_SUPPLY = 8 + 10 * 32 + 5
POOL_CREATOR_FEE_ON = POOL_LP_SUPPLY + 7 * 8
POOL_ENABLE_CREATOR_FEE = POOL_CREATOR_FEE_ON + 1


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
    if "error" in reply:
        raise RuntimeError(f"{method}: {reply['error']}")
    return reply["result"]


def get_json(url):
    req = urllib.request.Request(url, headers={"user-agent": HEADERS["user-agent"]})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.load(resp)


def b58encode(raw):
    number = int.from_bytes(raw, "big")
    text = ""
    while number:
        number, rem = divmod(number, 58)
        text = ALPHABET[rem] + text
    return "1" * (len(raw) - len(raw.lstrip(b"\x00"))) + text


def discriminator(name):
    return hashlib.sha256(f"account:{name}".encode()).digest()[:8]


def program_accounts(name, size):
    filters = [{"dataSize": size}, {"memcmp": {"offset": 0, "bytes": b58encode(discriminator(name))}}]
    result = rpc("getProgramAccounts", [CPMM, {"encoding": "base64", "filters": filters}])
    return [(item["pubkey"], base64.b64decode(item["account"]["data"][0])) for item in result]


def u64(data, offset):
    return int.from_bytes(data[offset:offset + 8], "little")


def amm_configs(api_ids):
    rows = []
    for key, data in program_accounts("AmmConfig", 236):
        rows.append({
            "index": int.from_bytes(data[10:12], "little"),
            "address": key,
            "in_cpmm_config_api": key in api_ids,
            "disable_create_pool": bool(data[9]),
            "trade_fee_rate": u64(data, 12),
            "protocol_fee_rate": u64(data, 20),
            "fund_fee_rate": u64(data, 28),
            "create_pool_fee_lamports": u64(data, 36),
            "protocol_owner": b58encode(data[44:76]),
            "fund_owner": b58encode(data[76:108]),
            "creator_fee_rate": u64(data, 108),
            "creator_fee_share_rate": u64(data, 116),
        })
    return sorted(rows, key=lambda r: r["index"])


def creator_fee_shares():
    rows = [{"address": key, "creator": b58encode(data[9:41]), "amm_config": b58encode(data[41:73]),
             "share_rate": u64(data, 73)} for key, data in program_accounts("CreatorFeeShare", 145)]
    return sorted(rows, key=lambda r: (r["creator"], r["amm_config"]))


def pool_lp_supply(pages):
    pools = []
    for page in range(1, pages + 1):
        pools += [p for p in get_json(POOL_API.format(page=page))["data"]["data"] if p["programId"] == CPMM]
    rows = []
    for start in range(0, len(pools), 50):
        chunk = pools[start:start + 50]
        states = rpc("getMultipleAccounts", [[p["id"] for p in chunk], {"encoding": "base64"}])["value"]
        mints = rpc("getMultipleAccounts", [[p["lpMint"]["address"] for p in chunk], {"encoding": "base64"}])["value"]
        for pool, state, mint in zip(chunk, states, mints):
            if not state or not mint:
                continue
            data = base64.b64decode(state["data"][0])
            mint_supply = u64(base64.b64decode(mint["data"][0]), 36)
            lp_supply = u64(data, POOL_LP_SUPPLY)
            rows.append({
                "pool": pool["id"],
                "tvl_usd": round(pool.get("tvl") or 0),
                "status": data[POOL_STATUS],
                "lp_supply": lp_supply,
                "lp_mint_supply": mint_supply,
                "gap": lp_supply - mint_supply,
                "enable_creator_fee": bool(data[POOL_ENABLE_CREATOR_FEE]),
                "creator_fee_on": FEE_ON.get(data[POOL_CREATOR_FEE_ON], data[POOL_CREATOR_FEE_ON]),
            })
        time.sleep(0.4)
    return rows


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
    parser.add_argument("--pages", type=int, default=2, help="api-v3 pages of 1,000 standard pools to scan")
    parser.add_argument("--rpc-url", default=RPC, help="Solana JSON-RPC endpoint")
    parser.add_argument("--rpc-label", default="Solana public mainnet RPC",
                        help="provider label written to summary.json; do not include credentials")
    parser.add_argument("--rpc-token-prompt", action="store_true",
                        help="prompt for an x-token without storing it in shell history")
    args = parser.parse_args()
    RPC = args.rpc_url
    if args.rpc_token_prompt:
        HEADERS["x-token"] = getpass.getpass("RPC x-token: ")
    started = datetime.now(timezone.utc)

    api_ids = {c["id"] for c in get_json(CONFIG_API)["data"]}
    configs = amm_configs(api_ids)
    shares = creator_fee_shares()
    pools = pool_lp_supply(args.pages)
    enabled = [p for p in pools if p["enable_creator_fee"]]

    summary = {
        "generated_at": started.isoformat(),
        "rpc_provider": args.rpc_label,
        "slot": rpc("getSlot", []),
        "amm_configs": {
            "on_chain": len(configs),
            "listed_by_cpmm_config_api": sum(c["in_cpmm_config_api"] for c in configs),
            "unlisted_indexes": [c["index"] for c in configs if not c["in_cpmm_config_api"]],
            "creator_fee_rate_range": [min(c["creator_fee_rate"] for c in configs),
                                       max(c["creator_fee_rate"] for c in configs)],
            "creator_fee_share_rate_by_index": {str(c["index"]): c["creator_fee_share_rate"] for c in configs},
            "create_pool_fee_lamports": sorted({c["create_pool_fee_lamports"] for c in configs}),
            "index_0": next((c for c in configs if c["index"] == 0), None),
        },
        "creator_fee_shares": {
            "accounts": len(shares),
            "distinct_creators": len({s["creator"] for s in shares}),
            "share_rates": sorted({s["share_rate"] for s in shares}),
        },
        "pool_lp_supply": {
            "standard_pools_scanned": args.pages * 1000,
            "cpmm_pools_read": len(pools),
            "lowest_tvl_usd": min((p["tvl_usd"] for p in pools), default=None),
            "gap_exactly_100": sum(p["gap"] == 100 for p in pools),
            "gap_above_100": sum(p["gap"] > 100 for p in pools),
            "gap_below_100": sum(p["gap"] < 100 for p in pools),
            "status_nonzero": sum(p["status"] != 0 for p in pools),
            "creator_fee_enabled": len(enabled),
            "creator_fee_on_when_enabled": {name: sum(p["creator_fee_on"] == name for p in enabled)
                                            for name in FEE_ON.values()},
        },
    }

    out = Path(__file__).resolve().parent.parent / "public" / "tino-changes" / "evidence" / f"cpmm-{started:%Y-%m-%d}"
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "amm-configs.csv", configs)
    write_csv(out / "creator-fee-shares.csv", shares)
    write_csv(out / "pool-lp-supply.csv", pools)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
