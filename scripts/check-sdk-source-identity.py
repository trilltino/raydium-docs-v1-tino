#!/usr/bin/env python3
"""Check that the pinned SDK commit's source matches the published npm package, and save the evidence.

The docs pin `@raydium-io/raydium-sdk-v2@0.2.85-alpha` and cite source lines from
raydium-sdk-V2 at 32a184e. This script downloads both tarballs (read in memory, never
extracted or executed), hashes every file under `src/` in each, and compares them.

Writes public/tino-changes/evidence/sdk-source-identity-<UTC date>/manifest.json with each
file's SHA-256 and the files that differ or exist on one side only.

Run: py -I scripts/check-sdk-source-identity.py [--version 0.2.85-alpha] [--commit 32a184e...]
"""

import argparse
import hashlib
import io
import json
import tarfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HEADERS = {"user-agent": "docs-measurement/1.0"}
NPM = "https://registry.npmjs.org/@raydium-io/raydium-sdk-v2/-/raydium-sdk-v2-{version}.tgz"
GITHUB = "https://codeload.github.com/raydium-io/raydium-sdk-V2/tar.gz/{commit}"


def src_hashes(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=180) as resp:
        raw = resp.read()
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        for member in tar.getmembers():
            parts = member.name.split("/", 1)  # drop the top-level folder
            if member.isfile() and len(parts) == 2 and parts[1].startswith("src/"):
                files[parts[1]] = hashlib.sha256(tar.extractfile(member).read()).hexdigest()
    return hashlib.sha256(raw).hexdigest(), files


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", default="0.2.85-alpha")
    parser.add_argument("--commit", default="32a184eb0aea15ddbb485e24a1a73d3723fd94d6")
    args = parser.parse_args()
    started = datetime.now(timezone.utc)

    npm_url, gh_url = NPM.format(version=args.version), GITHUB.format(commit=args.commit)
    npm_sha, npm_files = src_hashes(npm_url)
    gh_sha, gh_files = src_hashes(gh_url)
    differ = sorted(f for f in npm_files.keys() & gh_files.keys() if npm_files[f] != gh_files[f])
    summary = {
        "generated_at": started.isoformat(),
        "npm": {"url": npm_url, "tarball_sha256": npm_sha, "src_files": len(npm_files)},
        "github": {"url": gh_url, "tarball_sha256": gh_sha, "src_files": len(gh_files)},
        "identical": not differ and npm_files.keys() == gh_files.keys(),
        "differ": differ,
        "npm_only": sorted(npm_files.keys() - gh_files.keys()),
        "github_only": sorted(gh_files.keys() - npm_files.keys()),
        "src_sha256": dict(sorted(npm_files.items())),
    }
    out = Path(__file__).resolve().parent.parent / "public" / "tino-changes" / "evidence" / f"sdk-source-identity-{started:%Y-%m-%d}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "src_sha256"}, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
