#!/usr/bin/env python3
"""Find which LaunchLab transaction starts the vesting clock, from mainnet execution, and save the evidence.

LaunchLab's source is not public. Its IDL (raydium-io/raydium-idl at e7e0c96) gives the
PoolState layout: VestingSchedule { total_locked_amount, cliff_period, unlock_period,
start_time, allocated_share_amount } at byte 101, and status at byte 17. The docs disagree on
whether start_time is set when fundraising ends or during migration.

PoolState has no other timestamp field, so whichever transaction wrote start_time did so at
block time `start_time - cliff_period`. For migrated pools that lock tokens with a cliff, this
script lists the transactions on the pool within 60 s of that time, decodes their LaunchLab
instructions and each TradeEvent's `pool_status` (emitted by CPI), and records the completing
buy (the first successful trade whose event reports status Migrate, by slot) and the migrate
transaction, with their offsets from the clock start.

Writes public/tino-changes/evidence/launchlab-vesting-<UTC date>/result.json.

Run: py -I scripts/check-launchlab-vesting.py [--pools 6] --rpc-url <url> --rpc-token-env NAME
The token is sent as `x-token` and never written to the evidence.
"""

import argparse
import base64
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RPC = "https://api.mainnet-beta.solana.com"
LAUNCHLAB = "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"  # see reference/program-addresses
HEADERS = {"content-type": "application/json", "user-agent": "docs-measurement/1.0"}
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
POOL_DISC = bytes([247, 237, 227, 245, 215, 195, 222, 70])
NAMES = {  # instruction discriminators from the IDL
    bytes([250, 234, 13, 123, 213, 156, 19, 236]): "buy_exact_in",
    bytes([24, 211, 116, 40, 105, 3, 153, 56]): "buy_exact_out",
    bytes([136, 92, 200, 103, 28, 218, 144, 140]): "migrate_to_cpswap",
    bytes([207, 82, 192, 145, 254, 207, 145, 223]): "migrate_to_amm",
    bytes([49, 33, 104, 30, 189, 157, 79, 35]): "claim_vested_token",
}
STATUS_OFFSET, VESTING_OFFSET = 17, 101
EVENT_CPI_TAG = bytes([228, 69, 165, 46, 81, 203, 154, 29])  # Anchor emit_cpi prefix
TRADE_EVENT = bytes([189, 219, 127, 211, 78, 230, 97, 238])
TRADE_EVENT_HEAD = 16 + 32  # emit_cpi tag, event discriminator, pool_state
STATUSES = ["Fund", "Migrate", "Trade"]


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for attempt in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(RPC, data=body, headers=HEADERS), timeout=300) as resp:
                reply = json.load(resp)
            if "error" not in reply:
                return reply["result"]
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{method} kept failing")


def b58(raw):
    n, s = int.from_bytes(raw, "big"), ""
    while n:
        n, r = divmod(n, 58)
        s = ALPHABET[r] + s
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + s


def b58decode(text):
    n = 0
    for c in text:
        n = n * 58 + ALPHABET.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(text) - len(text.lstrip("1"))) + raw


def launchlab_calls(tx, pool):
    """Names of the LaunchLab instructions in a transaction, and the pool_status its TradeEvents report for `pool`."""
    msg, meta = tx["transaction"]["message"], tx["meta"]
    keys = msg["accountKeys"] + (meta.get("loadedAddresses") or {}).get("writable", []) + (meta.get("loadedAddresses") or {}).get("readonly", [])
    inner = [i for g in meta.get("innerInstructions") or [] for i in g["instructions"]]
    names, statuses = [], []
    for ix in msg["instructions"] + inner:
        if keys[ix["programIdIndex"]] != LAUNCHLAB:
            continue
        raw = b58decode(ix["data"])
        if raw[:16] == EVENT_CPI_TAG + TRADE_EVENT:
            names.append("TradeEvent")
            # The IDL's TradeEvent is 13 u64s then trade_direction, pool_status, exact_in (155 bytes);
            # older pools emitted 12 u64s then trade_direction, pool_status (146 bytes).
            body = len(raw) - TRADE_EVENT_HEAD
            status = raw[-2] if body % 8 == 3 else raw[-1] if body % 8 == 2 else None
            if b58(raw[16:48]) == pool and status is not None:
                statuses.append(STATUSES[status])
        else:
            names.append(NAMES.get(raw[:8], "other"))
    return names, statuses


def signatures_back_to(address, oldest_time):
    sigs, before = [], None
    while True:
        page = rpc("getSignaturesForAddress", [address, {"limit": 1000, **({"before": before} if before else {})}])
        if not page:
            return sigs
        sigs += page
        before = page[-1]["signature"]
        if (page[-1].get("blockTime") or 0) < oldest_time:
            return sigs


