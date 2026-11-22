#!/usr/bin/env python3
"""Tally the instructions recent Farm v3, v5 and v6 transactions use, to see how rewards are claimed, and save the evidence.

The farm programs' source and IDLs are not public. The pinned SDK (raydium-sdk-V2 at 32a184e,
src/raydium/farm/instruction.ts) encodes each version's Deposit and Withdraw as a one-byte tag
followed by a u64 amount: v6 Deposit 1 / Withdraw 2, v5 Deposit 11 / Withdraw 12, v3 Deposit 10 /
Withdraw 11. Its `harvestAllRewards` (farm.ts) sends Withdraw with amount 0 on every version, and
`createAssociatedLedgerAccountInstruction` creates a user ledger with tag 9 on v3 and 10 on v5.
On v6, tags 0, 3, 4 and 5 are the farm creator's create, restart-reward, add-reward and
withdraw-reward calls.

For each program, this script samples recent successful transactions and counts every
invocation (top-level and CPI) by tag, splitting Deposit and Withdraw by whether the amount is
zero.

Writes public/tino-changes/evidence/farm-claims-<UTC date>/result.json.

Run: py -I scripts/check-farm-claims.py [--txs 1000] --rpc-url <url> --rpc-token-env NAME
The token is sent as `x-token` and never written to the evidence.
"""

import argparse
import json
import os
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

RPC = "https://api.mainnet-beta.solana.com"
HEADERS = {"content-type": "application/json", "user-agent": "docs-measurement/1.0"}
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
PROGRAMS = {  # see reference/program-addresses
    "v6": ("FarmqiPv5eAj3j1GMdMCMUGXqPUvmquZtMy86QH6rzhG",
           {0: "CreateFarm", 1: "Deposit", 2: "Withdraw", 3: "RestartReward", 4: "AddNewReward", 5: "CreatorWithdrawReward"},
           {1, 2}),
    "v5": ("9KEPoZmtHUrBbhWN1v1KWLMkkvwY6WLtAVUCPRtRjP4z", {10: "CreateAssociatedLedger", 11: "Deposit", 12: "Withdraw"}, {11, 12}),
    "v3": ("EhhTKczWMGQt46ynNeRX1WfeagwwJd7ufHvCDjRxjo5Q", {9: "CreateAssociatedLedger", 10: "Deposit", 11: "Withdraw"}, {10, 11}),
}


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for attempt in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(RPC, data=body, headers=HEADERS), timeout=120) as resp:
                reply = json.load(resp)
            if "error" not in reply:
                return reply["result"]
        except Exception:
            pass
        time.sleep(1.0 * (attempt + 1))
    return None


def b58decode(text):
    n = 0
    for c in text:
        n = n * 58 + ALPHABET.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(text) - len(text.lstrip("1"))) + raw


def tally(program, tags, amount_tags, wanted):
    sigs, before = [], None
    while len(sigs) < wanted:
        page = rpc("getSignaturesForAddress", [program, {"limit": 1000, **({"before": before} if before else {})}])
        if not page:
            break
        sigs += [s["signature"] for s in page if s["err"] is None][: wanted - len(sigs)]
        before = page[-1]["signature"]

    def fetch(sig):
        return sig, rpc("getTransaction", [sig, {"encoding": "json", "maxSupportedTransactionVersion": 1}])

    with ThreadPoolExecutor(6) as pool:
        fetched = list(pool.map(fetch, sigs))

    counts, examples, times, claim_accounts = Counter(), defaultdict(list), [], []
    for sig, tx in fetched:
        if not tx:
            continue
        times.append(tx.get("blockTime") or 0)
        msg, meta = tx["transaction"]["message"], tx["meta"]
        keys = msg["accountKeys"] + (meta.get("loadedAddresses") or {}).get("writable", []) + (meta.get("loadedAddresses") or {}).get("readonly", [])
        inner = [i for g in meta.get("innerInstructions") or [] for i in g["instructions"]]
        for ix in msg["instructions"] + inner:
            if keys[ix["programIdIndex"]] != program:
                continue
            raw = b58decode(ix["data"])
            tag = raw[0] if raw else None
            label = tags.get(tag, f"tag {tag}")
            if tag in amount_tags and len(raw) >= 9:
                label += " amount=0" if int.from_bytes(raw[1:9], "little") == 0 else " amount>0"
            counts[label] += 1
            if len(examples[label]) < 5:
                examples[label].append(sig)
            if label == "Withdraw amount=0" and len(claim_accounts) < 3:
                # Account roles of a claim: each account's token mint and token owner, where the
                # transaction's token balances show one, so the LP vault, LP account and reward
                # vault/ATA pairs can be told apart.
                balances = {b["accountIndex"]: b for b in (meta.get("preTokenBalances") or []) + (meta.get("postTokenBalances") or [])}
                claim_accounts.append({"signature": sig, "data_bytes": len(raw), "accounts": [
                    {"position": pos, "pubkey": keys[a], "signer": a < msg["header"]["numRequiredSignatures"],
                     "token_mint": balances.get(a, {}).get("mint"), "token_owner": balances.get(a, {}).get("owner")}
                    for pos, a in enumerate(ix["accounts"])]})
    times = [t for t in times if t]
    return {"program": program, "sdk_tags": {str(k): v for k, v in tags.items()}, "transactions": len(sigs),
            "block_time_range": [datetime.fromtimestamp(min(times), timezone.utc).isoformat(),
                                 datetime.fromtimestamp(max(times), timezone.utc).isoformat()] if times else None,
            "invocations_by_instruction": dict(counts.most_common()), "example_signatures": examples,
            "claim_account_samples": claim_accounts}


def main():
    global RPC
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--txs", type=int, default=1000, help="successful transactions to sample per program")
    parser.add_argument("--rpc-url", default=RPC)
    parser.add_argument("--rpc-token-env", metavar="NAME")
    args = parser.parse_args()
    RPC = args.rpc_url
    if args.rpc_token_env:
        HEADERS["x-token"] = os.environ[args.rpc_token_env]
    started = datetime.now(timezone.utc)

    summary = {"generated_at": started.isoformat(), "sdk": "raydium-io/raydium-sdk-V2@32a184eb0aea15ddbb485e24a1a73d3723fd94d6",
               "farms": {name: tally(program, tags, amount_tags, args.txs) for name, (program, tags, amount_tags) in PROGRAMS.items()}}
    out = Path(__file__).resolve().parent.parent / "public" / "tino-changes" / "evidence" / f"farm-claims-{started:%Y-%m-%d}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    for name, farm in summary["farms"].items():
        print(name, farm["transactions"], farm["block_time_range"], json.dumps(farm["invocations_by_instruction"]))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
