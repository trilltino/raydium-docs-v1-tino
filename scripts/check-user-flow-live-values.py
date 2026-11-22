#!/usr/bin/env python3
"""Capture the live Raydium UI and API values the user-flow pages quote, and save the evidence.

The user-flow pages quote values that come from the production UI and public APIs, not from
program source:

- the LaunchLab referral `shareFeeRate` the UI sends when a link carries `lreferrer` (1%);
- the UI's default LaunchLab slippage (2.5%);
- the CPMM fee tiers the UI shows (`showWithUI` in the CPMM config API);
- the public SOL LaunchLab config's default and minimum raise, maximum share-fee rate,
  maximum lock rate and minimum migration rate.

The UI values are read from the production page's `_app` bundle as text (never executed). The
script records the bundle's URL and SHA-256 with short matched snippets, and saves the two API
responses verbatim.

Writes public/tino-changes/evidence/user-flows-<UTC date>/{summary,ui-bundle}.json,
cpmm-config.json and launchlab-configs.json.

Run: py -I scripts/check-user-flow-live-values.py
"""

import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PAGE = "https://raydium.io/launchpad/"
CPMM_CONFIG_API = "https://api-v3.raydium.io/main/cpmm-config"
LAUNCHLAB_CONFIG_API = "https://launch-mint-v1.raydium.io/main/configs"
WSOL = "So11111111111111111111111111111111111111112"
HEADERS = {"user-agent": "Mozilla/5.0 (docs-measurement/1.0)"}
LAUNCHLAB_RATE_DENOMINATOR = 1_000_000  # LaunchLab rates are parts per million
CPMM_RATE_DENOMINATOR = 1_000_000


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=120) as resp:
        return resp.read()


def number(text):
    value = float(text)
    return int(value) if value.is_integer() else value


def read_ui_bundle():
    html = get(PAGE).decode("utf-8", "replace")
    app_path = re.search(r'src="(/_next/static/chunks/pages/_app-[0-9a-f]+\.js)"', html).group(1)
    raw = get("https://raydium.io" + app_path)
    js = raw.decode("utf-8", "replace")

    # function y(){const e=(0,i.KM)().lreferrer;...return{wallet:new o.PublicKey(e),shareFeeRate:l.GH}...}
    handler = re.search(r'lreferrer;if\(!e\)return\{wallet:void 0,shareFeeRate:\w+\};try\{return\{wallet:new \w+\.PublicKey\(e\),shareFeeRate:(\w+)\.(\w+)\}', js)
    alias, export = handler.groups()
    module_start = js.rfind('function(e,t,n){"use strict";', 0, handler.start())
    module_id = re.search(r'\b' + alias + r'=n\((\d+)\)', js[module_start:handler.start()]).group(1)
    module = js[js.find(module_id + ':function(e,t,n){'):][:20000]
    local = re.search(export + r':function\(\)\{return (\w+)\}', module).group(1)
    definition = re.search(r'\b' + local + r'=new\(\w+\(\)\)\(([0-9.e]+)\)', module)
    rate = number(definition.group(1))

    store = re.search(r'mintHost:"https://launch-mint-v1-devnet\.raydium\.io"\}:\w+,slippage:([0-9.e]+),', js)
    slippage = number(store.group(1))

    def snippet(match, before, after, text=js):
        return text[max(0, match.start() - before):match.end() + after]

    return {
        "page": PAGE,
        "bundle": "https://raydium.io" + app_path,
        "bundle_bytes": len(raw),
        "bundle_sha256": hashlib.sha256(raw).hexdigest(),
        "launchlab_referral": {
            "share_fee_rate": rate,
            "percent": rate / LAUNCHLAB_RATE_DENOMINATOR * 100,
            "resolved": f"shareFeeRate:{alias}.{export} -> module {module_id} export {export} = {local} = {definition.group(0)}",
            "handler_snippet": snippet(handler, 40, 80),
            "constant_snippet": snippet(definition, 40, 20, module),
        },
        "launchlab_default_slippage": {"value": slippage, "percent": slippage * 100, "snippet": snippet(store, 60, 40)},
    }


def main():
    started = datetime.now(timezone.utc)
    out = Path(__file__).resolve().parent.parent / "public" / "tino-changes" / "evidence" / f"user-flows-{started:%Y-%m-%d}"
    out.mkdir(parents=True, exist_ok=True)

    ui = read_ui_bundle()
    cpmm_raw, launch_raw = get(CPMM_CONFIG_API), get(LAUNCHLAB_CONFIG_API)
    (out / "cpmm-config.json").write_bytes(cpmm_raw)
    (out / "launchlab-configs.json").write_bytes(launch_raw)

    cpmm = json.loads(cpmm_raw)["data"]
    ui_tiers = sorted({c["tradeFeeRate"] for c in cpmm if c.get("showWithUI")})
    sol = next(c for c in json.loads(launch_raw)["data"]["data"] if c["key"]["mintB"] == WSOL and c.get("showWithUI"))
    key, decimals = sol["key"], sol["mintInfoB"]["decimals"]

    summary = {
        "generated_at": started.isoformat(),
        "ui_bundle": {k: ui[k] for k in ("bundle", "bundle_sha256")},
        "launchlab_referral_percent": ui["launchlab_referral"]["percent"],
        "launchlab_default_slippage_percent": ui["launchlab_default_slippage"]["percent"],
        "cpmm_ui_trade_fee_percents": [r / CPMM_RATE_DENOMINATOR * 100 for r in ui_tiers],
        "cpmm_configs_in_api": len(cpmm),
        "launchlab_public_sol_config": {
            "pubkey": key["pubKey"],
            "default_raise_sol": int(sol["defaultParams"]["totalFundRaisingB"]) / 10 ** decimals,
            "minimum_raise_sol": int(key["minFundRaisingB"]) / 10 ** decimals,
            "max_share_fee_percent": int(key["maxShareFeeRate"]) / LAUNCHLAB_RATE_DENOMINATOR * 100,
            "max_lock_percent": int(key["maxLockRate"]) / LAUNCHLAB_RATE_DENOMINATOR * 100,
            "min_migrate_percent": int(key["minMigrateRateA"]) / LAUNCHLAB_RATE_DENOMINATOR * 100,
        },
        "sources": {"cpmm_config": CPMM_CONFIG_API, "launchlab_configs": LAUNCHLAB_CONFIG_API},
    }
    (out / "ui-bundle.json").write_text(json.dumps({"generated_at": started.isoformat(), **ui}, indent=2) + "\n", encoding="utf-8", newline="\n")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