def main():
    global RPC
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pools", type=int, default=6)
    parser.add_argument("--rpc-url", default=RPC)
    parser.add_argument("--rpc-token-env", metavar="NAME")
    args = parser.parse_args()
    RPC = args.rpc_url
    if args.rpc_token_env:
        HEADERS["x-token"] = os.environ[args.rpc_token_env]
    started = datetime.now(timezone.utc)

    found = rpc("getProgramAccounts", [LAUNCHLAB, {"encoding": "base64", "dataSlice": {"offset": VESTING_OFFSET, "length": 32},
                "filters": [{"dataSize": 429}, {"memcmp": {"offset": 0, "bytes": b58(POOL_DISC)}},
                            {"memcmp": {"offset": STATUS_OFFSET, "bytes": b58(bytes([2]))}}]}])
    candidates = []
    for item in found:
        d = base64.b64decode(item["account"]["data"][0])
        locked, cliff, unlock, start = (int.from_bytes(d[i:i + 8], "little") for i in (0, 8, 16, 24))
        if locked and cliff and start:
            candidates.append({"pool": item["pubkey"], "total_locked_amount": locked, "cliff_period": cliff, "unlock_period": unlock, "start_time": start})
    candidates.sort(key=lambda c: -c["start_time"])

    results = []
    for c in candidates[: args.pools]:
        t0 = c["start_time"] - c["cliff_period"]
        sigs = signatures_back_to(c["pool"], t0 - 3600)
        window = [s for s in sigs if s.get("blockTime") is not None and abs(s["blockTime"] - t0) <= 60 and s["err"] is None]
        txs = []
        for s in window:
            tx = rpc("getTransaction", [s["signature"], {"encoding": "json", "maxSupportedTransactionVersion": 1}])
            names, statuses = launchlab_calls(tx, c["pool"]) if tx else (None, None)
            txs.append({"signature": s["signature"], "slot": s["slot"], "block_time": s["blockTime"], "offset_from_t0_s": s["blockTime"] - t0,
                        "launchlab_instructions": names, "trade_event_pool_status": statuses})
        txs.sort(key=lambda x: x["slot"])
        completing = next((x for x in txs if "Migrate" in (x["trade_event_pool_status"] or [])
                           and any(n.startswith("buy") for n in x["launchlab_instructions"] or [])), None)
        migrate = None
        for s in sorted((s for s in sigs if s.get("blockTime") and s["err"] is None and t0 - 600 <= s["blockTime"] <= t0 + 7 * 86400),
                        key=lambda s: s["blockTime"]):
            tx = rpc("getTransaction", [s["signature"], {"encoding": "json", "maxSupportedTransactionVersion": 1}])
            if tx and any(n.startswith("migrate") for n in launchlab_calls(tx, c["pool"])[0]):
                migrate = {"signature": s["signature"], "slot": s["slot"], "block_time": s["blockTime"], "offset_from_t0_s": s["blockTime"] - t0}
                break
        buys_at_t0 = [x["signature"] for x in txs if x["offset_from_t0_s"] == 0 and any(n.startswith("buy") for n in x["launchlab_instructions"] or [])]
        results.append({**c, "clock_started_at": t0, "clock_started_at_utc": datetime.fromtimestamp(t0, timezone.utc).isoformat(),
                        "successful_buys_at_clock_start": buys_at_t0,
                        "completing_buy": completing and {k: completing[k] for k in ("signature", "slot", "block_time", "offset_from_t0_s")},
                        "completing_buy_at_clock_start": bool(completing and completing["offset_from_t0_s"] == 0),
                        "migrate_transaction": migrate,
                        "migration_strictly_after_clock_start": bool(migrate and migrate["offset_from_t0_s"] > 0),
                        "migration_in_later_slot_than_completing_buy": bool(migrate and completing and migrate["slot"] > completing["slot"]),
                        "transactions_within_60s": txs})
        time.sleep(0.3)

    out = Path(__file__).resolve().parent.parent / "public" / "tino-changes" / "evidence" / f"launchlab-vesting-{started:%Y-%m-%d}"
    out.mkdir(parents=True, exist_ok=True)
    summary = {"generated_at": started.isoformat(), "program": LAUNCHLAB, "idl": "raydium-io/raydium-idl@e7e0c96fe77bcf6a020b84a44c47a722aac8e359",
               "migrated_pools_read": len(found), "with_locked_cliff_and_start": len(candidates),
               "pools_checked": len(results),
               "migration_strictly_after_clock_start": sum(r["migration_strictly_after_clock_start"] for r in results),
               "buy_at_clock_start": sum(bool(r["successful_buys_at_clock_start"]) for r in results),
               "completing_buy_found": sum(bool(r["completing_buy"]) for r in results),
               "completing_buy_at_clock_start": sum(r["completing_buy_at_clock_start"] for r in results),
               "migration_in_later_slot_than_completing_buy": sum(r["migration_in_later_slot_than_completing_buy"] for r in results),
               "pools": results}
    (out / "result.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "pools"}, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
